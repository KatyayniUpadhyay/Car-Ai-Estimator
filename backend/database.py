# backend/database.py
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime

# Database URL (SQLite)
DATABASE_URL = "sqlite:///./car_ai.db"

# Engine & Session
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Database model
class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(Integer, primary_key=True, index=True)
    image_path = Column(String, nullable=False)
    damage_type = Column(String, nullable=False)
    location = Column(String, nullable=False)
    cost_inr = Column(Float, nullable=False)
    cost_usd = Column(Float, nullable=False)
    cost_yen = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Dependency to get DB session
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
