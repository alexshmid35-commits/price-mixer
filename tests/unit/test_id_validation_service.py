"""Unit tests for Onliner ID validation helpers."""

import threading

import pandas as pd
import pytest

from price_mixer.services import id_validation as svc


def row(**kwargs):
    return pd.Series(kwargs)


def test_verify_onliner_id_row_returns_none_without_id():
    assert svc.verify_onliner_id_row(
        0,
        row(Название="SSD", OnlinerID=""),
        fetch_onliner_product_info=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
    ) is None


def test_verify_onliner_id_row_trusts_manual_confirmation():
    item = svc.verify_onliner_id_row(
        2,
        row(Название="SSD", OnlinerID="123", Поставщик="A", Категория="SSD"),
        settings={"verify_id": {"trust_manual_confirmed": True}},
        fetch_onliner_product_info=lambda oid, **kwargs: {"name": "Different", "url": "u", "source": "cache"},
        row_category=lambda item: item.get("Категория", ""),
        is_manually_confirmed_id=lambda name, oid: True,
    )

    assert item["status"] == "match"
    assert item["score"] == 1.0
    assert item["reason"] == "manual_confirmed"
    assert item["source"] == "cache|manual_confirmed"
    assert item["needs_review"] is False


def test_verify_onliner_id_row_handles_api_without_name_as_review_by_default():
    item = svc.verify_onliner_id_row(
        1,
        row(Название="SSD", OnlinerID="123"),
        fetch_onliner_product_info=lambda oid, **kwargs: {"name": "", "url": "u", "source": "api"},
    )

    assert item["status"] == "review"
    assert item["reason"] == "api_no_name"
    assert item["needs_review"] is True


def test_verify_onliner_id_row_can_mark_api_without_name_as_mismatch():
    item = svc.verify_onliner_id_row(
        1,
        row(Название="SSD", OnlinerID="123"),
        settings={"verify_id": {"api_no_name_status": "mismatch"}},
        fetch_onliner_product_info=lambda oid, **kwargs: {"name": "", "url": "u", "source": "api"},
    )

    assert item["status"] == "mismatch"


def test_verify_onliner_id_row_accepts_score_above_threshold():
    item = svc.verify_onliner_id_row(
        1,
        row(Название="SSD Kingston", OnlinerID="123", Поставщик="A"),
        settings={"verify_id": {"match_threshold": 0.8}},
        fetch_onliner_product_info=lambda oid, **kwargs: {"name": "SSD Kingston 1TB", "url": "u", "source": "api"},
        calc_name_match=lambda local, remote: {"score": 0.85, "match": False, "reason": "tokens"},
    )

    assert item["status"] == "match"
    assert item["score"] == 0.85
    assert item["reason_label"] == "Совпало"


def test_verify_onliner_id_row_strict_reason_can_override_score_match():
    item = svc.verify_onliner_id_row(
        1,
        row(Название="SSD Kingston", OnlinerID="123"),
        settings={"verify_id": {"match_threshold": 0.8, "require_article_or_model_priority": True}},
        fetch_onliner_product_info=lambda oid, **kwargs: {"name": "SSD Kingston 1TB", "url": "u", "source": "api"},
        calc_name_match=lambda local, remote: {"score": 0.95, "match": True, "reason": "tokens"},
    )

    assert item["status"] == "mismatch"
    assert item["needs_review"] is True


def test_build_start_states_are_mode_specific():
    verify_state = svc.build_verify_all_start_state(now=100)
    api_state = svc.build_validate_clean_start_state("api", now=101)
    db_state = svc.build_validate_clean_start_state("db", now=102)

    assert verify_state["message"] == "Подготовка проверки ID..."
    assert verify_state["started_at"] == 100
    assert api_state["mode"] == "api"
    assert api_state["mode_label"] == "Onliner API"
    assert db_state["mode"] == "db"
    assert db_state["mode_label"] == "Локальная БД 150k"
    assert api_state["cancelled"] is False
    assert api_state["cancel_requested"] is False
    assert db_state["cancelled"] is False
    assert db_state["cancel_requested"] is False


def test_build_validate_clean_no_column_state():
    assert svc.build_validate_clean_no_column_state(now=123) == {
        "running": False,
        "finished_at": 123,
        "message": "В текущем прайсе нет колонки OnlinerID.",
    }


def test_build_validate_clean_no_tasks_state_is_mode_specific():
    assert svc.build_validate_clean_no_tasks_state("api", now=123) == {
        "running": False,
        "finished_at": 123,
        "message": "Нет товаров с OnlinerID для проверки (или все TGPC ПЭВМ).",
    }
    assert svc.build_validate_clean_no_tasks_state("db", now=124) == {
        "running": False,
        "finished_at": 124,
        "message": "Нет товаров с OnlinerID для локальной проверки (или все TGPC ПЭВМ).",
    }


def test_build_validate_clean_error_state_is_mode_specific_and_truncates():
    long_error = "x" * 250

    api_state = svc.build_validate_clean_error_state("api", long_error, now=123)
    db_state = svc.build_validate_clean_error_state("db", RuntimeError("db failed"), now=124)

    assert api_state == {
        "running": False,
        "cancelled": False,
        "cancel_requested": False,
        "finished_at": 123,
        "message": "Ошибка валидации: " + ("x" * 180),
    }
    assert db_state == {
        "running": False,
        "cancelled": False,
        "cancel_requested": False,
        "finished_at": 124,
        "message": "Ошибка локальной проверки: db failed",
    }


def test_build_validate_clean_cancelled_state_is_mode_specific():
    assert svc.build_validate_clean_cancelled_state("api", now=123) == {
        "running": False,
        "cancelled": True,
        "cancel_requested": False,
        "finished_at": 123,
        "message": "Проверка ID отменена пользователем. Изменения не применены.",
    }
    assert svc.build_validate_clean_cancelled_state("db", now=124) == {
        "running": False,
        "cancelled": True,
        "cancel_requested": False,
        "finished_at": 124,
        "message": "Локальная проверка отменена пользователем. Изменения не применены.",
    }


