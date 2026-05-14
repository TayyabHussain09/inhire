# app/main.py
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import models, routes
from .database import Base, engine

Base.metadata.create_all(bind=engine)

with engine.begin() as connection:
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS template_id INTEGER REFERENCES assessment_templates(id)"))
    connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS hr_level VARCHAR(50) DEFAULT 'senior'"))
    connection.execute(text("ALTER TABLE assessment_templates ADD COLUMN IF NOT EXISTS candidate_level VARCHAR(50) DEFAULT 'intern'"))
    connection.execute(text("ALTER TABLE assessment_templates ADD COLUMN IF NOT EXISTS access_code VARCHAR(100) DEFAULT 'DEFAULT' NOT NULL"))
    connection.execute(text("ALTER TABLE assessment_questions ADD COLUMN IF NOT EXISTS question_type VARCHAR(30) DEFAULT 'theory'"))
    connection.execute(text("ALTER TABLE assessment_questions ADD COLUMN IF NOT EXISTS instructions TEXT"))
    connection.execute(text("ALTER TABLE assessment_questions ADD COLUMN IF NOT EXISTS expected_output TEXT"))
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS coding_status VARCHAR(50) DEFAULT 'locked'"))
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS coding_ai_suggested_score FLOAT"))
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS coding_human_final_score FLOAT"))
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS ai_log TEXT"))
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS proctoring_log TEXT"))
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS retry_allowed BOOLEAN DEFAULT FALSE"))
    connection.execute(text("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS final_status VARCHAR(50) DEFAULT 'in_progress'"))

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="inhire-interview")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(routes.router)

@app.get("/health")
def health():
    return {"status": "inhire-interview is online and routing correctly."}
