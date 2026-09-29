"""Run the NammaSafe AI frontend, backend, and local database without Docker.

Usage:
    python run_all.py
    python run_all.py --stop
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PROJECT_ROOT / "nammasafe-ai" / "backend"
VENV_ROOT = BACKEND_ROOT / ".venv"
VENV_PYTHON = VENV_ROOT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
VITE_ENTRY = PROJECT_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
RUNTIME_ROOT = PROJECT_ROOT / ".nammasafe-runtime"
PID_FILE = RUNTIME_ROOT / "processes.json"


def run_command(command: list[str], cwd: Path) -> int:
    return subprocess.run(command, cwd=cwd, check=False).returncode


def stop_process(process_id: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process_id), "/T", "/F"], check=False)
        return
    try:
        os.kill(process_id, 15)
    except ProcessLookupError:
        pass


def stop_stack() -> int:
    if not PID_FILE.exists():
        print("NammaSafe AI is not running from this launcher.")
        return 0
    for process_id in json.loads(PID_FILE.read_text(encoding="utf-8")).values():
        stop_process(process_id)
    PID_FILE.unlink(missing_ok=True)
    print("NammaSafe AI stopped.")
    return 0


def ensure_backend_environment() -> bool:
    if VENV_PYTHON.exists():
        return True
    print("Creating the backend Python environment...")
    if run_command([sys.executable, "-m", "venv", str(VENV_ROOT)], BACKEND_ROOT) != 0:
        return False
    print("Installing backend dependencies...")
    return run_command([str(VENV_PYTHON), "-m", "pip", "install", "-r", "requirements.txt"], BACKEND_ROOT) == 0


def start_process(command: list[str], cwd: Path, log_file: Path) -> subprocess.Popen[bytes]:
    log_handle = log_file.open("ab")
    options: dict[str, object] = {"cwd": cwd, "stdout": log_handle, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(command, **options)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start or stop NammaSafe AI without Docker.")
    parser.add_argument("--stop", action="store_true", help="Stop frontend and backend started by this script.")
    arguments = parser.parse_args()

    if arguments.stop:
        return stop_stack()
    if not BACKEND_ROOT.exists() or not VITE_ENTRY.exists():
        print("Project dependencies are missing. Run npm install from the project folder first.", file=sys.stderr)
        return 1
    if PID_FILE.exists():
        print("NammaSafe AI is already running. Use python run_all.py --stop before starting again.")
        return 1
    if not ensure_backend_environment():
        return 1

    RUNTIME_ROOT.mkdir(exist_ok=True)
    backend_process = start_process(
        [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        BACKEND_ROOT,
        RUNTIME_ROOT / "backend.log",
    )
    frontend_process = start_process(
        ["node", str(VITE_ENTRY), "--host", "127.0.0.1", "--port", "3000"],
        PROJECT_ROOT,
        RUNTIME_ROOT / "frontend.log",
    )
    time.sleep(2)
    if backend_process.poll() is not None or frontend_process.poll() is not None:
        stop_process(backend_process.pid)
        stop_process(frontend_process.pid)
        print("Startup failed. Check .nammasafe-runtime/backend.log and frontend.log.", file=sys.stderr)
        return 1

    PID_FILE.write_text(json.dumps({"backend": backend_process.pid, "frontend": frontend_process.pid}), encoding="utf-8")
    print("NammaSafe AI is running without Docker.")
    print("Frontend: http://localhost:3000")
    print("Backend API: http://localhost:8000")
    print("API docs: http://localhost:8000/docs")
    print("Database: nammasafe-ai/backend/nammasafe.db (SQLite)")
    print("Stop everything: python run_all.py --stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
