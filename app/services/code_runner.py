import subprocess
import sys
import tempfile
from pathlib import Path


def run_python_code(source_code: str, stdin_data: str = "", timeout_seconds: int = 5) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = Path(temp_dir) / "candidate_solution.py"
        script_path.write_text(source_code, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return {
                "exit_code": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "exit_code": None,
                "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
                "stderr": "Execution timed out.",
                "timed_out": True,
            }
