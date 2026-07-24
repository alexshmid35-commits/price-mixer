"""Unit tests for autofill worker service helpers."""

import threading

import pandas as pd

from price_mixer.services.autofill_workers import (
    build_iven_id_index,
    lookup_iven_match,
    make_tgpc_pc_status,
    reject_iven_match_payload,
    run_iven_bridge_worker,
    run_tgpc_pc_worker,
    start_autofill_payload,
    status_payload,
)


def _name_key(value):
    return str(value or "").strip().lower().replace(" ", "")


def test_build_iven_id_index_skips_target_suppliers():
    df = pd.DataFrame([
        {"Название": "Kingston NV2", "OnlinerID": "123", "Ссылка": "u1", "Поставщик": "IVEN"},
        {"Название": "TGPC Action", "OnlinerID": "999", "Ссылка": "u2", "Поставщик": "TGPC"},
    ])

    index = build_iven_id_index(df, normalize_name_key=_name_key)

    assert index == {"kingstonnv2": {"id": "123", "name": "Kingston NV2", "url": "u1"}}


def test_lookup_iven_match_uses_best_score():
    result = lookup_iven_match(
        "Kingston NV2",
        {
            "a": {"id": "1", "name": "Other", "url": ""},
            "b": {"id": "2", "name": "Kingston NV2", "url": "u"},
        },
        calc_name_match=lambda left, right: {"score": 1.0 if right == "Kingston NV2" else 0.1},
        threshold=0.8,
    )

    assert result == {"id": "2", "name": "Kingston NV2", "url": "u", "score": 1.0}


def test_start_autofill_payload_initializes_status_and_starts_worker():
    status = {"running": False}
    started = []

    body = start_autofill_payload(
        "/tmp/session",
        cons_exists=True,
        status=status,
        lock=threading.RLock(),
        start_worker=lambda: started.append(True),
        status_factory=lambda: make_tgpc_pc_status(now_fn=lambda: 100),
    )

    assert body == {"status": "started"}
    assert status["running"] is True
    assert status["started_at"] == 100
    assert started == [True]


def test_start_autofill_payload_resets_stale_running_status():
    status = {"running": True, "started_at": 100, "message": "old"}
    started = []

    body = start_autofill_payload(
        "/tmp/session",
        cons_exists=True,
        status=status,
        lock=threading.RLock(),
        start_worker=lambda: started.append(True),
        status_factory=lambda: make_tgpc_pc_status(now_fn=lambda: 4000),
        now_fn=lambda: 4000,
        stale_after_sec=1800,
    )

    assert body == {"status": "started"}
    assert status["running"] is True
    assert status["started_at"] == 4000
    assert started == [True]


def test_run_tgpc_pc_worker_applies_confident_match():
    status = make_tgpc_pc_status(now_fn=lambda: 100)
    written = []
    journals = []
    df = pd.DataFrame([{
        "Название": "TGPC Action 81872 A-X",
        "OnlinerID": "",
        "Ссылка": "",
        "Поставщик": "TGPC",
    }])

    run_tgpc_pc_worker(
        "/tmp/session",
        status=status,
        lock=threading.RLock(),
        read_consolidated_df=lambda session_dir: df.copy(),
        load_app_settings=lambda: {"no_id_search": {"max_candidates": 20}},
        row_category=lambda row: "Системный блок",
        is_tgpc_pc_name=lambda name: "TGPC" in name,
        db_search_tgpc_pc_candidates=lambda name, limit=12: [{"id": "777", "url": "u", "name": "TGPC Action", "score": 0.97}],
        get_id_cache_key_for_name=_name_key,
        normalize_name_key=_name_key,
        load_id_cache=lambda: {},
        save_id_cache=lambda cache: written.append(("cache", cache)),
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=lambda bindings: written.append(("manual", bindings)),
        append_id_change_journal=journals.append,
        write_consolidated_df=lambda session_dir, out_df: written.append(("df", out_df.copy())),
        write_consolidated_json=lambda out_df, path: written.append(("json", str(path))),
        now_fn=lambda: 200,
    )

    assert status["running"] is False
    assert status["applied"] == 1
    assert status["skipped"] == 0
    assert journals[0]["changes"][0]["new_onliner_id"] == "777"
    saved_df = [item[1] for item in written if item[0] == "df"][0]
    assert saved_df.at[0, "OnlinerID"] == "777"


