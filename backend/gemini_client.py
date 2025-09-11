# backend/gemini_client.py
import json
import re
from io import BytesIO
from typing import Union
from PIL import Image
import google.generativeai as genai

__all__ = ["analyze_damage_bytes", "analyze_image"]

def analyze_damage_bytes(image_bytes: bytes, model_name: str = "gemini-1.5-pro") -> dict:
    """
    Send image bytes to Gemini and return a parsed JSON (dict) when possible.
    If parsing fails, returns {'raw_output': <text>}.
    """
    model = genai.GenerativeModel(model_name)

    prompt = """
You are an expert car damage assessor.

Return the output ONLY as valid JSON in this exact structure:

{
  "damages": [
    {"part": "string (e.g. front bumper)", "damage_type": "string (e.g. dent/scratch/broken)"}
  ],
  "estimated_cost": {
    "usd": "string (range or number, e.g. 50-100 / 75)",
    "inr": "string",
    "jpy": "string"
  },
  "notes": "short note about hidden/structural concerns"
}

Rules:
- Do not print any text outside the JSON object.
- Use plain numbers or ranges inside the cost strings (currency symbol optional).
"""

    # send the prompt + image bytes
    response = model.generate_content([prompt, {"mime_type": "image/png", "data": image_bytes}])
    text = response.text

    # Try direct JSON parse
    try:
        return json.loads(text)
    except Exception:
        # Fallback: extract first JSON object-like substring
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return {"raw_output": text}
        else:
            return {"raw_output": text}


def analyze_image(image: Union[str, bytes, Image.Image], model_name: str = "gemini-1.5-pro") -> dict:
    """
    Convenience wrapper that accepts:
      - a PIL Image object
      - a file path (str)
      - raw bytes
    and returns the same parsed dict as analyze_damage_bytes.
    """
    # If user passed a PIL Image, convert to bytes
    if isinstance(image, Image.Image):
        buf = BytesIO()
        # use PNG for consistent MIME
        image.save(buf, format="PNG")
        buf.seek(0)
        img_bytes = buf.read()
        return analyze_damage_bytes(img_bytes, model_name=model_name)

    # If path string
    if isinstance(image, str):
        with open(image, "rb") as f:
            img_bytes = f.read()
        return analyze_damage_bytes(img_bytes, model_name=model_name)

    # If bytes-like
    if isinstance(image, (bytes, bytearray)):
        return analyze_damage_bytes(bytes(image), model_name=model_name)

    # unknown type
    return {"raw_output": "Unsupported image input type to analyze_image()"}



