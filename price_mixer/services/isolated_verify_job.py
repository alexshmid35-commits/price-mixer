"""Process launcher and durable state for bulk OnlinerID verification."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

from price_mixer.services.consolidated_io import has_consolidated_data
from price_mixer.state_store import load_dict, save_json_atomic


STATUS_FILENAME = ".verify-all-ids-status.json"
LOG_FILENAME = "verify_all_ids_worker.log"


def verify_status_path(session_dir) -> Path:
    return Path(session_dir).resolve() / STATUS_FILENAME


def process_is_running(pid: int) -> bool:
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        process_handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process_handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(process_handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(process_handle)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class DurableVerifyStatusWriter:
    """Throttle progress writes while always persisting terminal state."""

    def __init__(self, status_path, job_id, *, pid=None, min_interval=0.25, clock=time.monotonic):
        self.status_path = Path(status_path)
        self.job_id = str(job_id)
        self.pid = int(pid or os.getpid())
        self.min_interval = max(float(min_interval), 0.0)
        self.clock = clock
        self._last_write = 0.0

    def __call__(self, payload, *, force=False) -> bool:
        payload = dict(payload or {})
        now = self.clock()
        running = bool(payload.get("running"))
        total = int(payload.get("total", 0) or 0)
        done = int(payload.get("done", 0) or 0)
        force = bool(force or not running or done == 0 or (total > 0 and done >= total))
        if not force and now - self._last_write < self.min_interval:
            return False

        current = load_dict(self.status_path)
        if str(current.get("job_id", "")) != self.job_id:
            return False
        payload.update({
            "job_id": self.job_id,
            "pid": self.pid,
            "state": str(payload.get("state") or ("running" if running else "done")),
            "updated_at": time.time(),
        })
        save_json_atomic(self.status_path, payload)
        self._last_write = now
        return True


class IsolatedVerifyJob:
    def __init__(
        self,
        *,
        python_executable: str | None = None,
        popen_factory: Callable = subprocess.Popen,
        process_checker: Callable[[int], bool] = process_is_running,
        startup_grace_sec: float = 30,
    ):
        self.python_executable = python_executable or sys.executable
        self.popen_factory = popen_factory
        self.process_checker = process_checker
        self.startup_grace_sec = max(float(startup_grace_sec), 1.0)
        self.project_dir = Path(__file__).resolve().parents[2]

    def start(self, session_dir, initial_state) -> dict | tuple[dict, int]:
        if not session_dir:
            return {"status": "error", "message": "Нет активной сессии"}, 400
        session_path = Path(session_dir).resolve()
        if not has_consolidated_data(session_path):
            return {"status": "error", "message": "Нет данных"}, 400

        current = self.status(session_path)
        if current.get("running"):
            return {"status": "already_running"}

        job_id = uuid.uuid4().hex
        status_path = verify_status_path(session_path)
        state = dict(initial_state or {})
        state.update({
            "running": True,
            "state": "starting",
            "job_id": job_id,
            "pid": 0,
            "updated_at": time.time(),
        })
        save_json_atomic(status_path, state)
        command = [
            self.python_executable,
            "-m",
            "price_mixer.workers.verify_ids",
            "--session-dir",
            str(session_path),
            "--status-file",
            str(status_path),
            "--job-id",
            job_id,
        ]
        options = {
            "cwd": str(self.project_dir),
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        try:
            with (session_path / LOG_FILENAME).open("a", encoding="utf-8") as log_file:
                process = self.popen_factory(
                    command,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    **options,
                )
        except Exception as exc:
            state.update({
                "running": False,
                "state": "error",
                "finished_at": int(time.time()),
                "message": f"Не удалось запустить worker проверки ID: {exc}",
                "updated_at": time.time(),
            })
            save_json_atomic(status_path, state)
            return {"status": "error", "message": state["message"]}, 500

        latest = load_dict(status_path)
        if str(latest.get("job_id", "")) == job_id:
            latest.update({"pid": int(process.pid), "state": "running", "updated_at": time.time()})
            save_json_atomic(status_path, latest)
        return {"status": "started"}

    def status(self, session_dir, fallback=None) -> dict:
        if not session_dir:
            return dict(fallback or {"running": False, "state": "idle", "items": [], "report_items": []})
        status_path = verify_status_path(session_dir)
        payload = load_dict(status_path) or dict(fallback or {})
        if not payload:
            return {"running": False, "state": "idle", "items": [], "report_items": []}
        payload["items"] = list(payload.get("items", []) or [])
        payload["report_items"] = list(payload.get("report_items", []) or [])
        if payload.get("running"):
            pid = int(payload.get("pid", 0) or 0)
            started_at = float(payload.get("started_at", 0) or 0)
            missing_pid_is_stale = not pid and started_at and time.time() - started_at > self.startup_grace_sec
            if (pid and not self.process_checker(pid)) or missing_pid_is_stale:
                payload.update({
                    "running": False,
                    "state": "error",
                    "finished_at": int(time.time()),
                    "updated_at": time.time(),
                    "message": "Worker проверки ID завершился аварийно. Запустите проверку ещё раз.",
                })
                save_json_atomic(status_path, payload)
        return payload