def test_run_tgpc_pc_worker_can_target_iven_pc_supplier_only():
    status = make_tgpc_pc_status(now_fn=lambda: 100)
    written = []
    journals = []
    df = pd.DataFrame([
        {
            "Название": "Компьютер IVEN BY Gaming Black 1809",
            "OnlinerID": "",
            "Ссылка": "",
            "Поставщик": "IVEN",
        },
        {
            "Название": "Компьютер IVEN BY Gaming Black 1809",
            "OnlinerID": "",
            "Ссылка": "",
            "Поставщик": "N-Tech",
        },
    ])

    run_tgpc_pc_worker(
        "/tmp/session",
        status=status,
        lock=threading.RLock(),
        read_consolidated_df=lambda session_dir: df.copy(),
        load_app_settings=lambda: {"no_id_search": {"max_candidates": 20}},
        row_category=lambda row: "Системный блок",
        is_tgpc_pc_name=lambda name: "IVEN" in name,
        db_search_tgpc_pc_candidates=lambda name, limit=12: [{"id": "888", "url": "u", "name": name, "score": 1.0}],
        get_id_cache_key_for_name=_name_key,
        normalize_name_key=_name_key,
        load_id_cache=lambda: {},
        save_id_cache=lambda cache: None,
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=lambda bindings: None,
        append_id_change_journal=journals.append,
        write_consolidated_df=lambda session_dir, out_df: written.append(out_df.copy()),
        write_consolidated_json=lambda out_df, path: None,
        target_supplier_names=["IVEN"],
        pc_label="IVEN ПЭВМ",
        now_fn=lambda: 200,
    )

    saved_df = written[0]
    assert status["applied"] == 1
    assert saved_df.at[0, "OnlinerID"] == "888"
    assert saved_df.at[1, "OnlinerID"] == ""
    assert journals[0]["changes"][0]["row_idx"] == 0


def test_run_tgpc_pc_worker_saves_extra_cache_keys_for_iven_pc():
    status = make_tgpc_pc_status(now_fn=lambda: 100)
    saved_caches = []
    saved_bindings = []
    df = pd.DataFrame([{
        "Название": "Компьютер Iven Office 201993 AMD Ryzen",
        "OnlinerID": "",
        "Ссылка": "",
        "Поставщик": "IVEN",
    }])

    run_tgpc_pc_worker(
        "/tmp/session",
        status=status,
        lock=threading.RLock(),
        read_consolidated_df=lambda session_dir: df.copy(),
        load_app_settings=lambda: {"no_id_search": {"max_candidates": 20}},
        row_category=lambda row: "Системный блок",
        is_tgpc_pc_name=lambda name: "Iven" in name,
        db_search_tgpc_pc_candidates=lambda name, limit=12: [{"id": "5137272", "url": "", "name": name, "score": 1.0}],
        get_id_cache_key_for_name=lambda name: "",
        normalize_name_key=_name_key,
        load_id_cache=lambda: {},
        save_id_cache=saved_caches.append,
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=saved_bindings.append,
        append_id_change_journal=lambda entry: None,
        write_consolidated_df=lambda session_dir, out_df: None,
        write_consolidated_json=lambda out_df, path: None,
        target_supplier_names=["IVEN"],
        pc_label="IVEN ПЭВМ",
        get_id_cache_keys_for_name=lambda name: ["iven_pc:201993", "iven_pc:office:201993"],
        get_manual_binding_keys_for_name=lambda name: [_name_key(name), "iven_pc:201993", "iven_pc:office:201993"],
        now_fn=lambda: 200,
    )

    assert saved_caches[0]["iven_pc:201993"]["id"] == "5137272"
    assert saved_caches[0]["iven_pc:office:201993"]["id"] == "5137272"
    assert saved_bindings[0]["supplier:iven:iven_pc:201993"]["id"] == "5137272"
    assert saved_bindings[0]["supplier:iven:iven_pc:office:201993"]["id"] == "5137272"
    assert saved_bindings[0]["supplier:iven:iven_pc:201993"]["suppliers"] == ["IVEN"]