def test_build_validate_clean_prepare_progress_state_for_api_mode():
    assert svc.build_validate_clean_prepare_progress_state("api", 7) == {
        "total": 7,
        "done": 0,
        "confirmed": 0,
        "cleared": 0,
        "queued": 0,
        "errors": 0,
        "message": "Фаза 1: проверяю 7 товаров...",
    }


def test_build_validate_clean_prepare_progress_state_for_db_mode():
    assert svc.build_validate_clean_prepare_progress_state("db", 8) == {
        "total": 8,
        "done": 0,
        "confirmed": 0,
        "cleared": 0,
        "queued": 0,
        "errors": 0,
        "skipped_api": 0,
        "mode": "db",
        "mode_label": "Локальная БД 150k",
        "skipped_label": "Пропуск = ID или имя не найдены в локальной БД, поэтому ID оставили без изменений.",
        "message": "Локальная сверка: проверяю 8 товаров...",
    }


def test_build_validate_clean_step_progress_state_is_mode_specific_and_truncates_name():
    long_name = "A" * 70

    api_state = svc.build_validate_clean_step_progress_state(
        "api",
        done=2,
        total=10,
        current_name=long_name,
        confirmed=1,
        cleared=3,
        skipped=4,
        errors=5,
    )
    db_state = svc.build_validate_clean_step_progress_state(
        "db",
        done=3,
        total=11,
        current_name="SSD",
        confirmed=2,
        cleared=4,
        skipped=6,
        errors=7,
    )

    assert api_state == {
        "done": 2,
        "confirmed": 1,
        "cleared": 3,
        "skipped_api": 4,
        "errors": 5,
        "message": "Фаза 1: 2/10 — " + ("A" * 55),
    }
    assert db_state == {
        "done": 3,
        "confirmed": 2,
        "cleared": 4,
        "skipped_api": 6,
        "errors": 7,
        "message": "Локальная сверка: 3/11 — SSD",
    }


def test_build_validate_clean_candidates_start_state_is_mode_specific():
    assert svc.build_validate_clean_candidates_start_state("api", 3) == {
        "message": "Фаза 2: ищу кандидатов для 3 очищенных товаров...",
    }
    assert svc.build_validate_clean_candidates_start_state("db", 4) == {
        "message": "Локальная сверка: ищу кандидатов для 4 очищенных товаров...",
    }


def test_build_validate_clean_candidates_step_state_is_mode_specific_and_truncates_name():
    long_name = "B" * 70

    assert svc.build_validate_clean_candidates_step_state("api", 2, 5, long_name) == {
        "message": "Фаза 2: кандидаты 2/5 — " + ("B" * 50),
    }
    assert svc.build_validate_clean_candidates_step_state("db", 3, 6, "SSD") == {
        "message": "Локальная сверка: кандидаты 3/6 — SSD",
    }


def test_build_validate_clean_queued_state():
    assert svc.build_validate_clean_queued_state(7) == {"queued": 7}


def test_save_validate_clean_results_writes_api_outputs_and_journal(tmp_path):
    calls = []
    df = pd.DataFrame({"OnlinerID": ["111"]})
    manual_bindings = {"ssd": {"id": "111"}}
    review_queue = {"ssd": {"name": "SSD"}}
    journal_changes = [{"row_idx": 1}]

    journal_entry = svc.save_validate_clean_results(
        "api",
        tmp_path,
        df,
        manual_bindings,
        review_queue,
        journal_changes,
        save_manual_id_bindings=lambda payload: calls.append(("manual", payload)),
        save_review_queue=lambda payload: calls.append(("queue", payload)),
        append_id_change_journal=lambda payload: calls.append(("journal", payload)),
        write_consolidated_df=lambda session_dir, payload: calls.append(("xlsx", session_dir, payload)),
        write_consolidated_json=lambda payload, path: calls.append(("json", path, payload)),
        now=123,
    )

    assert journal_entry == {
        "ts": 123,
        "action": "validate_clean_ids",
        "session_dir": str(tmp_path),
        "source": "api_validate_clean_ids",
        "changes": journal_changes,
    }
    assert calls[0] == ("manual", manual_bindings)
    assert calls[1] == ("queue", review_queue)
    assert calls[2] == ("journal", journal_entry)
    assert calls[3] == ("xlsx", tmp_path, df)
    assert calls[4] == ("json", tmp_path / "consolidated.json", df)


def test_save_validate_clean_results_uses_db_journal_metadata(tmp_path):
    calls = []

    journal_entry = svc.save_validate_clean_results(
        "db",
        tmp_path,
        pd.DataFrame(),
        {},
        {},
        [{"row_idx": 1}],
        append_id_change_journal=lambda payload: calls.append(payload),
        now=456,
    )

    assert journal_entry["ts"] == 456
    assert journal_entry["action"] == "validate_clean_ids_db"
    assert journal_entry["source"] == "api_validate_clean_ids_db"
    assert calls == [journal_entry]


def test_save_validate_clean_results_skips_empty_journal(tmp_path):
    calls = []

    journal_entry = svc.save_validate_clean_results(
        "api",
        tmp_path,
        pd.DataFrame(),
        {},
        {},
        [],
        append_id_change_journal=lambda payload: calls.append(payload),
    )

    assert journal_entry is None
    assert calls == []


