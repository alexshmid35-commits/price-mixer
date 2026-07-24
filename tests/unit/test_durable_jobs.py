from pathlib import Path

import pandas as pd

from price_mixer.services import api_sources
from price_mixer.services.background_xlsx import ExternalBackgroundXlsxWorker
from price_mixer.services.durable_jobs import DurableJobQueue
from price_mixer.workers.durable_worker import DurableWorker

ROOT = Path(__file__).resolve().parents[2]


def test_durable_queue_persists_claim_and_completion(tmp_path):
    path = tmp_path / "jobs.db"
    queue = DurableJobQueue(path)
    queued = queue.enqueue("sample", {"value": 1}, max_attempts=2)

    claimed = DurableJobQueue(path).claim("worker-1", kinds={"sample"})
    completed = DurableJobQueue(path).complete(claimed["job_id"])

    assert claimed["job_id"] == queued["job_id"]
    assert claimed["payload"] == {"value": 1}
    assert claimed["attempts"] == 1
    assert completed["state"] == "succeeded"
    assert queue.counts() == {"succeeded": 1}


def test_durable_queue_retries_then_fails_without_storing_exception_text(tmp_path):
    queue = DurableJobQueue(tmp_path / "jobs.db")
    job_id = queue.enqueue("sample", {}, max_attempts=2)["job_id"]
    first = queue.claim("worker")
    retry = queue.fail(first["job_id"], RuntimeError("password=private"), retry_delay=0)
    second = queue.claim("worker")
    failed = queue.fail(second["job_id"], RuntimeError("token=private"), retry_delay=0)

    assert retry["state"] == "queued"
    assert failed["state"] == "failed"
    assert failed["error_type"] == "RuntimeError"
    assert "private" not in str(failed)
    assert job_id == failed["job_id"]


def test_durable_queue_cancels_older_queued_dedupe_job(tmp_path):
    queue = DurableJobQueue(tmp_path / "jobs.db")
    first = queue.enqueue("xlsx", {"snapshot_path": "first"}, dedupe_key="session")
    second = queue.enqueue("xlsx", {"snapshot_path": "second"}, dedupe_key="session")

    assert queue.get(first["job_id"])["state"] == "cancelled"
    assert second["superseded"] == [
        {
            "job_id": first["job_id"],
            "payload": {"snapshot_path": "first"},
        }
    ]
    assert queue.latest("xlsx", "session")["job_id"] == second["job_id"]


def test_durable_queue_can_reuse_active_idempotent_job(tmp_path):
    queue = DurableJobQueue(tmp_path / "jobs.db")
    first = queue.enqueue(
        "review",
        {"batch": 1},
        dedupe_key="session",
        reuse_active=True,
    )
    second = queue.enqueue(
        "review",
        {"batch": 2},
        dedupe_key="session",
        reuse_active=True,
    )

    assert second["job_id"] == first["job_id"]
    assert second["reused"] is True
    assert queue.counts() == {"queued": 1}


def test_durable_queue_cancel_resume_and_late_completion_are_safe(tmp_path):
    queue = DurableJobQueue(tmp_path / "jobs.db")
    job_id = queue.enqueue("sample", {}, max_attempts=2)["job_id"]
    queue.claim("worker")

    cancelled = queue.cancel(job_id)
    late_completion = queue.complete(job_id)
    resumed = queue.resume(job_id)
    claimed_again = queue.claim("worker-2")

    assert cancelled["state"] == "cancelled"
    assert late_completion["state"] == "cancelled"
    assert resumed["state"] == "queued"
    assert claimed_again["job_id"] == job_id
    assert claimed_again["attempts"] == 1


def test_resumed_job_rejects_completion_from_previous_worker(tmp_path):
    queue = DurableJobQueue(tmp_path / "jobs.db")
    job_id = queue.enqueue("sample", {})["job_id"]
    queue.claim("old-worker")
    queue.cancel(job_id)
    queue.resume(job_id)
    queue.claim("new-worker")

    stale = queue.complete(job_id, worker_id="old-worker")
    completed = queue.complete(job_id, worker_id="new-worker")

    assert stale["state"] == "running"
    assert completed["state"] == "succeeded"


def test_worker_heartbeat_reports_liveness_without_exposing_worker_id(tmp_path):
    now = [100.0]
    queue = DurableJobQueue(tmp_path / "jobs.db", clock=lambda: now[0])
    queue.heartbeat("host-user-private")

    healthy = queue.worker_health(max_age=30)
    now[0] = 131.0
    stale = queue.worker_health(max_age=30)

    assert healthy == {
        "status": "ok",
        "active_workers": 1,
        "latest_heartbeat_age_sec": 0.0,
    }
    assert stale == {
        "status": "unavailable",
        "active_workers": 0,
        "latest_heartbeat_age_sec": None,
    }
    assert "host-user-private" not in str(healthy)


