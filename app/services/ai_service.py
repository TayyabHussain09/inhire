import os
import json
import sys
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Initialize the Gemini client (reads GEMINI_API_KEY from env automatically)
client = genai.Client()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def _parse_json_response(raw_text: str, default_score: int = 0) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    result = json.loads(raw_text.strip())
    result["score"] = max(0, min(100, int(result.get("score", default_score))))
    result["raw_response"] = raw_text
    return result


def _safe_json_response(response_text: str, default_score: int = 0) -> dict:
    try:
        return _parse_json_response(response_text, default_score)
    except Exception:
        return {
            "score": default_score,
            "reasoning": "Gemini returned a non-JSON response. HR review required.",
            "raw_response": response_text,
        }


def test_gemini_connection():
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents="Respond with exactly the word: 'Connected'."
        )
        return response.text.strip()
    except Exception as e:
        return str(e)


def evaluate_candidate_transcript(transcript: str, target_role: str, global_instructions: str = "") -> dict:
    """
    Evaluates a candidate's technical text answer using Gemini.
    Returns {"score": int, "reasoning": str}
    """
    prompt = f"""
You are Gemini 2.5 Flash-Lite acting as an expert HR recruiter and senior {target_role} evaluator.
Review the candidate's submitted answers against the HR instructions and job-role questions.

HR Instructions: "{global_instructions or 'Use strict role-specific hiring standards.'}"

Candidate's Answer: "{transcript}"

SCORING CRITERIA for a {target_role} role:
- Technical accuracy and depth (40 points)
- Problem-solving approach and methodology (30 points)  
- Communication clarity (20 points)
- Practical real-world knowledge (10 points)

You MUST respond with ONLY a valid JSON object. Do not include markdown code blocks, backticks, or any extra text.
Respond with exactly this format:
{{
    "score": <integer between 0 and 100>,
    "reasoning": "A concise, 2-sentence explanation of the score highlighting specific strengths or weaknesses."
}}
"""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )

        return _safe_json_response(response.text, 0)

    except Exception as e:
        print(f"AI Technical Evaluation Error: {e}")
        return {"score": 0, "reasoning": "Failed to process AI evaluation. Please contact support."}


def evaluate_behavioral_video(video_url: str, target_role: str, interview_prompts: str = "") -> dict:
    """
    Evaluates a candidate's behavioral video interview using Gemini.
    Returns {"score": int, "reasoning": str}
    """
    return {
        "score": 0,
        "reasoning": "Video file was uploaded and recorded for HR review. No transcript, frame extraction, or audio analysis is available in this runtime, so Gemini cannot honestly score communication, leadership, teamwork, or behavioral quality from the file path alone.",
        "raw_response": f"manual_review_required video={video_url} prompts={interview_prompts}",
    }
def evaluate_question_answer(question: str, instructions: str, answer: str, target_role: str, department: str, question_type: str = "theory", expected_output: str = "") -> dict:
    prompt = f"""
You are Gemini 2.5 Flash-Lite evaluating one candidate answer for an auditable hiring assessment.

Department: {department}
Target role: {target_role}
Question type: {question_type}
HR instructions: {instructions or "No extra instructions provided."}
Question: {question}
Expected output or rubric: {expected_output or "Evaluate against the prompt and role requirements."}
Candidate answer/code: {answer}

Score only this answer from 0 to 100 based on the actual question, HR instructions, expected output, and role context. If the question is a simple conversational, greeting, confirmation, or screening question, do not grade it as a technical exam; evaluate whether the candidate answered naturally and appropriately. If this is code, evaluate correctness, edge cases, clarity, and whether output matches requirements. Do not invent execution results.

Return ONLY valid JSON:
{{
  "score": <integer 0-100>,
  "reasoning": "Specific explanation of what was correct, incorrect, and why this score was given."
}}
"""
    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return _safe_json_response(response.text, 0)
    except Exception as e:
        print(f"AI Question Evaluation Error: {e}")
        return {"score": 0, "reasoning": "Gemini evaluation failed. HR review required.", "raw_response": str(e)}


def evaluate_video_proctoring(video_url: str) -> dict:
    checks = []
    if sys.version_info >= (3, 14):
        checks.append("Python 3.14 detected: OpenCV/MediaPipe/Librosa wheels are not reliably available yet; use Python 3.11/3.12 for full local proctoring.")
    for module_name, label in [
        ("cv2", "OpenCV frame analysis"),
        ("mediapipe", "face mesh / eye movement tracking"),
        ("librosa", "audio feature extraction / duplicate voice heuristics"),
    ]:
        try:
            __import__(module_name)
            checks.append(f"{label}: available")
        except Exception as exc:
            checks.append(f"{label}: unavailable ({exc.__class__.__name__})")
    reasoning = "Video proctoring audit hook executed for " + video_url + ". " + " | ".join(checks)
    return {"score": None, "reasoning": reasoning, "raw_response": reasoning}
