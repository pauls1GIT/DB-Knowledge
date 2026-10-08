"""Run the KEDB frontend and backend in a single Databricks App.

The reverse proxy owns the public port. Streamlit and FastAPI bind to localhost.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def _terminate(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 5
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    public_port = os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", "8000"))
    if int(public_port) in {8001, 8501}:
        raise ValueError("Public port must differ from internal ports 8001 and 8501")
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", "src")
    env.setdefault("KEDB_API_URL", "http://127.0.0.1:8001")

    commands = [
        [sys.executable, "-m", "uvicorn", "kedb.presentation.api.app:app",
         "--host", "127.0.0.1", "--port", "8001"],
        [sys.executable, "-m", "streamlit", "run", "src/kedb/presentation/streamlit/app.py",
         "--server.address=127.0.0.1", "--server.port=8501",
         "--server.headless=true", "--browser.gatherUsageStats=false"],
        [sys.executable, "-m", "kedb.presentation.proxy"],
    ]
    processes = []
    try:
        for command in commands:
            processes.append(subprocess.Popen(command, env=env))
    except Exception:
        _terminate(processes)
        raise

    def handle_signal(_signum, _frame):
        _terminate(processes)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    _terminate(processes)
                    return code
            time.sleep(1)
    finally:
        _terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