def test_worker_delegates_scheduled_database_maintenance(tmp_path):
    calls = []
    worker = DurableWorker(
        DurableJobQueue(tmp_path / "jobs.db"),
        uploads_dir=tmp_path / "uploads",
        database_maintainer=lambda data_dir: calls.append(data_dir) or [{"status": "ok"}],
    )

    result = worker.maintain_databases()

    assert result == [{"status": "ok"}]
    assert len(calls) == 1


def test_external_xlsx_backend_is_processed_outside_flask(tmp_path):
    uploads = tmp_path / "uploads"
    session = uploads / "session"
    session.mkdir(parents=True)
    queue = DurableJobQueue(tmp_path / "data" / "jobs.db")
    backend = ExternalBackgroundXlsxWorker(queue)
    dataframe = pd.DataFrame({"Название": ["SSD"], "Цена": [10]})

    queued = backend.enqueue(session, dataframe, label="unit")
    worker = DurableWorker(queue, uploads_dir=uploads, worker_id="unit-worker")

    assert queued["state"] == "queued"
    assert worker.run_once() is True
    assert backend.status(session)["state"] == "done"
    result = pd.read_excel(session / "consolidated_price.xlsx")
    assert result.to_dict("records") == [{"Название": "SSD", "Цена": 10}]
    assert list(session.glob(".xlsx-job-*")) == []


def test_external_worker_rejects_paths_outside_uploads(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    outside = tmp_path / "outside.pkl"
    outside.write_bytes(b"not-a-pickle")
    queue = DurableJobQueue(tmp_path / "jobs.db")
    job_id = queue.enqueue(
        "xlsx",
        {
            "snapshot_path": str(outside),
            "final_path": str(tmp_path / "outside.xlsx"),
        },
        max_attempts=1,
    )["job_id"]

    DurableWorker(queue, uploads_dir=uploads).run_once()

    assert queue.get(job_id)["state"] == "failed"
    assert outside.is_file()
    assert not (tmp_path / "outside.xlsx").exists()


def test_api_source_fetch_survives_process_boundary_via_persistent_status(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("PRICE_MIXER_JOB_MODE", "external")
    monkeypatch.setattr(
        api_sources,
        "SOURCE_RUNTIME_DIR",
        tmp_path / "cache" / "source_runtime",
    )
    uploads = tmp_path / "uploads"
    queue = DurableJobQueue(tmp_path / "data" / "jobs.db")
    settings = {
        "api_sources": {
            "demo": {
                "mode": "direct_file",
                "file_url": "https://example.test/price.xlsx",
                "label": "Demo",
                "supplier": "Demo",
                "verify_ssl": True,
            }
        }
    }
    history = []

    def fake_download(**kwargs):
        kwargs["target_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["target_path"].write_bytes(b"price")

    monkeypatch.setattr(
        api_sources,
        "_download_direct_source_with_retries",
        fake_download,
    )

    def enqueue(source_key, client_key):
        runtime = api_sources.get_source_runtime(source_key, client_key)
        queue.enqueue(
            "api_source_fetch",
            {"source_key": source_key, "client_key": client_key},
            dedupe_key=f"{client_key}:{source_key}",
            job_id=runtime["job_id"],
        )

    body, status = api_sources.source_fetch_start_payload(
        {"source": "demo"},
        client_key="client-1",
        settings=settings,
        start_worker=enqueue,
    )
    worker = DurableWorker(
        queue,
        uploads_dir=uploads,
        settings_loader=lambda: settings,
        history_appender=history.append,
    )

    assert status == 200
    assert body["state"]["status"] == "starting"
    assert worker.run_once() is True
    persisted = api_sources.get_source_runtime("demo", "client-1")
    assert persisted["status"] == "ready"
    assert Path(persisted["file_path"]).read_bytes() == b"price"
    assert history[-1]["status"] == "ok"


def test_durable_worker_systemd_template_is_hardened():
    service = (ROOT / "deploy" / "price-mixer-worker.service").read_text(encoding="utf-8")

    assert "price_mixer.workers.durable_worker" in service
    assert "Restart=on-failure" in service
    assert "ReadOnlyPaths=/opt/price-mixer/current" in service
    assert "ReadWritePaths=/var/lib/price-mixer/data" in service
    assert "ReadWritePaths=/var/lib/price-mixer/uploads" in service