def test_run_validate_clean_api_tasks_applies_confirm_skip_and_clear():
    df = pd.DataFrame({
        "Название": ["Good SSD", "Timeout SSD", "Wrong SSD"],
        "OnlinerID": ["111", "222", "333"],
        "Ссылка": ["u1", "u2", "u3"],
    }, index=[10, 11, 12])
    progress = []
    logs = []
    manual_bindings = {}
    product_cache = {}

    def fetch_product_name(oid, hard_timeout):
        if oid == "111":
            return "Good SSD Remote", "remote-111", "ok"
        if oid == "222":
            return "", "remote-222", "timeout"
        return "Different Remote", "remote-333", "ok"

    def calc_name_match(local, remote):
        return {"score": 0.9 if "Good" in local else 0.2, "reason": "tokens"}

    state = svc.run_validate_clean_api_tasks(
        df,
        [(idx, row.copy()) for idx, row in df.iterrows()],
        manual_bindings,
        product_cache,
        product_cache_ttl=10,
        fetch_product_name=fetch_product_name,
        is_manually_confirmed_id=lambda name, oid: False,
        calc_name_match=calc_name_match,
        normalize_name_key=lambda name: name.lower().replace(" ", "-"),
        progress_update=progress.append,
        log=logs.append,
        clear_value=pd.NA,
        progress_every=2,
    )

    assert state["done"] == 3
    assert state["confirmed"] == 1
    assert state["skipped"] == 1
    assert state["errors"] == 0
    assert state["confirmed_rows"] == [{
        "name": "Good SSD",
        "onliner_id": "111",
        "api_name": "Good SSD Remote",
        "score": 0.9,
    }]
    assert state["skipped_rows"] == [{
        "name": "Timeout SSD",
        "onliner_id": "222",
        "reason": "api_unreachable_timeout",
    }]
    assert state["cleared_items"] == [(12, "Wrong SSD", "wrong-ssd", "333", "Different Remote", 0.2, "tokens")]
    assert state["journal_changes"][0]["old_url"] == "u3"
    assert pd.isna(df.at[12, "OnlinerID"])
    assert manual_bindings == {"good-ssd": {"id": "111", "url": "remote-111"}}
    assert product_cache["111"]["name"] == "Good SSD Remote"
    assert progress[-1]["message"] == "Фаза 1: 3/3 — Wrong SSD"
    assert logs[0] == "[validate] Старт Фазы 1: 3 товаров"


def test_run_validate_clean_api_tasks_records_errors_and_continues():
    df = pd.DataFrame({"Название": ["Broken"], "OnlinerID": ["111"]}, index=[10])

    state = svc.run_validate_clean_api_tasks(
        df,
        [(10, df.loc[10].copy())],
        {},
        {},
        product_cache_ttl=10,
        fetch_product_name=lambda oid, hard_timeout: (_ for _ in ()).throw(RuntimeError("network down")),
        is_manually_confirmed_id=lambda name, oid: False,
        calc_name_match=lambda local, remote: {"score": 0.0},
        normalize_name_key=lambda name: name,
        progress_update=lambda payload: None,
        log=lambda message: None,
    )

    assert state["done"] == 1
    assert state["errors"] == 1
    assert state["confirmed"] == 0
    assert state["cleared_items"] == []


def test_run_validate_clean_db_tasks_applies_confirm_skip_and_clear():
    df = pd.DataFrame({
        "Название": ["Good SSD", "Skip SSD", "Wrong SSD"],
        "OnlinerID": ["111", "222", "333"],
        "Ссылка": ["u1", "u2", "u3"],
    }, index=[10, 11, 12])
    manual_bindings = {}
    progress = []

    def db_get_product_by_id(oid):
        return {
            "111": {"name": "Good SSD Remote", "url": "db-111"},
            "333": {"name": "Different Remote", "url": "db-333"},
        }.get(oid)

    def db_find_exact_id_for_name(name):
        if name == "Skip SSD":
            return {"id": "222", "name": "Skip SSD"}
        return None

    def calc_name_match(local, remote):
        return {"score": 0.88 if "Good" in local else 0.1, "reason": "tokens"}

    state = svc.run_validate_clean_db_tasks(
        df,
        [(idx, row.copy()) for idx, row in df.iterrows()],
        manual_bindings,
        is_manually_confirmed_id=lambda name, oid: False,
        db_get_product_by_id=db_get_product_by_id,
        db_find_exact_id_for_name=db_find_exact_id_for_name,
        calc_name_match=calc_name_match,
        normalize_name_key=lambda name: name.lower().replace(" ", "-"),
        progress_update=progress.append,
        log=lambda message: None,
        clear_value=pd.NA,
        progress_every=2,
    )

    assert state["done"] == 3
    assert state["confirmed"] == 1
    assert state["skipped"] == 1
    assert state["confirmed_rows"][0]["api_name"] == "Good SSD Remote"
    assert state["skipped_rows"] == [{"name": "Skip SSD", "onliner_id": "222", "reason": "db_missing_or_uncertain"}]
    assert state["cleared_items"] == [(12, "Wrong SSD", "wrong-ssd", "333", "Different Remote", 0.1, "db_id_name_mismatch", None)]
    assert pd.isna(df.at[12, "Ссылка"])
    assert manual_bindings == {"good-ssd": {"id": "111", "url": "db-111"}}
    assert progress[-1]["message"] == "Локальная сверка: 3/3 — Wrong SSD"


def test_run_validate_clean_db_tasks_stops_before_mutation_when_cancelled():
    df = pd.DataFrame({
        "Название": ["Wrong SSD"],
        "OnlinerID": ["333"],
        "Ссылка": ["u3"],
    }, index=[12])

    with pytest.raises(svc.ValidationCancelledError):
        svc.run_validate_clean_db_tasks(
            df,
            [(12, df.loc[12].copy())],
            {},
            is_manually_confirmed_id=lambda name, oid: False,
            db_get_product_by_id=lambda oid: {"name": "Different Remote", "url": "db-333"},
            db_find_exact_id_for_name=lambda name: None,
            calc_name_match=lambda local, remote: {"score": 0.1, "reason": "tokens"},
            normalize_name_key=lambda name: "wrong-ssd",
            should_cancel=lambda: True,
        )

    assert df.at[12, "OnlinerID"] == "333"
    assert df.at[12, "Ссылка"] == "u3"


def test_populate_api_review_queue_for_cleared_items_updates_queue_and_progress():
    review_queue = {}
    progress = []
    cleared_items = [
        (10, "Good SSD", "good", "111", "Old API", 0.2, "low"),
        (11, "No Candidates", "none", "222", "", 0.0, "api_not_found"),
    ]

    def search_onliner_candidates(name, **kwargs):
        if name == "Good SSD":
            return [{"id": "999", "name": "Good SSD Remote", "score": 0.91, "url": "u"}]
        return []

    queued = svc.populate_api_review_queue_for_cleared_items(
        cleared_items,
        review_queue,
        search_onliner_candidates,
        limit_cands=80,
        progress_update=progress.append,
    )

    assert queued == 1
    assert review_queue["good"]["candidates"] == [{
        "id": "999",
        "name": "Good SSD Remote",
        "score": 0.91,
        "url": "u",
    }]
    assert review_queue["none"]["candidates"] == []
    assert progress[0]["message"] == "Фаза 2: ищу кандидатов для 2 очищенных товаров..."
    assert progress[-1] == {"queued": 1}


