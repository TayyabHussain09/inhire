# app/schemas.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "candidate"


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    name: str


class AssessmentSubmit(BaseModel):
    raw_transcript: str
    target_role: str = "Software Engineer"
    template_id: Optional[int] = None


class VideoUpload(BaseModel):
    video_url: str


class HRScoreUpdate(BaseModel):
    assessment_id: int
    tech_human_final_score: Optional[float] = None
    coding_human_final_score: Optional[float] = None
    behavioral_human_final_score: Optional[float] = None
    is_finally_approved: Optional[bool] = None


class AssessmentResponse(BaseModel):
    id: int
    candidate_id: int
    template_id: Optional[int]
    target_role: Optional[str]
    tech_transcript: Optional[str]
    tech_ai_suggested_score: Optional[float]
    tech_human_final_score: Optional[float]
    tech_status: Optional[str]
    behavioral_video_url: Optional[str]
    behavioral_ai_suggested_score: Optional[float]
    behavioral_human_final_score: Optional[float]
    behavioral_status: Optional[str]
    is_finally_approved: bool
    approved_by_hr_id: Optional[int]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class CandidateProfile(BaseModel):
    id: int
    name: str
    email: str
    role: str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class CandidateDashboardRow(BaseModel):
    id: int
    name: str
    email: str
    target_role: str
    template_name: Optional[str] = None
    tech_ai_score: Optional[float]
    tech_final_score: Optional[float]
    tech_status: Optional[str]
    behavioral_ai_score: Optional[float]
    behavioral_final_score: Optional[float]
    behavioral_status: Optional[str]
    is_finally_approved: bool
    assessment_id: Optional[int]
