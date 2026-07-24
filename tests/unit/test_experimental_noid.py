from contextlib import contextmanager
import sqlite3

import pandas as pd

from price_mixer.services.experimental_noid import ExperimentalNoIdRuntime, classify_candidates


def test_classify_candidates_keeps_close_high_scores_ambiguous():
    candidates = [
        {"id": "1", "score": 0.995, "reason": "article_like"},
        {"id": "2", "score": 0.99, "reason": "article_like"},
    ]

    assert classify_candidates(candidates) == ("ambiguous", 0.995, 0.005)


def test_classify_candidates_marks_only_reliable_reason_strong():
    strong = [{"id": "1", "score": 0.996, "reason": "motherboard_model"}]
    fuzzy = [{"id": "1", "score": 1.0, "reason": "brand_model_tokens"}]

    assert classify_candidates(strong)[0] == "strong"
    assert classify_candidates(fuzzy)[0] == "possible"


def _runtime(tmp_path):
    db_path = tmp_path / "catalog.db"

    @contextmanager
    def connection():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    frame = pd.DataFrame([
        {"OnlinerID": "", "Название": "Камера Exact A1", "Поставщик": "IVEN", "Категория": "IP-камеры"},
        {"OnlinerID": "", "Название": "Плата MSI B650M", "Поставщик": "Tradex", "Категория": "Материнская плата"},
        {"OnlinerID": "777", "Название": "Товар с ID", "Поставщик": "N-Tech", "Категория": "SSD"},
    ], index=[10, 20, 30])
    confirmations = []

    def exact(name):
        if name == "Камера Exact A1":
            return {"id": "101", "name": name, "url": "u1", "score": 1.0}
        return None

    def candidates(name, **_kwargs):
        if name == "Плата MSI B650M":
            return [{
                "id": "202",
                "name": "Материнская плата MSI B650M",
                "url": "u2",
                "score": 0.996,
                "reason": "motherboard_model",
                "source": "local_db",
            }]
        return []

    def confirm(_session_dir, payload):
        confirmations.append(payload)
        return {"status": "ok", "updated": 1}

    runtime = ExperimentalNoIdRuntime(
        db_connection=connection,
        read_dataframe=lambda _session_dir: frame.copy(),
        normalize_onliner_id=lambda value: str(value or "").strip(),
        normalize_name_key=lambda value: str(value or "").strip().casefold(),
        find_exact=exact,
        find_top_candidates=candidates,
        confirm_batch=confirm,
        start_thread=lambda target: target(),
        max_workers=2,
    )
    return runtime, confirmations


def test_runtime_builds_persistent_review_and_confirms_manually(tmp_path):
    runtime, confirmations = _runtime(tmp_path)
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()

    body, status_code = runtime.start(session_dir)

    assert status_code == 202
    job_id = body["job_id"]
    status = runtime.status(session_dir, job_id)["job"]
    assert status["status"] == "completed"
    assert status["total"] == 2
    assert status["tier_counts"] == {"exact": 1, "strong": 1}

    report = runtime.items(session_dir, {"job_id": job_id, "page": 1, "limit": 40})
    assert report["total"] == 2
    exact_item = next(item for item in report["items"] if item["confidence_tier"] == "exact")

    decision = runtime.decide(session_dir, {
        "job_id": job_id,
        "item_key": exact_item["item_key"],
        "action": "confirm",
        "candidate_id": "101",
    })

    assert decision == {"ok": True, "status": "confirmed", "selected_id": "101"}
    assert confirmations[0]["items"][0]["supplier"] == "IVEN"
    assert confirmations[0]["items"][0]["row_idx"] == "10"
    status = runtime.status(session_dir, job_id)["job"]
    assert status["decision_counts"]["confirmed"] == 1


def test_rejected_candidate_is_remembered_for_next_job(tmp_path):
    runtime, _confirmations = _runtime(tmp_path)
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()
    first, _ = runtime.start(session_dir)
    first_report = runtime.items(session_dir, {"job_id": first["job_id"]})
    strong_item = next(item for item in first_report["items"] if item["confidence_tier"] == "strong")

    rejected = runtime.decide(session_dir, {
        "job_id": first["job_id"],
        "item_key": strong_item["item_key"],
        "action": "reject_candidate",
        "candidate_id": "202",
    })

    assert rejected["status"] == "rejected"
    second, _ = runtime.start(session_dir)
    second_report = runtime.items(session_dir, {"job_id": second["job_id"]})
    remembered = next(item for item in second_report["items"] if item["product_name"] == "Плата MSI B650M")
    assert remembered["confidence_tier"] == "none"
    assert remembered["candidates"][0]["rejected"] is True