def test_populate_db_review_queue_for_cleared_items_updates_queue_and_progress():
    review_queue = {}
    progress = []
    exact = {"id": "999", "name": "Exact SSD", "url": "u"}

    queued = svc.populate_db_review_queue_for_cleared_items(
        [(10, "Good SSD", "good", "111", "Old DB", 0.1, "low", exact)],
        review_queue,
        db_find_top_candidates=lambda name, top_n, min_score: [
            {"id": "999", "name": "Duplicate", "score": 0.8},
            {"id": "888", "name": "Fuzzy", "score": 0.7},
        ],
        progress_update=progress.append,
    )

    assert queued == 1
    assert [candidate["id"] for candidate in review_queue["good"]["candidates"]] == ["999", "888"]
    assert review_queue["good"]["onliner_name"] == "Old DB"
    assert progress[0]["message"] == "Локальная сверка: ищу кандидатов для 1 очищенных товаров..."
    assert progress[-1] == {"queued": 1}


def test_start_validation_job_validates_session_and_file(tmp_path):
    status = {}
    lock = threading.RLock()

    no_session, no_session_status = svc.start_validation_job(
        "",
        status,
        lock,
        {"running": True},
        worker=lambda session_dir: None,
        thread_factory=lambda **kwargs: None,
    )
    assert no_session_status == 400
    assert no_session["message"] == "Нет активной сессии"

    no_file, no_file_status = svc.start_validation_job(
        tmp_path,
        status,
        lock,
        {"running": True},
        worker=lambda session_dir: None,
        thread_factory=lambda **kwargs: None,
    )
    assert no_file_status == 400
    assert no_file["message"] == "Нет данных"


def test_start_validation_job_sets_status_and_starts_thread(tmp_path):
    (tmp_path / "consolidated.json").write_text("{}", encoding="utf-8")
    status = {"running": False, "old": True}
    started = {}
    prepared = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            started["target"] = target
            started["args"] = args
            started["daemon"] = daemon

        def start(self):
            started["started"] = True

    result = svc.start_validation_job(
        tmp_path,
        status,
        threading.RLock(),
        {"running": True, "message": "go"},
        worker=lambda session_dir: None,
        thread_factory=FakeThread,
        before_start=lambda session_dir: prepared.append(str(session_dir)),
    )

    assert result == {"status": "started"}
    assert status == {"running": True, "message": "go"}
    assert started["args"] == (str(tmp_path),)
    assert started["daemon"] is True
    assert started["started"] is True
    assert prepared == [str(tmp_path)]


