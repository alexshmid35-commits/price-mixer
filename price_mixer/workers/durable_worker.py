"""Separate durable worker process for Price Mixer background jobs."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import threading
import time
import uuid
from pathlib import Path

from price_mixer.logging_config import (
    configure_price_mixer_logging,
    get_logger,
    log_context,
)
from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.services.api_sources import (
    fetch_api_source_worker,
    get_source_runtime,
)
from price_mixer.services.durable_jobs import DurableJobQueue
from price_mixer.services.supplier_snapshots import append_api_fetch_history
from price_mixer.settings import load_app_settings
from price_mixer.workers.xlsx_writer import write_snapshot


LOGGER = get_logger("price_mixer.worker")


class DurableWorker:
    def __init__(
        self,
        queue_backend=None,
        *,
        uploads_dir=None,
        worker_id=None,
        retry_delay=5,
        settings_loader=load_app_settings,
        history_appender=append_api_fetch_history,
    ):
        self.queue = queue_backend or DurableJobQueue()
        self.uploads_dir = Path(
            uploads_dir or get_runtime_paths().uploads_dir
        ).resolve()
        self.worker_id = str(
            worker_id
            or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        self.retry_delay = max(0, float(retry_delay))
        self.settings_loader = settings_loader
        self.history_appender = history_appender

    def run_once(self):
        self.queue.heartbeat(self.worker_id)
        job = self.queue.claim(
            self.worker_id,
            kinds={"xlsx", "api_source_fetch"},
            lease_seconds=900,
        )
        if job is None:
            return False
        with log_context(job_id=job["job_id"]):
            try:
                LOGGER.info("durable job started kind=%s", job["kind"])
                if job["kind"] == "xlsx":
                    message = self._run_xlsx(job)
                elif job["kind"] == "api_source_fetch":
                    message = self._run_api_source_fetch(job)
                else:
                    raise ValueError("unsupported durable job kind")
                self.queue.complete(job["job_id"], message=message)
                if job["kind"] == "xlsx":
                    self._cleanup_xlsx_snapshot(job)
                LOGGER.info("durable job completed kind=%s", job["kind"])
            except Exception as exc:
                state = self.queue.fail(
                    job["job_id"],
                    exc,
                    retry_delay=self.retry_delay,
                )
                LOGGER.exception(
                    "durable job failed kind=%s retry=%s",
                    job["kind"],
                    bool(state and state["state"] == "queued"),
                )
            return True

    def _run_xlsx(self, job):
        payload = job.get("payload") or {}
        snapshot = self._safe_upload_path(
            payload.get("snapshot_path"),
            prefix=".xlsx-job-",
            suffix=".pkl",
        )
        final_path = self._safe_upload_path(
            payload.get("final_path"),
            exact_name="consolidated_price.xlsx",
        )
        if snapshot.parent != final_path.parent:
            raise ValueError("XLSX job paths must share one session directory")
        if not snapshot.is_file():
            raise FileNotFoundError("XLSX job snapshot is missing")
        output = final_path.parent / f".xlsx-result-{job['job_id']}.xlsx"
        try:
            write_snapshot(snapshot, output)
            if not self.queue.is_latest(job):
                return "superseded"
            os.replace(output, final_path)
            return "XLSX updated"
        finally:
            output.unlink(missing_ok=True)

    def _cleanup_xlsx_snapshot(self, job):
        payload = job.get("payload") or {}
        snapshot = self._safe_upload_path(
            payload.get("snapshot_path"),
            prefix=".xlsx-job-",
            suffix=".pkl",
        )
        snapshot.unlink(missing_ok=True)

    def _run_api_source_fetch(self, job):
        payload = job.get("payload") or {}
        source_key = str(payload.get("source_key", "") or "").strip()
        client_key = str(payload.get("client_key", "") or "").strip()
        # Runtime helpers validate both identifiers before touching disk.
        get_source_runtime(source_key, client_key)
        fetch_api_source_worker(
            source_key,
            client_key,
            upload_dir=self.uploads_dir,
            load_settings=self.settings_loader,
            append_history=self.history_appender,
        )
        final_state = get_source_runtime(source_key, client_key)
        if final_state.get("status") != "ready":
            raise RuntimeError("API source fetch reported an error")
        return "API source fetched"

    def _safe_upload_path(self, value, *, prefix=None, suffix=None, exact_name=None):
        path = Path(str(value or "")).resolve()
        if not path.is_relative_to(self.uploads_dir):
            raise ValueError("durable job path escapes uploads directory")
        if exact_name is not None and path.name != exact_name:
            raise ValueError("durable job target filename is not allowed")
        if prefix is not None and not path.name.startswith(prefix):
            raise ValueError("durable job input filename is not allowed")
        if suffix is not None and path.suffix != suffix:
            raise ValueError("durable job input suffix is not allowed")
        return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Price Mixer durable worker")
    parser.add_argument(
        "--job-db",
        default=os.getenv("PRICE_MIXER_JOB_DB", ""),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args(argv)
    configure_price_mixer_logging()
    queue_path = str(args.job_db or "").strip() or None
    worker = DurableWorker(
        DurableJobQueue(queue_path) if queue_path else None
    )
    if args.once:
        return 0 if worker.run_once() else 3

    stopped = threading.Event()

    def _stop(_signum, _frame):
        stopped.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    LOGGER.info("durable worker started")
    last_prune = 0.0
    while not stopped.is_set():
        now = time.monotonic()
        if now - last_prune >= 3600:
            worker.queue.prune_completed()
            last_prune = now
        if not worker.run_once():
            stopped.wait(max(0.05, float(args.poll_interval)))
    LOGGER.info("durable worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
