"""Coalesced XLSX generation in an isolated worker process."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from price_mixer.logging_config import get_logger, log_context
from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.services.consolidated_io import clear_consolidated_df_cache
from price_mixer.services.durable_jobs import DurableJobQueue


LOGGER = get_logger("price_mixer.jobs.xlsx")


@dataclass(frozen=True)
class XlsxJob:
    session_dir: Path
    snapshot_path: Path
    generation: int
    label: str
    job_id: str


class BackgroundXlsxWorker:
    """Serialize small job snapshots quickly and write XLSX outside Flask."""

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        process_runner: Callable = subprocess.run,
        process_timeout: float = 600,
        max_attempts: int = 2,
    ):
        self.python_executable = python_executable or sys.executable
        self.process_runner = process_runner
        self.process_timeout = max(float(process_timeout), 1.0)
        self.max_attempts = max(int(max_attempts), 1)
        self._lock = threading.RLock()
        self._queue: queue.Queue[XlsxJob] = queue.Queue()
        self._generations: dict[str, int] = {}
        self._statuses: dict[str, dict] = {}
        self._thread: threading.Thread | None = None
        self._project_dir = Path(__file__).resolve().parents[2]

    def enqueue(self, session_dir, df, *, label: str = "consolidated") -> dict:
        session_path = Path(session_dir).resolve()
        session_path.mkdir(parents=True, exist_ok=True)
        key = str(session_path)
        now = time.time()
        with self._lock:
            generation = self._generations.get(key, 0) + 1
            self._generations[key] = generation

        token = uuid.uuid4().hex
        snapshot_path = session_path / f".xlsx-job-{generation}-{token}.pkl"
        try:
            df.to_pickle(snapshot_path)
        except Exception as exc:
            snapshot_path.unlink(missing_ok=True)
            with self._lock:
                if self._generations.get(key) == generation:
                    self._statuses[key] = self._status_payload(
                        state="error",
                        generation=generation,
                        label=label,
                        attempts=0,
                        message=f"Не удалось подготовить XLSX-задание: {exc}",
                        updated_at=now,
                    )
            raise

        job = XlsxJob(
            session_path,
            snapshot_path,
            generation,
            str(label or "consolidated"),
            token,
        )
        with self._lock:
            self._statuses[key] = self._status_payload(
                state="queued",
                generation=generation,
                label=job.label,
                job_id=job.job_id,
                attempts=0,
                message="XLSX поставлен в очередь.",
                updated_at=now,
            )
            self._ensure_thread_locked()
        self._queue.put(job)
        return self.status(session_path)

    def status(self, session_dir=None) -> dict:
        with self._lock:
            if session_dir is None:
                return {
                    "state": "idle" if not self._statuses else "ready",
                    "pending": self._queue.qsize(),
                    "sessions": {key: dict(value) for key, value in self._statuses.items()},
                }
            key = str(Path(session_dir).resolve())
            payload = dict(self._statuses.get(key) or self._status_payload())
            payload["pending"] = self._queue.qsize()
            return payload

    def wait_until_idle(self, timeout: float = 10) -> bool:
        deadline = time.monotonic() + max(float(timeout), 0.0)
        while time.monotonic() <= deadline:
            with self._lock:
                running = any(item.get("state") in {"queued", "running"} for item in self._statuses.values())
            if self._queue.unfinished_tasks == 0 and not running:
                return True
            time.sleep(0.01)
        return False

    def _ensure_thread_locked(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="price-mixer-xlsx-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self):
        while True:
            job = self._queue.get()
            with log_context(job_id=job.job_id):
                try:
                    LOGGER.info(
                        "XLSX job started generation=%s label=%s",
                        job.generation,
                        job.label,
                    )
                    self._run_job(job)
                except Exception as exc:
                    LOGGER.exception("XLSX dispatcher failed")
                    self._set_error_if_current(job, f"XLSX worker error: {exc}")
                finally:
                    job.snapshot_path.unlink(missing_ok=True)
                    self._queue.task_done()

    def _run_job(self, job: XlsxJob):
        if not self._is_current(job):
            return

        output_path = job.session_dir / f".xlsx-result-{job.generation}-{uuid.uuid4().hex}.xlsx"
        command = [
            self.python_executable,
            "-m",
            "price_mixer.workers.xlsx_writer",
            "--input",
            str(job.snapshot_path),
            "--output",
            str(output_path),
        ]
        last_error = ""
        try:
            for attempt in range(1, self.max_attempts + 1):
                if not self._is_current(job):
                    return
                self._set_status(
                    job,
                    state="running",
                    attempts=attempt,
                    message=f"Формирование XLSX, попытка {attempt}.",
                )
                try:
                    process_options = {
                        "cwd": str(self._project_dir),
                        "stdin": subprocess.DEVNULL,
                        "capture_output": True,
                        "text": True,
                        "timeout": self.process_timeout,
                        "check": False,
                    }
                    if os.name == "nt":
                        process_options["creationflags"] = subprocess.CREATE_NO_WINDOW
                    result = self.process_runner(command, **process_options)
                    if result.returncode == 0 and output_path.is_file():
                        if not self._is_current(job):
                            return
                        os.replace(output_path, job.session_dir / "consolidated_price.xlsx")
                        clear_consolidated_df_cache()
                        self._set_status(
                            job,
                            state="done",
                            attempts=attempt,
                            message="XLSX обновлён.",
                            finished_at=time.time(),
                        )
                        LOGGER.info(
                            "XLSX job completed generation=%s attempts=%s",
                            job.generation,
                            attempt,
                        )
                        return
                    stderr = str(getattr(result, "stderr", "") or "").strip()
                    stdout = str(getattr(result, "stdout", "") or "").strip()
                    last_error = stderr or stdout or f"worker exited with code {result.returncode}"
                except subprocess.TimeoutExpired:
                    last_error = f"worker timeout after {self.process_timeout:g}s"
                except Exception as exc:
                    last_error = str(exc)
                LOGGER.warning(
                    "XLSX job attempt failed generation=%s attempt=%s reason=%s",
                    job.generation,
                    attempt,
                    last_error[-240:],
                )
            self._set_error_if_current(job, f"Не удалось обновить XLSX: {last_error[-500:]}")
        finally:
            output_path.unlink(missing_ok=True)

    def _is_current(self, job: XlsxJob) -> bool:
        with self._lock:
            return self._generations.get(str(job.session_dir)) == job.generation

    def _set_status(self, job: XlsxJob, *, state: str, attempts: int, message: str, finished_at=0):
        key = str(job.session_dir)
        with self._lock:
            if self._generations.get(key) != job.generation:
                return
            self._statuses[key] = self._status_payload(
                state=state,
                generation=job.generation,
                label=job.label,
                job_id=job.job_id,
                attempts=attempts,
                message=message,
                updated_at=time.time(),
                finished_at=finished_at,
            )

    def _set_error_if_current(self, job: XlsxJob, message: str):
        current = self.status(job.session_dir)
        self._set_status(
            job,
            state="error",
            attempts=int(current.get("attempts", 0) or 0),
            message=message,
            finished_at=time.time(),
        )

    @staticmethod
    def _status_payload(
        *,
        state="idle",
        generation=0,
        label="",
        job_id="",
        attempts=0,
        message="",
        updated_at=0,
        finished_at=0,
    ) -> dict:
        return {
            "state": state,
            "running": state in {"queued", "running"},
            "generation": int(generation),
            "label": str(label),
            "job_id": str(job_id),
            "attempts": int(attempts),
            "message": str(message),
            "updated_at": float(updated_at),
            "finished_at": float(finished_at),
        }


class ExternalBackgroundXlsxWorker:
    """Queue XLSX generation for the separate durable worker service."""

    def __init__(self, queue_backend=None):
        self.queue = queue_backend or DurableJobQueue()

    def enqueue(self, session_dir, df, *, label="consolidated"):
        session_path = Path(session_dir).resolve()
        session_path.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        generation = time.time_ns()
        snapshot_path = session_path / f".xlsx-job-{generation}-{job_id}.pkl"
        try:
            df.to_pickle(snapshot_path)
            queued = self.queue.enqueue(
                "xlsx",
                {
                    "session_dir": str(session_path),
                    "snapshot_path": str(snapshot_path),
                    "final_path": str(session_path / "consolidated_price.xlsx"),
                    "label": str(label or "consolidated"),
                    "generation": generation,
                },
                dedupe_key=_session_dedupe_key(session_path),
                max_attempts=2,
                job_id=job_id,
            )
        except Exception:
            snapshot_path.unlink(missing_ok=True)
            raise
        for superseded in queued["superseded"]:
            _remove_superseded_snapshot(
                superseded.get("payload") or {},
                session_path,
            )
        return self.status(session_path)

    def status(self, session_dir=None):
        if session_dir is None:
            counts = self.queue.counts()
            return {
                "state": "ready",
                "pending": counts.get("queued", 0),
                "running": counts.get("running", 0),
                "counts": counts,
            }
        session_path = Path(session_dir).resolve()
        job = self.queue.latest("xlsx", _session_dedupe_key(session_path))
        if job is None:
            return BackgroundXlsxWorker._status_payload()
        state = {
            "succeeded": "done",
            "failed": "error",
            "cancelled": "cancelled",
        }.get(job["state"], job["state"])
        payload = job.get("payload") or {}
        result = BackgroundXlsxWorker._status_payload(
            state=state,
            generation=payload.get("generation", 0),
            label=payload.get("label", ""),
            job_id=job["job_id"],
            attempts=job.get("attempts", 0),
            message=job.get("message", ""),
            updated_at=job.get("updated_at", 0),
            finished_at=job.get("finished_at", 0),
        )
        result["pending"] = self.queue.counts().get("queued", 0)
        return result

    def wait_until_idle(self, timeout=10):
        deadline = time.monotonic() + max(float(timeout), 0)
        while time.monotonic() <= deadline:
            counts = self.queue.counts()
            if not counts.get("queued", 0) and not counts.get("running", 0):
                return True
            time.sleep(0.02)
        return False


def create_background_xlsx_worker(environ=None):
    env = os.environ if environ is None else environ
    mode = str(env.get("PRICE_MIXER_JOB_MODE", "inline") or "inline").lower()
    if mode == "external":
        job_db = str(env.get("PRICE_MIXER_JOB_DB", "") or "").strip()
        return ExternalBackgroundXlsxWorker(
            DurableJobQueue(job_db or get_runtime_paths().data_file("jobs.db"))
        )
    return BackgroundXlsxWorker()


def _session_dedupe_key(session_path):
    import hashlib

    return hashlib.sha256(str(Path(session_path).resolve()).encode("utf-8")).hexdigest()


def _remove_superseded_snapshot(payload, session_path):
    candidate = Path(str(payload.get("snapshot_path", "") or ""))
    try:
        resolved = candidate.resolve()
    except OSError:
        return
    if (
        resolved.parent == session_path
        and resolved.name.startswith(".xlsx-job-")
        and resolved.suffix == ".pkl"
    ):
        resolved.unlink(missing_ok=True)
