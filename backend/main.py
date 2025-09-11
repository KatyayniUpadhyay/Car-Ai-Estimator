# backend/main.py
import os
import uuid
import re
import json
from io import BytesIO
from fastapi import FastAPI, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from PIL import Image
import google.generativeai as genai
from fastapi.staticfiles import StaticFiles
import os


# local imports
from backend.database import SessionLocal, engine, Base, Analysis, get_db
import backend.gemini_client as gemini_client
from sqlalchemy.orm import Session

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY missing in .env")

genai.configure(api_key=API_KEY)

app = FastAPI()

# Allow your frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# make sure uploads dir exists and mount it for static serving
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# helpers
def _parse_number_from_string(s):
    """Extract positive float values from string."""
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return abs(float(s))
    s = str(s)
    s_clean = s.replace(",", "")
    nums = re.findall(r"\d+(?:\.\d+)?", s_clean)  # 🚨 removed the "-" sign
    if not nums:
        return 0.0
    try:
        values = [float(n) for n in nums]
        if len(values) >= 2:
            return sum(values[:2]) / 2.0
        return values[0]
    except:
        return 0.0


def _normalize_analysis(raw):
    """
    Accept parsed JSON from Gemini (various shapes) and return a stable dict:
    {
      damage_type: string or list,
      location: string,
      cost_inr: float,
      cost_usd: float,
      cost_yen: float,
      uploadedImage: (populated later),
      notes: string
    }
    """
    if not isinstance(raw, dict):
        return {
            "damage_type": "Unknown",
            "location": "",
            "cost_inr": 0.0,
            "cost_usd": 0.0,
            "cost_yen": 0.0,
            "notes": str(raw)
        }

    # If Gemini provided the exact structure:
    damages = raw.get("damages") or raw.get("damage") or []
    damage_types = []
    locations = []

    if isinstance(damages, list) and len(damages) > 0:
        for d in damages:
            part = d.get("part") if isinstance(d, dict) else None
            dtype = d.get("damage_type") if isinstance(d, dict) else None
            if dtype and part:
                damage_types.append(f"{dtype} ({part})")
                locations.append(part)
            elif dtype:
                damage_types.append(dtype)
            elif part:
                locations.append(part)
    else:
        # fallback: look for simple fields
        dtype_field = raw.get("damage_type") or raw.get("damage")
        if dtype_field:
            if isinstance(dtype_field, list):
                damage_types = dtype_field
            else:
                damage_types = [str(dtype_field)]

        # maybe a direct location key
        loc = raw.get("location") or raw.get("part")
        if loc:
            if isinstance(loc, list):
                locations.extend(loc)
            else:
                locations.append(str(loc))

    # build damage_type and location strings
    damage_type_out = damage_types if damage_types else (raw.get("damage_type") or "Unknown")
    if isinstance(damage_type_out, list) and len(damage_type_out) == 1:
        damage_type_out = damage_type_out[0]  # single string is friendlier

    location_out = ", ".join(locations) if locations else (raw.get("location") or "")

    # costs: try various keys
    est = raw.get("estimated_cost") or raw.get("estimatedCosts") or {}
    usd_raw = None; inr_raw = None; jpy_raw = None

    if isinstance(est, dict):
        usd_raw = est.get("usd") or est.get("USD") or est.get("dollars")
        inr_raw = est.get("inr") or est.get("INR")
        jpy_raw = est.get("jpy") or est.get("JPY") or est.get("yen")
    else:
        # maybe top-level cost fields
        usd_raw = raw.get("cost_usd") or raw.get("costUSD") or raw.get("usd")
        inr_raw = raw.get("cost_inr") or raw.get("costINR") or raw.get("inr")
        jpy_raw = raw.get("cost_yen") or raw.get("costJPY") or raw.get("jpy")

    cost_usd = _parse_number_from_string(usd_raw)
    cost_inr = _parse_number_from_string(inr_raw)
    cost_yen = _parse_number_from_string(jpy_raw)

    notes = raw.get("notes") or raw.get("note") or raw.get("raw_output") or ""

    return {
        "damage_type": damage_type_out,
        "location": location_out,
        "cost_inr": cost_inr,
        "cost_usd": cost_usd,
        "cost_yen": cost_yen,
        "notes": notes
    }

# API endpoints
@app.post("/analyze/")
async def analyze(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Accepts an image upload, saves file, queries Gemini, normalizes response,
    saves a DB row, and returns {"analysis": <normalized dict>}.
    """
    try:
        contents = await file.read()
        # Save file
        ext = os.path.splitext(file.filename)[1] or ".png"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        with open(save_path, "wb") as f:
            f.write(contents)

        # Send to Gemini and parse
        raw = gemini_client.analyze_damage_bytes(contents)
        normalized = _normalize_analysis(raw)

        # attach uploadedImage (relative path)
        normalized["uploadedImage"] = f"/uploads/{unique_name}"

        # Save to DB (DB requires non-null floats/strings)
        damage_str = normalized["damage_type"] if isinstance(normalized["damage_type"], str) else (", ".join(normalized["damage_type"]) if isinstance(normalized["damage_type"], list) else "Unknown")
        location_str = normalized.get("location", "") or ""
        cost_inr = float(normalized.get("cost_inr") or 0.0)
        cost_usd = float(normalized.get("cost_usd") or 0.0)
        cost_yen = float(normalized.get("cost_yen") or 0.0)

        entry = Analysis(
            image_path=normalized["uploadedImage"],
            damage_type=damage_str,
            location=location_str,
            cost_inr=cost_inr,
            cost_usd=cost_usd,
            cost_yen=cost_yen
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        # Return normalized analysis object (frontend expects it inside `analysis`)
        return {"analysis": normalized}

    except Exception as e:
        return {"analysis": {"error": str(e)}}


# History endpoint returns saved rows (including image_path)
@app.get("/history")
def get_history(db: Session = Depends(get_db)):
    rows = db.query(Analysis).order_by(Analysis.created_at.desc()).all()
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "image_path": r.image_path,   # e.g. /uploads/abcd.png
            "damage_type": r.damage_type,
            "location": r.location,
            "cost_inr": r.cost_inr,
            "cost_usd": r.cost_usd,
            "cost_yen": r.cost_yen,
            "created_at": r.created_at.isoformat()
        })
    return out


# Create tables once at startup if not present
Base.metadata.create_all(bind=engine)

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
