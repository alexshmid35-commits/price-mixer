from contextlib import contextmanager
import sqlite3

import pandas as pd

from price_mixer.services.experimental_noid import (
    ExperimentalNoIdRuntime,
    classify_candidates,
    is_separate_pevm_row,
)


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


def _runtime(tmp_path, frame=None, exclude_row=None):
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

    if frame is None:
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
        exclude_row=exclude_row,
        start_thread=lambda target: target(),
        max_workers=2,
    )
    return runtime, confirmations


def test_runtime_excludes_only_pevm_handled_by_separate_supplier_modules(tmp_path):
    frame = pd.DataFrame([
        {
            "OnlinerID": "",
            "Название": "ПЭВМ TGPC Action 5 81872 A-X Ryzen 5",
            "Поставщик": "N-Tech",
            "Категория": "Компьютеры",
        },
        {
            "OnlinerID": "",
            "Название": "Компьютер IVEN BY Gaming Black 180557 Ryzen 5",
            "Поставщик": "IVEN",
            "Категория": "Компьютеры",
        },
        {
            "OnlinerID": "",
            "Название": "Кабель питания для ПЭВМ IVEN 1.8 м",
            "Поставщик": "IVEN",
            "Категория": "Кабели",
        },
        {
            "OnlinerID": "",
            "Название": "Компьютер Acer Veriton",
            "Поставщик": "Tradex",
            "Категория": "Компьютеры",
        },
    ])

    def exclude(row):
        return is_separate_pevm_row(
            row,
            canonical_supplier_name=lambda value: str(value or "").strip(),
            is_ntech_pevm_name=lambda name: "tgpc" in name.casefold(),
            is_iven_pevm_name=lambda name: "компьютер iven" in name.casefold(),
        )

    runtime, _confirmations = _runtime(tmp_path, frame=frame, exclude_row=exclude)
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()
    body, status_code = runtime.start(session_dir)

    assert status_code == 202
    job = runtime.status(session_dir, body["job_id"])["job"]
    assert job["total"] == 2
    assert "ПЭВМ исключено: 2" in job["message"]
    report = runtime.items(session_dir, {"job_id": body["job_id"]})
    assert {item["product_name"] for item in report["items"]} == {
        "Кабель питания для ПЭВМ IVEN 1.8 м",
        "Компьютер Acer Veriton",
    }


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
    quality = runtime.quality(session_dir, job_id)
    assert quality["overall"]["decisions"] == {"confirm": 1}
    assert quality["overall"]["candidate_acceptance_rate"] == 1.0
    assert quality["overall"]["precision"] == 1.0
    assert quality["overall"]["false_positive_rate"] == 0.0
    assert quality["overall"]["auto_confirm_rate"] == 0.0
    assert any(
        item["category"] == "IP-камеры"
        and item["decisions"] == {"confirm": 1}
        and item["precision"] == 1.0
        for item in quality["categories"]
    )


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
    quality = runtime.quality(session_dir, first["job_id"])
    assert quality["overall"]["decisions"] == {"reject_candidate": 1}
    assert quality["overall"]["candidate_acceptance_rate"] == 0.0
    assert quality["overall"]["precision"] == 0.0
    assert quality["overall"]["false_positive_rate"] == 1.0


def test_second_job_reuses_catalog_revision_candidate_cache(tmp_path):
    runtime, _confirmations = _runtime(tmp_path)
    runtime.catalog_revision = lambda: "catalog-r1"
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()
    exact_calls = 0
    candidate_calls = 0
    original_exact = runtime.find_exact
    original_candidates = runtime.find_top_candidates

    def counted_exact(name):
        nonlocal exact_calls
        exact_calls += 1
        return original_exact(name)

    def counted_candidates(name, **kwargs):
        nonlocal candidate_calls
        candidate_calls += 1
        return original_candidates(name, **kwargs)

    runtime.find_exact = counted_exact
    runtime.find_top_candidates = counted_candidates

    first, _ = runtime.start(session_dir)
    first_status = runtime.status(session_dir, first["job_id"])["job"]
    first_counts = (exact_calls, candidate_calls)
    second, _ = runtime.start(session_dir)
    second_status = runtime.status(session_dir, second["job_id"])["job"]

    assert first_status["cache_hits"] == 0
    assert first_status["cache_misses"] == 2
    assert second_status["cache_hits"] == 2
    assert second_status["cache_misses"] == 0
    assert (exact_calls, candidate_calls) == first_counts


