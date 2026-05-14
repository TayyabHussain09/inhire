from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.orm import Session, selectinload

from . import auth, database, models, schemas
from .services import ai_service, code_runner

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
UPLOADS_DIR = BASE_DIR / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def get_current_user(request: Request, db: Session = Depends(database.get_db)) -> models.User:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    token = request.cookies.get(auth.AUTH_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1]
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user


def require_hr(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role not in ("hr_senior", "hr_junior", "hr_intern"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access restricted to HR users only.")
    return current_user


def require_senior_hr(current_user: models.User = Depends(require_hr)) -> models.User:
    if current_user.role != "hr_senior":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only senior HR can modify final decisions, templates, and retries.")
    return current_user


def require_candidate(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role != "candidate":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access restricted to candidates only.")
    return current_user


def latest_assessment(db: Session, user_id: int):
    return db.query(models.Assessment).options(selectinload(models.Assessment.template).selectinload(models.AssessmentTemplate.questions), selectinload(models.Assessment.answers).selectinload(models.AssessmentAnswer.question)).filter(models.Assessment.candidate_id == user_id).order_by(models.Assessment.id.desc()).first()


def latest_dashboard_assessment(db: Session, user_id: int):
    assessment = db.query(models.Assessment).options(selectinload(models.Assessment.template).selectinload(models.AssessmentTemplate.questions), selectinload(models.Assessment.answers).selectinload(models.AssessmentAnswer.question)).filter(
        models.Assessment.candidate_id == user_id,
        models.Assessment.template_id.isnot(None),
    ).order_by(models.Assessment.id.desc()).first()
    return assessment or latest_assessment(db, user_id)


def active_templates(db: Session):
    return db.query(models.AssessmentTemplate).options(selectinload(models.AssessmentTemplate.questions)).filter(models.AssessmentTemplate.is_active == True).order_by(models.AssessmentTemplate.created_at.desc()).all()


def matching_templates(db: Session, department: str, candidate_level: str, access_code: str):
    return db.query(models.AssessmentTemplate).options(selectinload(models.AssessmentTemplate.questions)).filter(
        models.AssessmentTemplate.is_active == True,
        models.AssessmentTemplate.department == normalize_department(department),
        models.AssessmentTemplate.candidate_level == normalize_candidate_level(candidate_level),
        models.AssessmentTemplate.access_code == access_code.strip(),
    ).order_by(models.AssessmentTemplate.created_at.desc()).all()


def redirect_for_role(user: models.User):
    return "/hr" if user.role == "hr_senior" else "/candidate"


def grouped_questions(template, round_type):
    if not template:
        return []
    return sorted([q for q in template.questions if q.round_type == round_type], key=lambda q: q.sort_order or 1)


def grouped_questions_by_type(template, round_type, question_type):
    return [q for q in grouped_questions(template, round_type) if q.question_type == question_type]


def average_score(scores):
    clean_scores = [score for score in scores if score is not None]
    if not clean_scores:
        return 0
    return round(sum(clean_scores) / len(clean_scores), 1)


def build_answer_transcript(template, answers):
    lines = [f"Template: {template.name}", f"Department: {template.department}", f"Target role: {template.target_role}", f"Global instructions: {template.global_instructions}"]
    for question in grouped_questions(template, "text"):
        answer = answers.get(str(question.id), "").strip()
        lines.append(f"Question: {question.prompt}\nAnswer: {answer}")
    return "\n\n".join(lines)


def normalize_department(department: str):
    allowed_departments = {"software": "Software", "medical": "Medical"}
    key = department.strip().lower()
    if key not in allowed_departments:
        raise HTTPException(status_code=400, detail="Department must be Software or Medical.")
    return allowed_departments[key]


def normalize_candidate_level(candidate_level: str):
    allowed_levels = {
        "intern": "intern",
        "junior": "junior",
        "mid": "mid",
        "senior": "senior",
        "executive": "executive",
    }
    key = candidate_level.strip().lower()
    if key not in allowed_levels:
        raise HTTPException(status_code=400, detail="Candidate level must be Intern, Junior, Mid, Senior, or Executive.")
    return allowed_levels[key]


def parse_question_lines(raw_text: str):
    parsed = []
    for line in [q.strip() for q in raw_text.splitlines() if q.strip()]:
        parts = [part.strip() for part in line.split("||")]
        parsed.append({
            "prompt": parts[0],
            "instructions": parts[1] if len(parts) > 1 else None,
            "expected_output": parts[2] if len(parts) > 2 else None,
        })
    return parsed


def replace_audit_section(existing_log: str | None, section_prefixes: tuple[str, ...], new_lines: list[str]):
    kept_lines = []
    for line in (existing_log or "").splitlines():
        if not any(line.startswith(prefix) for prefix in section_prefixes):
            kept_lines.append(line)
    return "\n".join([line for line in kept_lines + new_lines if line])


def assessment_payload(assessment):
    if not assessment:
        return None
    return {
        "id": assessment.id,
        "template_id": assessment.template_id,
        "template_name": assessment.template.name if assessment.template else None,
        "target_role": assessment.target_role,
        "tech_transcript": assessment.tech_transcript,
        "tech_ai_suggested_score": assessment.tech_ai_suggested_score,
        "tech_human_final_score": assessment.tech_human_final_score,
        "tech_status": assessment.tech_status,
        "behavioral_video_url": assessment.behavioral_video_url,
        "behavioral_ai_suggested_score": assessment.behavioral_ai_suggested_score,
        "behavioral_human_final_score": assessment.behavioral_human_final_score,
        "behavioral_status": assessment.behavioral_status,
        "is_finally_approved": assessment.is_finally_approved,
    }


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html", context={"error": None})


@router.post("/signup-form")
def signup_form(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form("candidate"), db: Session = Depends(database.get_db)):
    if role not in ("candidate", "hr_senior", "hr_junior", "hr_intern"):
        role = "candidate"
    if db.query(models.User).filter(models.User.email == email).first():
        return templates.TemplateResponse(request=request, name="signup.html", context={"error": "Email already registered. Please log in instead."}, status_code=400)
    user = models.User(name=name, email=email, hashed_password=auth.get_password_hash(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = auth.create_access_token({"sub": user.email, "role": user.role})
    response = RedirectResponse(redirect_for_role(user), status_code=303)
    auth.attach_auth_cookie(response, token)
    return response


@router.post("/login-form")
def login_form(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Incorrect email or password"}, status_code=401)
    token = auth.create_access_token({"sub": user.email, "role": user.role})
    response = RedirectResponse(redirect_for_role(user), status_code=303)
    auth.attach_auth_cookie(response, token)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(auth.AUTH_COOKIE_NAME)
    return response


@router.get("/candidate", response_class=HTMLResponse)
def candidate_page(request: Request, current_user: models.User = Depends(require_candidate), db: Session = Depends(database.get_db)):
    assessment = latest_assessment(db, current_user.id)
    department = request.query_params.get("department", "")
    candidate_level = request.query_params.get("candidate_level", "")
    access_code = request.query_params.get("access_code", "")
    matched_templates = []
    if department and candidate_level and access_code:
        matched_templates = matching_templates(db, department, candidate_level, access_code)
    return templates.TemplateResponse(request=request, name="candidate.html", context={"user": current_user, "assessment": assessment, "templates": matched_templates, "department": department, "candidate_level": candidate_level, "access_code": access_code, "text_questions": grouped_questions_by_type(assessment.template, "text", "theory") if assessment else [], "coding_questions": grouped_questions_by_type(assessment.template, "text", "coding") if assessment else [], "video_questions": grouped_questions(assessment.template, "video") if assessment else []})


@router.post("/candidate/technical")
async def submit_technical_form(request: Request, template_id: int = Form(...), department: str = Form(...), candidate_level: str = Form(...), access_code: str = Form(...), current_user: models.User = Depends(require_candidate), db: Session = Depends(database.get_db)):
    existing = latest_assessment(db, current_user.id)
    if existing and existing.tech_status in ("passed_tech", "failed_tech"):
        return RedirectResponse("/candidate", status_code=303)
    template = db.query(models.AssessmentTemplate).options(selectinload(models.AssessmentTemplate.questions)).filter(models.AssessmentTemplate.id == template_id, models.AssessmentTemplate.is_active == True, models.AssessmentTemplate.department == normalize_department(department), models.AssessmentTemplate.candidate_level == normalize_candidate_level(candidate_level), models.AssessmentTemplate.access_code == access_code.strip()).first()
    if not template:
        raise HTTPException(status_code=404, detail="Assessment template not found.")
    form = await request.form()
    answers = {key.replace("answer_", ""): str(value) for key, value in form.items() if key.startswith("answer_")}
    theory_questions = grouped_questions_by_type(template, "text", "theory")
    coding_questions = grouped_questions_by_type(template, "text", "coding")
    assessment = existing or models.Assessment(candidate_id=current_user.id, template_id=template.id, target_role=template.target_role)
    db.add(assessment)
    db.flush()
    scores = []
    log_lines = []
    for question in theory_questions:
        answer = answers.get(str(question.id), "").strip()
        ai_result = ai_service.evaluate_question_answer(question.prompt, question.instructions or template.global_instructions, answer, template.target_role, template.department, question.question_type, question.expected_output or "")
        scores.append(ai_result.get("score", 0))
        log_lines.append(f"Q{question.id}: {ai_result.get('score', 0)} - {ai_result.get('reasoning', '')}")
        db.add(models.AssessmentAnswer(assessment_id=assessment.id, question_id=question.id, answer_text=answer, ai_score=ai_result.get("score", 0), ai_reasoning=ai_result.get("reasoning", ""), ai_raw_response=ai_result.get("raw_response", "")))
    score = average_score(scores)
    assessment.tech_transcript = build_answer_transcript(template, answers)
    assessment.tech_ai_suggested_score = score
    assessment.ai_log = "\n".join(log_lines)
    if score >= 60:
        assessment.tech_status = "passed_tech_pending_hr"
        assessment.coding_status = "unlocked" if coding_questions else "not_required"
        assessment.behavioral_status = "pending_hr_unlock"
    else:
        assessment.tech_status = "failed_tech"
        assessment.coding_status = "locked"
        assessment.behavioral_status = "locked"
        assessment.final_status = "failed_round_1"
    db.commit()
    return RedirectResponse("/candidate", status_code=303)


@router.post("/candidate/coding")
async def submit_coding_form(request: Request, current_user: models.User = Depends(require_candidate), db: Session = Depends(database.get_db)):
    assessment = latest_assessment(db, current_user.id)
    if not assessment or assessment.coding_status != "unlocked":
        raise HTTPException(status_code=403, detail="Coding round is locked.")
    form = await request.form()
    scores = []
    log_lines = [assessment.ai_log or ""]
    for question in grouped_questions_by_type(assessment.template, "text", "coding"):
        answer = str(form.get(f"answer_{question.id}", "")).strip()
        execution_result = code_runner.run_python_code(answer)
        evaluated_answer = f"{answer}\n\nExecution result:\nstdout: {execution_result['stdout']}\nstderr: {execution_result['stderr']}\nexit_code: {execution_result['exit_code']}\ntimed_out: {execution_result['timed_out']}"
        ai_result = ai_service.evaluate_question_answer(question.prompt, question.instructions or assessment.template.global_instructions, evaluated_answer, assessment.target_role, assessment.template.department, question.question_type, question.expected_output or "")
        scores.append(ai_result.get("score", 0))
        log_lines.append(f"CODING Q{question.id}: {ai_result.get('score', 0)} - {ai_result.get('reasoning', '')}\nExecution: {execution_result}")
        db.add(models.AssessmentAnswer(assessment_id=assessment.id, question_id=question.id, answer_text=evaluated_answer, ai_score=ai_result.get("score", 0), ai_reasoning=ai_result.get("reasoning", ""), ai_raw_response=ai_result.get("raw_response", "")))
    score = average_score(scores)
    assessment.coding_ai_suggested_score = score
    assessment.ai_log = "\n".join([line for line in log_lines if line])
    if score >= 60:
        assessment.coding_status = "passed_coding_pending_hr"
        assessment.behavioral_status = "pending_hr_unlock"
    else:
        assessment.coding_status = "failed_coding"
        assessment.behavioral_status = "locked"
        assessment.final_status = "failed_coding"
    db.commit()
    return RedirectResponse("/candidate", status_code=303)


@router.post("/candidate/video")
async def submit_video_form(file: UploadFile = File(...), current_user: models.User = Depends(require_candidate), db: Session = Depends(database.get_db)):
    assessment = latest_assessment(db, current_user.id)
    if not assessment or assessment.behavioral_status != "unlocked":
        raise HTTPException(status_code=403, detail="Behavioral round is not open for video upload.")
    upload = await upload_video(file, current_user, db)
    submit_behavioral_video(schemas.VideoUpload(video_url=upload["video_url"]), current_user, db)
    return RedirectResponse("/candidate", status_code=303)


@router.get("/hr", response_class=HTMLResponse)
def hr_page(request: Request, current_user: models.User = Depends(require_hr), db: Session = Depends(database.get_db)):
    templates_list = db.query(models.AssessmentTemplate).options(selectinload(models.AssessmentTemplate.questions)).order_by(models.AssessmentTemplate.created_at.desc()).all()
    return templates.TemplateResponse(request=request, name="hr.html", context={"user": current_user, "candidates": get_all_candidates(current_user, db), "templates": templates_list})


@router.post("/hr/templates")
async def create_template_form(request: Request, name: str = Form(...), department: str = Form(...), candidate_level: str = Form(...), access_code: str = Form(...), target_role: str = Form(...), global_instructions: str = Form(...), text_questions: str = Form(""), coding_questions: str = Form(""), video_questions: str = Form(""), current_user: models.User = Depends(require_senior_hr), db: Session = Depends(database.get_db)):
    form = await request.form()
    theory_rows = "\n".join([str(value).strip() for value in form.getlist("theory_row") if str(value).strip()])
    coding_rows = "\n".join([str(value).strip() for value in form.getlist("coding_row") if str(value).strip()])
    video_rows = "\n".join([str(value).strip() for value in form.getlist("video_row") if str(value).strip()])
    text_prompts = parse_question_lines(text_questions or theory_rows)
    coding_prompts = parse_question_lines(coding_questions or coding_rows)
    video_prompts = parse_question_lines(video_questions or video_rows)
    if not text_prompts or not video_prompts:
        raise HTTPException(status_code=400, detail="Add at least one Round 1 question and one Round 2 video prompt.")
    template = models.AssessmentTemplate(name=name, department=normalize_department(department), candidate_level=normalize_candidate_level(candidate_level), access_code=access_code.strip(), target_role=target_role, global_instructions=global_instructions, created_by_hr_id=current_user.id)
    db.add(template)
    db.flush()
    sort_order = 1
    for item in text_prompts:
        db.add(models.AssessmentQuestion(template_id=template.id, round_type="text", question_type="theory", prompt=item["prompt"], instructions=item["instructions"], expected_output=item["expected_output"], sort_order=sort_order))
        sort_order += 1
    for item in coding_prompts:
        db.add(models.AssessmentQuestion(template_id=template.id, round_type="text", question_type="coding", prompt=item["prompt"], instructions=item["instructions"], expected_output=item["expected_output"], sort_order=sort_order))
        sort_order += 1
    sort_order = 1
    for item in video_prompts:
        db.add(models.AssessmentQuestion(template_id=template.id, round_type="video", question_type="video", prompt=item["prompt"], instructions=item["instructions"], expected_output=item["expected_output"], sort_order=sort_order))
        sort_order += 1
    db.commit()
    return RedirectResponse("/hr", status_code=303)


@router.post("/hr/assessment/{assessment_id}/decision")
def hr_decision_form(assessment_id: int, tech_human_final_score: float | None = Form(None), coding_human_final_score: float | None = Form(None), behavioral_human_final_score: float | None = Form(None), decision: str = Form("reject"), current_user: models.User = Depends(require_senior_hr), db: Session = Depends(database.get_db)):
    update_hr_score(assessment_id, schemas.HRScoreUpdate(assessment_id=assessment_id, tech_human_final_score=tech_human_final_score, coding_human_final_score=coding_human_final_score, behavioral_human_final_score=behavioral_human_final_score), current_user, db)
    approve_or_reject_candidate(assessment_id, decision == "approve", current_user, db)
    return RedirectResponse("/hr", status_code=303)


@router.post("/hr/assessment/{assessment_id}/retry")
def hr_retry_form(assessment_id: int, allow_retry: bool = Form(False), current_user: models.User = Depends(require_senior_hr), db: Session = Depends(database.get_db)):
    assessment = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    assessment.retry_allowed = allow_retry
    if allow_retry:
        assessment.tech_status = "retry_allowed"
        assessment.coding_status = "locked"
        assessment.behavioral_status = "locked"
        assessment.final_status = "retry_allowed"
    db.commit()
    return RedirectResponse("/hr", status_code=303)


@router.post("/hr/assessment/{assessment_id}/unlock-video")
def hr_unlock_video_form(assessment_id: int, current_user: models.User = Depends(require_senior_hr), db: Session = Depends(database.get_db)):
    assessment = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    theory_score = assessment.tech_human_final_score if assessment.tech_human_final_score is not None else assessment.tech_ai_suggested_score
    coding_required = assessment.coding_status not in ("not_required", "locked")
    coding_score = assessment.coding_human_final_score if assessment.coding_human_final_score is not None else assessment.coding_ai_suggested_score
    if theory_score is None or theory_score < 60:
        raise HTTPException(status_code=400, detail="Theory score must be at least 60 before video unlock.")
    if coding_required and (coding_score is None or coding_score < 60):
        raise HTTPException(status_code=400, detail="Coding score must be at least 60 before video unlock.")
    assessment.behavioral_status = "unlocked"
    assessment.final_status = "video_unlocked_by_hr"
    db.commit()
    return RedirectResponse("/hr", status_code=303)


@router.post("/api/signup", response_model=schemas.Token)
def create_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = models.User(name=user.name, email=user.email, hashed_password=auth.get_password_hash(user.password), role=user.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    access_token = auth.create_access_token(data={"sub": new_user.email, "role": new_user.role})
    return {"access_token": access_token, "token_type": "bearer", "role": new_user.role, "name": new_user.name}


@router.post("/api/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    access_token = auth.create_access_token(data={"sub": user.email, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer", "role": user.role, "name": user.name}


@router.get("/api/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    return {"id": current_user.id, "name": current_user.name, "email": current_user.email, "role": current_user.role}


@router.post("/api/submit-technical")
def submit_technical_test(assessment_data: schemas.AssessmentSubmit, current_user: models.User = Depends(require_candidate), db: Session = Depends(database.get_db)):
    existing = latest_assessment(db, current_user.id)
    if existing and existing.tech_status in ("passed_tech", "failed_tech"):
        raise HTTPException(status_code=400, detail="You have already submitted the technical assessment.")
    template = db.query(models.AssessmentTemplate).filter(models.AssessmentTemplate.id == assessment_data.template_id).first() if assessment_data.template_id else None
    ai_result = ai_service.evaluate_candidate_transcript(assessment_data.raw_transcript, assessment_data.target_role, template.global_instructions if template else "")
    score = ai_result.get("score", 0)
    if score >= 60:
        tech_status = "passed_tech"
        behavioral_status = "unlocked"
        message = "Congratulations! You passed the technical round and have unlocked the Behavioral Video Interview."
        passed = True
    else:
        tech_status = "failed_tech"
        behavioral_status = "locked"
        message = f"Unfortunately, you scored {score}/100 and did not meet the 60% requirement for this role."
        passed = False
    assessment = existing or models.Assessment(candidate_id=current_user.id)
    assessment.template_id = assessment_data.template_id
    assessment.target_role = assessment_data.target_role
    assessment.tech_transcript = assessment_data.raw_transcript
    assessment.tech_ai_suggested_score = score
    assessment.tech_status = tech_status
    assessment.behavioral_status = behavioral_status
    if not existing:
        db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return {"message": message, "score": score, "reasoning": ai_result.get("reasoning", ""), "passed": passed, "assessment_id": assessment.id}


@router.post("/api/upload-video")
async def upload_video(file: UploadFile = File(...), current_user: models.User = Depends(require_candidate), db: Session = Depends(database.get_db)):
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video.")
    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "webm"
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = UPLOADS_DIR / filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"video_url": f"/static/uploads/{filename}", "filename": filename}


@router.post("/api/submit-behavioral")
def submit_behavioral_video(video_data: schemas.VideoUpload, current_user: models.User = Depends(require_candidate), db: Session = Depends(database.get_db)):
    assessment = latest_assessment(db, current_user.id)
    if not assessment:
        raise HTTPException(status_code=404, detail="No assessment found. Complete the technical round first.")
    if assessment.behavioral_status == "locked":
        raise HTTPException(status_code=403, detail="Behavioral round is locked. You must pass the technical round first.")
    if assessment.behavioral_status == "completed":
        raise HTTPException(status_code=400, detail="Behavioral assessment already submitted.")
    prompts = "\n".join([q.prompt for q in grouped_questions(assessment.template, "video")])
    ai_result = ai_service.evaluate_behavioral_video(video_data.video_url, assessment.target_role, prompts)
    proctoring_result = ai_service.evaluate_video_proctoring(video_data.video_url)
    score = ai_result.get("score", 70)
    assessment.behavioral_video_url = video_data.video_url
    assessment.behavioral_ai_suggested_score = score
    assessment.behavioral_status = "completed"
    assessment.proctoring_log = proctoring_result.get("reasoning", "")
    assessment.ai_log = replace_audit_section(
        assessment.ai_log,
        ("VIDEO:", "PROCTORING:"),
        [f"VIDEO: {score} - {ai_result.get('reasoning', '')}", f"PROCTORING: {proctoring_result.get('reasoning', '')}"],
    )
    db.commit()
    db.refresh(assessment)
    return {"message": "Behavioral video submitted successfully. Your application is now under HR review.", "score": score, "reasoning": ai_result.get("reasoning", ""), "assessment_id": assessment.id}


@router.get("/api/candidates")
def get_all_candidates(current_user: models.User = Depends(require_hr), db: Session = Depends(database.get_db)):
    candidates = db.query(models.User).filter(models.User.role == "candidate").all()
    dashboard_data = []
    for c in candidates:
        assessment = latest_dashboard_assessment(db, c.id)
        tech_score = None
        behavioral_score = None
        composite = None
        if assessment:
            tech_score = assessment.tech_human_final_score or assessment.tech_ai_suggested_score
            behavioral_score = assessment.behavioral_human_final_score or assessment.behavioral_ai_suggested_score
            if tech_score is not None and behavioral_score is not None:
                composite = round((tech_score * 0.4) + (behavioral_score * 0.6), 1)
            elif tech_score is not None:
                composite = tech_score
        dashboard_data.append({
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "target_role": assessment.target_role if assessment else "Not Started",
            "template_name": assessment.template.name if assessment and assessment.template else "No Template",
            "department": assessment.template.department if assessment and assessment.template else "N/A",
            "candidate_level": assessment.template.candidate_level if assessment and assessment.template else "N/A",
            "access_code": assessment.template.access_code if assessment and assessment.template else "N/A",
            "assessment_id": assessment.id if assessment else None,
            "tech_ai_score": assessment.tech_ai_suggested_score if assessment else None,
            "tech_final_score": assessment.tech_human_final_score if assessment else None,
            "tech_status": assessment.tech_status if assessment else "not_started",
            "behavioral_ai_score": assessment.behavioral_ai_suggested_score if assessment else None,
            "behavioral_final_score": assessment.behavioral_human_final_score if assessment else None,
            "behavioral_status": assessment.behavioral_status if assessment else "locked",
            "behavioral_video_url": assessment.behavioral_video_url if assessment else None,
            "coding_ai_score": assessment.coding_ai_suggested_score if assessment else None,
            "coding_final_score": assessment.coding_human_final_score if assessment else None,
            "coding_status": assessment.coding_status if assessment else "locked",
            "answers": assessment.answers if assessment else [],
            "ai_log": assessment.ai_log if assessment else "",
            "proctoring_log": assessment.proctoring_log if assessment else "",
            "retry_allowed": assessment.retry_allowed if assessment else False,
            "final_status": assessment.final_status if assessment else "not_started",
            "is_finally_approved": assessment.is_finally_approved if assessment else False,
            "composite_score": composite,
        })
    dashboard_data.sort(key=lambda x: x["composite_score"] if x["composite_score"] is not None else -1, reverse=True)
    return dashboard_data


@router.patch("/api/assessment/{assessment_id}/score")
def update_hr_score(assessment_id: int, score_data: schemas.HRScoreUpdate, current_user: models.User = Depends(require_hr), db: Session = Depends(database.get_db)):
    assessment = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    if score_data.tech_human_final_score is not None:
        assessment.tech_human_final_score = score_data.tech_human_final_score
    if score_data.coding_human_final_score is not None:
        assessment.coding_human_final_score = score_data.coding_human_final_score
    if score_data.behavioral_human_final_score is not None:
        assessment.behavioral_human_final_score = score_data.behavioral_human_final_score
    db.commit()
    db.refresh(assessment)
    return {"message": "Score updated successfully.", "assessment_id": assessment_id}


@router.patch("/api/assessment/{assessment_id}/approve")
def approve_or_reject_candidate(assessment_id: int, approve: bool, current_user: models.User = Depends(require_hr), db: Session = Depends(database.get_db)):
    assessment = db.query(models.Assessment).filter(models.Assessment.id == assessment_id).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    assessment.is_finally_approved = approve
    assessment.approved_by_hr_id = current_user.id
    db.commit()
    db.refresh(assessment)
    return {"message": f"Candidate has been {'approved' if approve else 'rejected'}.", "assessment_id": assessment_id, "is_finally_approved": approve}
