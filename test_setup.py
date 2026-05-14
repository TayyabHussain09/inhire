import os
from dotenv import load_dotenv
from sqlalchemy import text
from app.database import engine
from app.services.ai_service import test_gemini_connection
from app.main import app

load_dotenv()

def run_diagnostics():
    print("--- Running inHire Diagnostics ---")
    
    # 1. Test Neon DB Connection
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT version();"))
            db_version = result.scalar()
            print(f"✅ NEON DATABASE: Connected Successfully! \n   Version: {db_version}")
    except Exception as e:
        print(f"❌ NEON DATABASE: Connection Failed.\n   Error: {e}")

    # 2. Test Gemini API
    print("\nTesting Gemini API...")
    gemini_result = test_gemini_connection()
    if "Connected" in gemini_result:
         print(f"✅ GEMINI API: Connected Successfully! Response: '{gemini_result}'")
    else:
         print(f"❌ GEMINI API: Failed.\n   Error: {gemini_result}")

    print("\nTesting FastAPI route import...")
    print(f"✅ FASTAPI APP: Loaded '{app.title}' with {len(app.routes)} routes.")

    print("\nTesting proctoring dependencies...")
    for module_name, label in [("cv2", "OpenCV"), ("mediapipe", "MediaPipe"), ("librosa", "Librosa")]:
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", "installed")
            print(f"✅ {label}: Available ({version})")
        except Exception as e:
            print(f"❌ {label}: Missing or failed to import.\n   Error: {e}")

if __name__ == "__main__":
    run_diagnostics()