def test_start_validation_job_reports_already_running(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("exists", encoding="utf-8")

    result = svc.start_validation_job(
        tmp_path,
        {"running": True},
        threading.RLock(),
        {"running": True},
        worker=lambda session_dir: None,
        thread_factory=lambda **kwargs: None,
    )

    assert result == {"status": "already_running"}


def test_cancel_validation_job_marks_running_job_and_invokes_cancel(tmp_path):
    status = {"running": True, "message": "working"}
    cancelled = []

    result = svc.cancel_validation_job(
        tmp_path,
        status,
        threading.RLock(),
        cancel=lambda session_dir: cancelled.append(str(session_dir)),
    )

    assert result == {"status": "cancelling", "message": "Останавливаю проверку..."}
    assert status["running"] is True
    assert status["cancel_requested"] is True
    assert status["message"] == "Останавливаю проверку..."
    assert cancelled == [str(tmp_path)]


def test_cancel_validation_job_reports_when_job_is_not_running(tmp_path):
    result = svc.cancel_validation_job(
        tmp_path,
        {"running": False},
        threading.RLock(),
        cancel=lambda session_dir: pytest.fail("cancel should not be called"),
    )

    assert result == {"status": "not_running", "message": "Активной проверки нет."}


def test_status_snapshots_copy_items_and_dicts():
    lock = threading.RLock()
    verify_status = {"items": [{"id": 1}], "running": True}
    clean_status = {"running": False, "mode": "api"}

    verify_snapshot = svc.verify_all_status_snapshot(verify_status, lock)
    clean_snapshot = svc.status_snapshot(clean_status, lock)

    assert verify_snapshot == {"items": [{"id": 1}], "running": True}
    assert verify_snapshot["items"] is not verify_status["items"]
    assert clean_snapshot == clean_status
    assert clean_snapshot is not clean_status


def test_collect_id_validation_tasks_filters_empty_ids_names_and_tgpc():
    df = pd.DataFrame({
        "Название": ["SSD", "", "TGPC Action", "Mouse"],
        "OnlinerID": ["111", "222", "333", ""],
    }, index=[10, 11, 12, 13])

    tasks, skipped = svc.collect_id_validation_tasks(
        df,
        is_tgpc_pc_name=lambda name: name.startswith("TGPC"),
        require_name=True,
    )

    assert [(idx, row["Название"]) for idx, row in tasks] == [(10, "SSD")]
    assert skipped == 1

    tasks_without_name, skipped_without_name = svc.collect_id_validation_tasks(
        df,
        is_tgpc_pc_name=lambda name: name.startswith("TGPC"),
        require_name=False,
    )

    assert [(idx, row["Название"]) for idx, row in tasks_without_name] == [(10, "SSD"), (11, "")]
    assert skipped_without_name == 1


def test_sort_verify_result_items_orders_ui_and_report_lists():
    result_items = [
        {"name": "B", "score": 0.9},
        {"name": "A", "score": 0.1},
    ]
    report_items = [
        {"name": "Review", "status": "review"},
        {"name": "Match", "status": "match"},
        {"name": "Mismatch", "status": "mismatch"},
    ]

    sorted_results, sorted_report = svc.sort_verify_result_items(result_items, report_items)

    assert [item["name"] for item in sorted_results] == ["A", "B"]
    assert [item["name"] for item in sorted_report] == ["Mismatch", "Review", "Match"]


def test_build_validate_cleared_rows_report_for_api_mode():
    rows = svc.build_validate_cleared_rows_report([
        (1, "Missing", "k1", "111", "", 0.0, "api_not_found"),
        (2, "Low", "k2", "222", "Remote name", 0.2, "low_score"),
        (3, "Empty", "k3", "333", "", 0.0, "other"),
    ], mode="api")

    assert rows == [
        {
            "name": "Missing",
            "onliner_id": "111",
            "api_name": "HTTP 404 — товара с этим ID нет в каталоге Onliner",
            "score": 0.0,
            "clear_reason": "api_not_found",
        },
        {
            "name": "Low",
            "onliner_id": "222",
            "api_name": "Remote name",
            "score": 0.2,
            "clear_reason": "low_score",
        },
        {
            "name": "Empty",
            "onliner_id": "333",
            "api_name": "—",
            "score": 0.0,
            "clear_reason": "other",
        },
    ]


def test_build_validate_cleared_rows_report_for_db_mode():
    rows = svc.build_validate_cleared_rows_report([
        (1, "Exact", "k1", "111", "", 0.0, "db_exact_points_other_id", {"id": "999"}),
        (2, "Low", "k2", "222", "DB name", 0.2, "db_low_score", None),
    ], mode="db")

    assert rows == [
        {
            "name": "Exact",
            "onliner_id": "111",
            "api_name": "Локальная БД знает этот товар как ID 999",
            "score": 0.0,
            "clear_reason": "db_exact_points_other_id",
        },
        {
            "name": "Low",
            "onliner_id": "222",
            "api_name": "DB name",
            "score": 0.2,
            "clear_reason": "db_low_score",
        },
    ]


def test_build_validate_clean_finish_state_for_api_mode_limits_skipped_rows():
    skipped_rows = [{"name": str(i)} for i in range(502)]
    confirmed_rows = [{"name": "OK", "onliner_id": "111", "api_name": "Remote", "score": 0.9}]

    state = svc.build_validate_clean_finish_state(
        mode="api",
        total=10,
        confirmed=2,
        cleared_items=[
            (1, "Missing", "k1", "111", "", 0.0, "api_not_found"),
            (2, "Low", "k2", "222", "Remote name", 0.2, "low_score"),
        ],
        skipped=3,
        queued=1,
        errors=4,
        confirmed_rows=confirmed_rows,
        skipped_rows=skipped_rows,
        now=123,
    )

    assert state["running"] is False
    assert state["done"] == 10
    assert state["confirmed"] == 2
    assert state["cleared"] == 2
    assert state["skipped_api"] == 3
    assert state["queued"] == 1
    assert state["errors"] == 4
    assert state["finished_at"] == 123
    assert state["confirmed_rows"] == confirmed_rows
    assert len(state["skipped_rows"]) == 500
    assert state["cleared_rows"][0]["api_name"] == "HTTP 404 — товара с этим ID нет в каталоге Onliner"
    assert state["message"] == (
        "Готово. Подтверждено: 2, очищено: 2, "
        "пропущено (сбой API, ID сохранён): 3, ошибок: 4."
    )


def test_build_validate_clean_finish_state_for_db_mode_omits_empty_parts():
    state = svc.build_validate_clean_finish_state(
        mode="db",
        total=5,
        confirmed=1,
        cleared_items=[
            (1, "Exact", "k1", "111", "", 0.0, "db_exact_points_other_id", {"id": "999"}),
        ],
        skipped=0,
        queued=0,
        errors=0,
        confirmed_rows=[],
        skipped_rows=[],
        now=456,
    )

    assert state == {
        "running": False,
        "done": 5,
        "confirmed": 1,
        "cleared": 1,
        "skipped_api": 0,
        "queued": 0,
        "errors": 0,
        "finished_at": 456,
        "cleared_rows": [{
            "name": "Exact",
            "onliner_id": "111",
            "api_name": "Локальная БД знает этот товар как ID 999",
            "score": 0.0,
            "clear_reason": "db_exact_points_other_id",
        }],
        "confirmed_rows": [],
        "skipped_rows": [],
        "message": "Локальная сверка готова. Подтверждено: 1, очищено: 1.",
    }


def test_build_db_review_candidates_prioritizes_exact_and_deduplicates():
    candidates = svc.build_db_review_candidates(
        exact_match={"id": "111", "name": "Exact SSD", "url": "u1"},
        fuzzy_candidates=[
            {"id": "111", "name": "Duplicate SSD", "url": "u2", "score": 0.9},
            {"id": "222", "name": "Fuzzy SSD", "url": "u3", "score": 0.8765},
        ],
    )

    assert candidates == [
        {
            "id": "111",
            "name": "Exact SSD",
            "score": 1.0,
            "url": "u1",
            "source": "db_exact",
        },
        {
            "id": "222",
            "name": "Fuzzy SSD",
            "score": 0.876,
            "url": "u3",
            "source": "db_fuzzy",
        },
    ]


def test_build_db_review_candidates_handles_empty_bad_ids_and_limit():
    candidates = svc.build_db_review_candidates(
        exact_match={"id": "", "name": "No ID"},
        fuzzy_candidates=[
            {"id": None, "name": "Bad"},
            {"id": "333", "name": "First", "score": "0.71"},
            {"id": "444", "name": "Second", "score": 0.62},
        ],
        limit=1,
    )

    assert candidates == [
        {
            "id": "333",
            "name": "First",
            "score": 0.71,
            "url": "",
            "source": "db_fuzzy",
        },
    ]


def test_build_api_review_candidates_normalizes_deduplicates_and_limits():
    candidates = svc.build_api_review_candidates([
        {"id": "111", "name": " First ", "score": 0.9012, "url": " u1 "},
        {"id": "111", "name": "Duplicate", "score": 0.8, "url": "u2"},
        {"id": "", "name": "No ID", "score": 1.0, "url": "u3"},
        {"id": "222", "name": "Second", "score": "0.71", "url": ""},
        {"id": "333", "name": "Third", "score": 0.62, "url": "u4"},
        {"id": "444", "name": "Fourth", "score": 0.5, "url": "u5"},
    ], limit=3)

    assert candidates == [
        {"id": "111", "name": "First", "score": 0.901, "url": "u1"},
        {"id": "222", "name": "Second", "score": 0.71, "url": ""},
        {"id": "333", "name": "Third", "score": 0.62, "url": "u4"},
    ]


def test_build_db_review_queue_item_limits_candidates_and_sets_timestamp():
    item = svc.build_db_review_queue_item(
        name="  SSD  ",
        cleared_id=" 111 ",
        cleared_score=0.6549,
        onliner_name="  Old DB name  ",
        candidates=[{"id": str(i)} for i in range(7)],
        now=123,
    )

    assert item == {
        "name": "SSD",
        "cleared_id": "111",
        "cleared_score": 0.655,
        "onliner_name": "Old DB name",
        "candidates": [{"id": str(i)} for i in range(5)],
        "added_at": 123,
    }


def test_build_api_review_queue_item_uses_api_candidate_limit():
    item = svc.build_api_review_queue_item(
        name="SSD",
        cleared_id="111",
        cleared_score=0.5,
        onliner_name="Wrong API name",
        candidates=[{"id": str(i)} for i in range(5)],
        now=456,
    )

    assert item == {
        "name": "SSD",
        "cleared_id": "111",
        "cleared_score": 0.5,
        "onliner_name": "Wrong API name",
        "candidates": [{"id": str(i)} for i in range(3)],
        "added_at": 456,
    }


def test_validate_clean_api_row_returns_none_without_id():
    assert svc.validate_clean_api_row(
        7,
        row(Название="SSD", OnlinerID=""),
        fetch_product_name=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
    ) is None


def test_validate_clean_api_row_confirms_manual_id_without_fetch():
    result = svc.validate_clean_api_row(
        7,
        row(Название="SSD", OnlinerID="111"),
        fetch_product_name=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
        is_manually_confirmed_id=lambda name, oid: True,
    )

    assert result == {
        "row_idx": 7,
        "onliner_id": "111",
        "name": "SSD",
        "api_name": "",
        "api_url": "",
        "score": 1.0,
        "reason": "manual_confirmed",
        "record_confirm": True,
        "mutate_df_clear": False,
    }


def test_validate_clean_api_row_skips_fresh_empty_cache_without_fetch():
    result = svc.validate_clean_api_row(
        1,
        row(Название="SSD", OnlinerID="111"),
        product_cache={"111": {"updated_at": 100, "name": "", "url": "u"}},
        product_cache_ttl=10,
        now=105,
        fetch_product_name=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    assert result["reason"] == "api_unreachable_cached_empty"
    assert result["record_confirm"] is False
    assert result["mutate_df_clear"] is False
    assert result["api_url"] == "u"


def test_validate_clean_api_row_clears_not_found():
    result = svc.validate_clean_api_row(
        2,
        row(Название="SSD", OnlinerID="111"),
        fetch_product_name=lambda oid, hard_timeout: ("", "", "not_found"),
    )

    assert result["reason"] == "api_not_found"
    assert result["score"] == 0.0
    assert result["record_confirm"] is False
    assert result["mutate_df_clear"] is True


def test_validate_clean_api_row_skips_transient_fetch_errors():
    result = svc.validate_clean_api_row(
        2,
        row(Название="SSD", OnlinerID="111"),
        fetch_product_name=lambda oid, hard_timeout: ("", "u", "timeout"),
    )

    assert result["reason"] == "api_unreachable_timeout"
    assert result["api_url"] == "u"
    assert result["record_confirm"] is False
    assert result["mutate_df_clear"] is False


def test_validate_clean_api_row_fetches_caches_and_confirms_match():
    product_cache = {}
    result = svc.validate_clean_api_row(
        2,
        row(Название="SSD Kingston", OnlinerID="111"),
        product_cache=product_cache,
        product_cache_ttl=10,
        now=200,
        fetch_product_name=lambda oid, hard_timeout: ("SSD Kingston 1TB", "u", "ok"),
        calc_name_match=lambda local, remote: {"score": 0.8123, "reason": "model_token"},
        clear_threshold=0.65,
        cache_lock=threading.RLock(),
    )

    assert result == {
        "row_idx": 2,
        "onliner_id": "111",
        "name": "SSD Kingston",
        "api_name": "SSD Kingston 1TB",
        "api_url": "u",
        "score": 0.812,
        "reason": "model_token",
        "record_confirm": True,
        "mutate_df_clear": False,
    }
    assert product_cache["111"] == {"updated_at": 200, "name": "SSD Kingston 1TB", "url": "u"}


def test_validate_clean_api_row_clears_low_score():
    result = svc.validate_clean_api_row(
        2,
        row(Название="SSD Kingston", OnlinerID="111"),
        product_cache={"111": {"updated_at": 200, "name": "Logitech Mouse", "url": "u"}},
        product_cache_ttl=10,
        now=201,
        fetch_product_name=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
        calc_name_match=lambda local, remote: {"score": 0.2, "reason": "low"},
        clear_threshold=0.65,
    )

    assert result["api_name"] == "Logitech Mouse"
    assert result["score"] == 0.2
    assert result["reason"] == "low"
    assert result["record_confirm"] is False
    assert result["mutate_df_clear"] is True


def test_apply_validate_clean_api_result_records_skip():
    df = pd.DataFrame({"OnlinerID": ["111"], "Ссылка": ["u"]}, index=[5])
    skipped_rows = []

    deltas = svc.apply_validate_clean_api_result(
        df,
        {
            "row_idx": 5,
            "name": "SSD",
            "onliner_id": "111",
            "reason": "api_unreachable_timeout",
            "record_confirm": False,
            "mutate_df_clear": False,
        },
        "ssd",
        {},
        [],
        skipped_rows,
        [],
        [],
    )

    assert deltas == {"confirmed": 0, "skipped_api": 1}
    assert skipped_rows == [{"name": "SSD", "onliner_id": "111", "reason": "api_unreachable_timeout"}]
    assert df.at[5, "OnlinerID"] == "111"


def test_apply_validate_clean_api_result_confirms_and_updates_manual_binding():
    manual_bindings = {}
    confirmed_rows = []

    deltas = svc.apply_validate_clean_api_result(
        pd.DataFrame({"OnlinerID": ["111"]}, index=[5]),
        {
            "row_idx": 5,
            "name": "SSD",
            "onliner_id": "111",
            "api_name": "SSD remote",
            "api_url": "u",
            "score": 0.9123,
            "reason": "model_token",
            "record_confirm": True,
            "mutate_df_clear": False,
        },
        "ssd",
        manual_bindings,
        confirmed_rows,
        [],
        [],
        [],
    )

    assert deltas == {"confirmed": 1, "skipped_api": 0}
    assert manual_bindings == {"ssd": {"id": "111", "url": "u"}}
    assert confirmed_rows == [{"name": "SSD", "onliner_id": "111", "api_name": "SSD remote", "score": 0.912}]


def test_apply_validate_clean_api_result_does_not_bind_manual_confirmation():
    manual_bindings = {}
    confirmed_rows = []

    svc.apply_validate_clean_api_result(
        pd.DataFrame({"OnlinerID": ["111"]}, index=[5]),
        {
            "row_idx": 5,
            "name": "SSD",
            "onliner_id": "111",
            "score": 1.0,
            "reason": "manual_confirmed",
            "record_confirm": True,
            "mutate_df_clear": False,
        },
        "ssd",
        manual_bindings,
        confirmed_rows,
        [],
        [],
        [],
    )

    assert manual_bindings == {}
    assert confirmed_rows == [{"name": "SSD", "onliner_id": "111", "api_name": "", "score": 1.0}]


def test_apply_validate_clean_api_result_clears_row_and_records_journal():
    df = pd.DataFrame({"OnlinerID": ["111"], "Ссылка": ["old-url"]}, index=[5])
    cleared_items = []
    journal_changes = []

    deltas = svc.apply_validate_clean_api_result(
        df,
        {
            "row_idx": 5,
            "name": "SSD",
            "onliner_id": "111",
            "api_name": "Wrong remote",
            "score": 0.2345,
            "reason": "low",
            "record_confirm": False,
            "mutate_df_clear": True,
        },
        "ssd",
        {},
        [],
        [],
        cleared_items,
        journal_changes,
        clear_value=pd.NA,
    )

    assert deltas == {"confirmed": 0, "skipped_api": 0}
    assert pd.isna(df.at[5, "OnlinerID"])
    assert pd.isna(df.at[5, "Ссылка"])
    assert cleared_items == [(5, "SSD", "ssd", "111", "Wrong remote", 0.234, "low")]
    assert journal_changes == [{
        "row_idx": 5,
        "name": "SSD",
        "old_onliner_id": "111",
        "old_url": "old-url",
        "new_onliner_id": "",
        "new_url": "",
        "reason": "validate_clean score=0.234",
    }]


def test_apply_validate_clean_api_result_uses_specific_not_found_journal_reason():
    journal_changes = []

    svc.apply_validate_clean_api_result(
        pd.DataFrame({"OnlinerID": ["111"]}, index=[5]),
        {
            "row_idx": 5,
            "name": "SSD",
            "onliner_id": "111",
            "score": 0.0,
            "reason": "api_not_found",
            "record_confirm": False,
            "mutate_df_clear": True,
        },
        "ssd",
        {},
        [],
        [],
        [],
        journal_changes,
    )

    assert journal_changes[0]["reason"] == "validate_clean api_not_found"


def test_validate_clean_db_row_confirms_manual_id():
    result = svc.validate_clean_db_row(
        "SSD",
        "111",
        is_manually_confirmed_id=lambda name, oid: True,
        db_get_product_by_id=lambda oid: (_ for _ in ()).throw(AssertionError("should not query db")),
    )

    assert result == {
        "status": "confirm",
        "db_name": "",
        "score": 1.0,
        "reason": "manual_confirmed",
        "exact_match": None,
    }


def test_validate_clean_db_row_confirms_current_db_match():
    exact = {"id": "111", "name": "SSD exact"}

    result = svc.validate_clean_db_row(
        "SSD Kingston",
        "111",
        db_get_product_by_id=lambda oid: {"name": "SSD Kingston 1TB"},
        db_find_exact_id_for_name=lambda name: exact,
        calc_name_match=lambda local, remote: {"score": 0.87, "reason": "model_token"},
        clear_threshold=0.65,
    )

    assert result == {
        "status": "confirm",
        "db_name": "SSD Kingston 1TB",
        "score": 0.87,
        "reason": "model_token",
        "exact_match": exact,
    }


def test_validate_clean_db_row_clears_current_db_mismatch():
    result = svc.validate_clean_db_row(
        "SSD Kingston",
        "111",
        db_get_product_by_id=lambda oid: {"name": "Logitech Mouse"},
        db_find_exact_id_for_name=lambda name: None,
        calc_name_match=lambda local, remote: {"score": 0.2, "reason": "low"},
        clear_threshold=0.65,
    )

    assert result == {
        "status": "clear",
        "db_name": "Logitech Mouse",
        "score": 0.2,
        "reason": "db_id_name_mismatch",
        "exact_match": None,
    }


def test_validate_clean_db_row_clears_when_exact_name_points_to_other_id():
    exact = {"id": "222", "name": "SSD Kingston"}

    result = svc.validate_clean_db_row(
        "SSD Kingston",
        "111",
        db_get_product_by_id=lambda oid: None,
        db_find_exact_id_for_name=lambda name: exact,
    )

    assert result == {
        "status": "clear",
        "db_name": "SSD Kingston",
        "score": 0.0,
        "reason": "db_exact_points_other_id",
        "exact_match": exact,
    }


def test_validate_clean_db_row_skips_missing_or_same_exact_id():
    exact = {"id": "111", "name": "SSD Kingston"}

    result = svc.validate_clean_db_row(
        "SSD Kingston",
        "111",
        db_get_product_by_id=lambda oid: None,
        db_find_exact_id_for_name=lambda name: exact,
    )

    assert result == {
        "status": "skip",
        "db_name": "",
        "score": 0.0,
        "reason": "db_missing_or_uncertain",
        "exact_match": exact,
    }


def test_apply_validate_clean_db_result_records_skip():
    skipped_rows = []

    deltas = svc.apply_validate_clean_db_result(
        pd.DataFrame({"OnlinerID": ["111"]}, index=[5]),
        {"status": "skip", "reason": "db_missing_or_uncertain"},
        5,
        "SSD",
        "ssd",
        "111",
        {},
        [],
        skipped_rows,
        [],
        [],
    )

    assert deltas == {"confirmed": 0, "skipped_local": 1}
    assert skipped_rows == [{"name": "SSD", "onliner_id": "111", "reason": "db_missing_or_uncertain"}]


def test_apply_validate_clean_db_result_confirms_and_updates_manual_binding():
    manual_bindings = {}
    confirmed_rows = []

    deltas = svc.apply_validate_clean_db_result(
        pd.DataFrame({"OnlinerID": ["111"]}, index=[5]),
        {
            "status": "confirm",
            "db_name": "SSD Kingston 1TB",
            "score": 0.8765,
            "reason": "model_token",
        },
        5,
        "SSD Kingston",
        "ssd",
        "111",
        manual_bindings,
        confirmed_rows,
        [],
        [],
        [],
        db_get_product_by_id=lambda oid: {"url": "db-url"},
    )

    assert deltas == {"confirmed": 1, "skipped_local": 0}
    assert manual_bindings == {"ssd": {"id": "111", "url": "db-url"}}
    assert confirmed_rows == [{
        "name": "SSD Kingston",
        "onliner_id": "111",
        "api_name": "SSD Kingston 1TB",
        "score": 0.876,
    }]


def test_apply_validate_clean_db_result_does_not_bind_manual_confirmation():
    manual_bindings = {}
    confirmed_rows = []

    svc.apply_validate_clean_db_result(
        pd.DataFrame({"OnlinerID": ["111"]}, index=[5]),
        {
            "status": "confirm",
            "db_name": "",
            "score": 1.0,
            "reason": "manual_confirmed",
        },
        5,
        "SSD",
        "ssd",
        "111",
        manual_bindings,
        confirmed_rows,
        [],
        [],
        [],
    )

    assert manual_bindings == {}
    assert confirmed_rows == [{"name": "SSD", "onliner_id": "111", "api_name": "Локальная БД", "score": 1.0}]


def test_apply_validate_clean_db_result_clears_row_and_records_journal():
    df = pd.DataFrame({"OnlinerID": ["111"], "Ссылка": ["old-url"]}, index=[5])
    cleared_items = []
    journal_changes = []
    exact = {"id": "222", "name": "SSD exact"}

    deltas = svc.apply_validate_clean_db_result(
        df,
        {
            "status": "clear",
            "db_name": "Wrong DB name",
            "score": 0.1234,
            "reason": "db_id_name_mismatch",
            "exact_match": exact,
        },
        5,
        "SSD",
        "ssd",
        "111",
        {},
        [],
        [],
        cleared_items,
        journal_changes,
        clear_value=pd.NA,
    )

    assert deltas == {"confirmed": 0, "skipped_local": 0}
    assert pd.isna(df.at[5, "OnlinerID"])
    assert pd.isna(df.at[5, "Ссылка"])
    assert cleared_items == [(5, "SSD", "ssd", "111", "Wrong DB name", 0.123, "db_id_name_mismatch", exact)]
    assert journal_changes == [{
        "row_idx": 5,
        "name": "SSD",
        "old_onliner_id": "111",
        "old_url": "old-url",
        "new_onliner_id": "",
        "new_url": "",
        "reason": "validate_clean_db db_id_name_mismatch score=0.123",
    }]


def test_validation_confirmations_are_scoped_by_supplier():
    manual_bindings = {}
    for supplier, oid in (("IVEN", "111"), ("IVEN_zakaz", "222"), ("Tradex", "333"), ("N-Tech", "444")):
        svc.apply_validate_clean_api_result(
            pd.DataFrame({"OnlinerID": [oid]}, index=[0]),
            {
                "row_idx": 0,
                "name": "Одинаковый товар",
                "onliner_id": oid,
                "api_name": "Одинаковый товар Onliner",
                "api_url": "u" + oid,
                "score": 0.99,
                "reason": "exact",
                "record_confirm": True,
                "mutate_df_clear": False,
            },
            "same-product",
            manual_bindings,
            [],
            [],
            [],
            [],
            supplier_name=supplier,
        )

    assert manual_bindings["supplier:iven:same-product"]["id"] == "111"
    assert manual_bindings["supplier:iven_zakaz:same-product"]["id"] == "222"
    assert manual_bindings["supplier:tradex:same-product"]["id"] == "333"
    assert manual_bindings["supplier:n_tech:same-product"]["id"] == "444"


def test_validation_review_queue_keeps_same_name_separate_by_supplier():
    queue = {}
    cleared = [
        (0, "SSD Same", "ssd-same", "111", "Wrong", 0.1, "low", "IVEN"),
        (1, "SSD Same", "ssd-same", "222", "Wrong", 0.1, "low", "Tradex"),
    ]

    svc.populate_api_review_queue_for_cleared_items(
        cleared,
        queue,
        search_onliner_candidates=lambda *args, **kwargs: [{"id": "999", "name": "SSD Same"}],
        limit_cands=10,
    )

    assert set(queue) == {
        "supplier:iven:ssd-same",
        "supplier:tradex:ssd-same",
    }
    assert queue["supplier:iven:ssd-same"]["supplier"] == "IVEN"
    assert queue["supplier:tradex:ssd-same"]["supplier"] == "Tradex"
