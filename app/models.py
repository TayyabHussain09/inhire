# app/models.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="candidate")
    hr_level = Column(String(50), default="senior")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assessments = relationship("Assessment", foreign_keys="[Assessment.candidate_id]", back_populates="candidate")
    created_templates = relationship("AssessmentTemplate", foreign_keys="[AssessmentTemplate.created_by_hr_id]", back_populates="creator")

class AssessmentTemplate(Base):
    __tablename__ = "assessment_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    department = Column(String(100), nullable=False)
    candidate_level = Column(String(50), default="intern")
    access_code = Column(String(100), nullable=False, default="DEFAULT")
    target_role = Column(String(100), nullable=False)
    global_instructions = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_by_hr_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    creator = relationship("User", foreign_keys=[created_by_hr_id], back_populates="created_templates")
    questions = relationship("AssessmentQuestion", foreign_keys="[AssessmentQuestion.template_id]", back_populates="template", cascade="all, delete-orphan")
    assessments = relationship("Assessment", foreign_keys="[Assessment.template_id]", back_populates="template")

class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("assessment_templates.id"), nullable=False)
    round_type = Column(String(20), nullable=False)
    question_type = Column(String(30), default="theory")
    prompt = Column(Text, nullable=False)
    instructions = Column(Text, nullable=True)
    expected_output = Column(Text, nullable=True)
    sort_order = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    template = relationship("AssessmentTemplate", foreign_keys=[template_id], back_populates="questions")
    answers = relationship("AssessmentAnswer", foreign_keys="[AssessmentAnswer.question_id]", back_populates="question", cascade="all, delete-orphan")

class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("assessment_questions.id"), nullable=False)
    answer_text = Column(Text, nullable=True)
    ai_score = Column(Float, nullable=True)
    ai_reasoning = Column(Text, nullable=True)
    ai_raw_response = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assessment = relationship("Assessment", foreign_keys=[assessment_id], back_populates="answers")
    question = relationship("AssessmentQuestion", foreign_keys=[question_id], back_populates="answers")

class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("users.id"))
    template_id = Column(Integer, ForeignKey("assessment_templates.id"), nullable=True)
    target_role = Column(String(100))
    tech_transcript = Column(Text, nullable=True)
    tech_ai_suggested_score = Column(Float, nullable=True)
    tech_human_final_score = Column(Float, nullable=True)
    tech_status = Column(String(50), default="pending_review")
    coding_status = Column(String(50), default="locked")
    coding_ai_suggested_score = Column(Float, nullable=True)
    coding_human_final_score = Column(Float, nullable=True)
    behavioral_video_url = Column(String(255), nullable=True)
    behavioral_ai_suggested_score = Column(Float, nullable=True)
    behavioral_human_final_score = Column(Float, nullable=True)
    behavioral_status = Column(String(50), default="locked")
    ai_log = Column(Text, nullable=True)
    proctoring_log = Column(Text, nullable=True)
    retry_allowed = Column(Boolean, default=False)
    final_status = Column(String(50), default="in_progress")
    is_finally_approved = Column(Boolean, default=False)
    approved_by_hr_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    candidate = relationship("User", foreign_keys=[candidate_id], back_populates="assessments")
    hr_approver = relationship("User", foreign_keys=[approved_by_hr_id])
    template = relationship("AssessmentTemplate", foreign_keys=[template_id], back_populates="assessments")
    answers = relationship("AssessmentAnswer", foreign_keys="[AssessmentAnswer.assessment_id]", back_populates="assessment", cascade="all, delete-orphan")
