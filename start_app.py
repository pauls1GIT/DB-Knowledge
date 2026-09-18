"""Run the KEDB frontend and backend in a single Databricks App.

Streamlit owns the public Databricks Apps port. FastAPI is bound to localhost
only and is called by Streamlit at http://127.0.0.1:8001.
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


def main() -> int:
    public_port = os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", "8000"))
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", "src")
    env.setdefault("KEDB_API_URL", "http://127.0.0.1:8001")

    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "kedb.presentation.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
        env=env,
    )

    ui = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/kedb/presentation/streamlit/app.py",
            "--server.address=0.0.0.0",
            f"--server.port={public_port}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ],
        env=env,
    )

    processes = [api, ui]

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