def test_run_tgpc_pc_worker_does_not_autofill_duplicate_supplier_code_variants():
    status = make_tgpc_pc_status(now_fn=lambda: 100)
    written = []
    searched = []
    df = pd.DataFrame([
        {
            "Название": "Компьютер IVEN Gaming Black 181062 Core i5 / RTX 3060Ti",
            "OnlinerID": "",
            "Ссылка": "",
            "Поставщик": "IVEN",
        },
        {
            "Название": "Компьютер IVEN Gaming Black 181062 Core i5 / RTX 4060",
            "OnlinerID": "",
            "Ссылка": "",
            "Поставщик": "IVEN",
        },
    ])

    run_tgpc_pc_worker(
        "/tmp/session",
        status=status,
        lock=threading.RLock(),
        read_consolidated_df=lambda session_dir: df.copy(),
        load_app_settings=lambda: {"no_id_search": {"max_candidates": 20}},
        row_category=lambda row: "Системный блок",
        is_tgpc_pc_name=lambda name: "IVEN" in name,
        db_search_tgpc_pc_candidates=lambda name, limit=12: searched.append(name) or [{
            "id": "999",
            "url": "",
            "name": "Компьютер Iven Gaming Black 181062",
            "score": 1.0,
        }],
        get_id_cache_key_for_name=_name_key,
        normalize_name_key=_name_key,
        load_id_cache=lambda: {},
        save_id_cache=lambda cache: None,
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=lambda bindings: None,
        append_id_change_journal=lambda entry: None,
        write_consolidated_df=lambda session_dir, out_df: written.append(out_df.copy()),
        write_consolidated_json=lambda out_df, path: None,
        target_supplier_names=["IVEN"],
        get_match_identity_for_name=lambda name: "181062",
        now_fn=lambda: 200,
    )

    assert searched == []
    assert status["applied"] == 0
    assert status["skipped"] == 2
    assert status["items"][0]["status"] == "ambiguous_identity"
    assert written[0]["OnlinerID"].tolist() == ["", ""]


def test_run_iven_bridge_worker_exact_match_applies_id():
    status = {"running": True}
    written = []
    journals = []
    df = pd.DataFrame([{
        "Название": "Kingston NV2",
        "OnlinerID": "",
        "Ссылка": "",
        "Поставщик": "N-Tech",
    }])

    run_iven_bridge_worker(
        "/tmp/session",
        status=status,
        lock=threading.RLock(),
        db_stats=lambda: {"total_products": 10, "total_names": 10},
        read_consolidated_df=lambda session_dir: df.copy(),
        db_populate_from_df=lambda *args, **kwargs: None,
        db_find_id_for_name=lambda name, threshold=0.4, allow_b2b=False: {
            "id": "123",
            "url": "u",
            "score": 1.0,
            "source": "db_exact",
            "name": "Kingston NV2",
        },
        db_find_top_candidates=lambda *args, **kwargs: [],
        is_tgpc_pc_name=lambda name: False,
        normalize_name_key=_name_key,
        get_id_cache_key_for_name=_name_key,
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=lambda bindings: written.append(("manual", bindings)),
        load_id_cache=lambda: {},
        save_id_cache=lambda cache: written.append(("cache", cache)),
        append_id_change_journal=journals.append,
        write_consolidated_df=lambda session_dir, out_df: written.append(("df", out_df.copy())),
        write_consolidated_json=lambda out_df, path: None,
        now_fn=lambda: 300,
    )

    assert status["running"] is False
    assert status["applied"] == 1
    assert status["matches"][0]["id"] == "123"
    assert journals[0]["changes"][0]["reason"] == "db_bridge db_exact score=1.0"


def test_reject_iven_match_clears_by_row_and_manual_binding():
    df = pd.DataFrame([{"Название": "Kingston NV2", "OnlinerID": "123", "Ссылка": "u"}])
    saved = []

    body = reject_iven_match_payload(
        "/tmp/session",
        {"name": "Kingston NV2", "row_idx": 0},
        read_consolidated_df=lambda session_dir: df.copy(),
        write_consolidated_df=lambda session_dir, out_df: saved.append(out_df.copy()),
        write_consolidated_json=lambda out_df, path: None,
        normalize_name_key=_name_key,
        load_manual_id_bindings=lambda: {"kingstonnv2": {"id": "123", "url": "u"}},
        save_manual_id_bindings=lambda bindings: saved.append(bindings),
        blank_id_value="",
    )

    assert body == {"status": "ok", "cleared": 1}
    saved_df = next(item for item in saved if hasattr(item, "at"))
    saved_bindings = next(item for item in saved if isinstance(item, dict))
    assert saved_df.at[0, "OnlinerID"] == ""
    assert saved_bindings == {}


def test_status_payload_copies_items():
    status = {"running": False, "items": [{"x": 1}]}

    payload = status_payload(status, threading.RLock())

    assert payload == {"running": False, "items": [{"x": 1}]}
    assert payload["items"] is not status["items"]
