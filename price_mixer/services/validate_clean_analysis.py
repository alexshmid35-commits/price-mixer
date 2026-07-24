"""Run the network phase of validate-clean in an isolated process."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from price_mixer.services.id_validation import ValidationCancelledError
from price_mixer.state_store import load_dict, save_json_atomic


STATUS_FILENAME = ".validate-clean-analysis-status.json"
LOG_FILENAME = "validate_clean_analysis_worker.log"


class ValidateCleanAnalysisRunner:
    def __init__(self, *, python_executable=None, popen_factory: Callable = subprocess.Popen, poll_interval=0.2):
        self.python_executable = python_executable or sys.executable
        self.popen_factory = popen_factory
        self.poll_interval = max(float(poll_interval), 0.01)
        self.project_dir = Path(__file__).resolve().parents[2]
        self._lock = threading.RLock()
        self._active_processes = {}
        self._cancel_requested = set()

    @staticmethod
    def _session_key(session_dir):
        return str(Path(session_dir).resolve())

    def reset_cancel(self, session_dir):
        key = self._session_key(session_dir)
        with self._lock:
            self._cancel_requested.discard(key)

    def cancel(self, session_dir):
        key = self._session_key(session_dir)
        with self._lock:
            self._cancel_requested.add(key)
            process = self._active_processes.get(key)
        if process is not None:
            self._stop_process(process)
            return True
        return False

    def _is_cancel_requested(self, key):
        with self._lock:
            return key in self._cancel_requested

    @staticmethod
    def _stop_process(process):
        try:
            if process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        except (OSError, ProcessLookupError):
            pass

    def run(self, session_dir, payload, *, progress_update=None) -> dict:
        session_path = Path(session_dir).resolve()
        session_key = self._session_key(session_path)
        job_id = uuid.uuid4().hex
        input_path = session_path / f".validate-clean-{job_id}.input.json"
        result_path = session_path / f".validate-clean-{job_id}.result.json"
        status_path = session_path / STATUS_FILENAME
        request_payload = dict(payload or {})
        request_payload["job_id"] = job_id
        save_json_atomic(input_path, request_payload)
        initial = {
            "job_id": job_id,
            "running": True,
            "state": "starting",
            "total": len(request_payload.get("tasks", []) or []),
            "done": 0,
            "confirmed": 0,
            "cleared": 0,
            "skipped_api": 0,
            "errors": 0,
            "message": "Запускаю отдельный процесс проверки API...",
            "updated_at": time.time(),
        }
        save_json_atomic(status_path, initial)
        command = [
            self.python_executable,
            "-m",
            "price_mixer.workers.validate_clean_analysis",
            "--input",
            str(input_path),
            "--result",
            str(result_path),
            "--status",
            str(status_path),
            "--job-id",
            job_id,
        ]
        options = {"cwd": str(self.project_dir), "stdin": subprocess.DEVNULL}
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
            with self._lock:
                self._active_processes[session_key] = process
                cancel_now = session_key in self._cancel_requested
            if cancel_now:
                self._stop_process(process)
            while process.poll() is None:
                self._publish_status(status_path, job_id, progress_update)
                time.sleep(self.poll_interval)
            self._publish_status(status_path, job_id, progress_update)
            if self._is_cancel_requested(session_key):
                raise ValidationCancelledError("validation cancelled")
            if int(process.returncode or 0) != 0:
                status = load_dict(status_path)
                raise RuntimeError(status.get("message") or f"analysis worker exited with code {process.returncode}")
            result = load_dict(result_path)
            if str(result.get("job_id", "")) != job_id:
                raise RuntimeError("analysis worker did not produce a valid result")
            return result
        finally:
            with self._lock:
                active = self._active_processes.get(session_key)
                if active is locals().get("process"):
                    self._active_processes.pop(session_key, None)
                self._cancel_requested.discard(session_key)
            input_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)

    @staticmethod
    def _publish_status(status_path, job_id, progress_update):
        if not callable(progress_update):
            return
        status = load_dict(status_path)
        if str(status.get("job_id", "")) != job_id:
            return
        progress_update({
            key: status[key]
            for key in (
                "running",
                "total",
                "done",
                "confirmed",
                "cleared",
                "skipped_api",
                "errors",
                "message",
            )
            if key in status
        })