def test_same_product_cache_is_shared_but_supplier_decisions_are_isolated(tmp_path):
    frame = pd.DataFrame([
        {
            "OnlinerID": "",
            "Название": "Камера Exact A1",
            "Поставщик": "IVEN",
            "Категория": "IP-камеры",
        },
        {
            "OnlinerID": "",
            "Название": "Камера Exact A1",
            "Поставщик": "Tradex",
            "Категория": "IP-камеры",
        },
    ], index=[10, 20])
    runtime, confirmations = _runtime(tmp_path, frame=frame)
    runtime.catalog_revision = lambda: "catalog-r1"
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()

    first, _ = runtime.start(session_dir)
    report = runtime.items(session_dir, {"job_id": first["job_id"]})
    by_supplier = {item["supplier"]: item for item in report["items"]}
    runtime.decide(session_dir, {
        "job_id": first["job_id"],
        "item_key": by_supplier["IVEN"]["item_key"],
        "action": "reject_candidate",
        "candidate_id": "101",
    })

    second, _ = runtime.start(session_dir)
    report = runtime.items(session_dir, {"job_id": second["job_id"]})
    by_supplier = {item["supplier"]: item for item in report["items"]}

    assert by_supplier["IVEN"]["candidates"][0]["rejected"] is True
    assert by_supplier["IVEN"]["confidence_tier"] == "none"
    assert by_supplier["Tradex"]["candidates"][0]["rejected"] is False
    assert by_supplier["Tradex"]["confidence_tier"] == "exact"
    decision = runtime.decide(session_dir, {
        "job_id": second["job_id"],
        "item_key": by_supplier["Tradex"]["item_key"],
        "action": "confirm",
        "candidate_id": "101",
    })
    assert decision["status"] == "confirmed"
    assert confirmations[-1]["items"][0]["supplier"] == "Tradex"


def test_bulk_preview_and_decision_use_first_active_candidate(tmp_path):
    runtime, confirmations = _runtime(tmp_path)
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()
    started, _ = runtime.start(session_dir)
    report = runtime.items(session_dir, {"job_id": started["job_id"]})
    keys = [item["item_key"] for item in report["items"]]

    preview = runtime.bulk_preview(session_dir, {
        "job_id": started["job_id"],
        "action": "confirm",
        "item_keys": keys,
    })
    result = runtime.bulk_decide(session_dir, {
        "job_id": started["job_id"],
        "action": "confirm",
        "item_keys": keys,
    })

    assert preview["count"] == 2
    assert result["processed"] == 2
    assert result["failed"] == []
    assert len(confirmations) == 2
    history = runtime.history(session_dir, started["job_id"])
    assert len(history["decisions"]) == 2
    assert {row["action"] for row in history["decisions"]} == {"confirm"}


def test_undo_confirmation_requires_unchanged_current_id(tmp_path):
    frame = pd.DataFrame([{
        "OnlinerID": "",
        "Название": "Камера Exact A1",
        "Поставщик": "IVEN",
        "Категория": "IP-камеры",
    }], index=[10])
    runtime, _confirmations = _runtime(tmp_path, frame=frame)
    cleared = []
    runtime.read_dataframe = lambda _session_dir: frame.copy()
    runtime.clear_manual_id = lambda _session_dir, payload: (
        cleared.append(payload) or {"status": "ok", "cleared": 1}
    )
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()
    started, _ = runtime.start(session_dir)
    item = runtime.items(session_dir, {"job_id": started["job_id"]})["items"][0]
    runtime.decide(session_dir, {
        "job_id": started["job_id"],
        "item_key": item["item_key"],
        "action": "confirm",
        "candidate_id": "101",
    })
    frame.at[10, "OnlinerID"] = "101"
    decision_id = runtime.history(session_dir, started["job_id"])["decisions"][0]["decision_id"]

    result = runtime.undo(session_dir, {"decision_ids": [decision_id]})

    assert result == {"ok": True, "restored": 1, "failed": []}
    assert cleared[0]["item"]["supplier"] == "IVEN"
    assert runtime.items(
        session_dir,
        {"job_id": started["job_id"], "decision_state": "open"},
    )["total"] == 1
