"""Unit tests for bulk Onliner ID cleanup service."""

import pandas as pd

from price_mixer.services import bulk_id_cleanup as svc
from price_mixer.services.product_normalization import normalize_name_key


def memory_callbacks(df, state=None):
    state = state or {}
    state.setdefault("written_df", None)
    state.setdefault("json_written", False)
    state.setdefault("journals", [])
    state.setdefault("review_queue", {})
    state.setdefault("manual_bindings", {})
    state.setdefault("id_cache", {})

    def read_df(session_dir):
        return df.copy()

    def write_df(session_dir, out_df):
        state["written_df"] = out_df.copy()

    def write_json(out_df, path):
        state["json_written"] = True

    return state, read_df, write_df, write_json


def test_clear_invalid_onliner_ids_clears_matching_rows_and_related_caches(tmp_path):
    df = pd.DataFrame({
        "Название": ["SSD A", "SSD B", "Mouse"],
        "OnlinerID": ["111", "222", "333"],
        "Ссылка": ["u1", "u2", "u3"],
    })
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "manual_bindings": {normalize_name_key("SSD B"): {"id": "222"}, normalize_name_key("Mouse"): {"id": "333"}},
        "id_cache": {"art-SSD B": {"id": "222"}, "art-Mouse": {"id": "333"}},
    })

    result = svc.clear_invalid_onliner_ids(
        tmp_path,
        {"items": [{"onliner_id": "222"}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        build_item_category_key=lambda row: f"key:{row.get('Название', '')}",
        normalize_name_key=normalize_name_key,
        get_id_cache_key_for_name=lambda name: f"art-{name}",
    )

    assert result == {"status": "ok", "cleared": 1}
    assert list(state["written_df"]["OnlinerID"]) == ["111", "", "333"]
    assert list(state["written_df"]["Ссылка"]) == ["u1", "", "u3"]
    assert state["json_written"] is True
    assert state["manual_bindings"] == {normalize_name_key("Mouse"): {"id": "333"}}
    assert state["id_cache"] == {"art-Mouse": {"id": "333"}}


def test_clear_invalid_onliner_ids_returns_zero_without_items(tmp_path):
    state, read_df, write_df, write_json = memory_callbacks(pd.DataFrame())

    result = svc.clear_invalid_onliner_ids(
        tmp_path,
        {"items": []},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: {},
        save_id_cache=lambda payload: None,
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=lambda payload: None,
    )

    assert result == {"status": "ok", "cleared": 0}
    assert state["written_df"] is None


def test_clear_all_nonpc_onliner_ids_keeps_tgpc_and_other_suppliers(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("exists", encoding="utf-8")
    df = pd.DataFrame({
        "Поставщик": ["N-TECH", "NTECH", "Other"],
        "Название": ["Mouse", "TGPC Action 81872 A-X", "Keyboard"],
        "OnlinerID": ["111", "222", "333"],
        "Ссылка": ["u1", "u2", "u3"],
    })
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "review_queue": {normalize_name_key("Mouse"): {"queued": True}},
        "manual_bindings": {normalize_name_key("Mouse"): {"id": "111"}},
        "id_cache": {"art-Mouse": {"id": "111"}},
    })

    result = svc.clear_all_nonpc_onliner_ids(
        tmp_path,
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        is_tgpc_pc_name=lambda name: "TGPC" in name,
        normalize_name_key=normalize_name_key,
        get_id_cache_key_for_name=lambda name: f"art-{name}",
    )

    assert result["status"] == "ok"
    assert result["cleared"] == 1
    assert result["kept_pc"] == 1
    assert result["skipped_other_suppliers"] == 1
    assert pd.isna(state["written_df"].at[0, "OnlinerID"])
    assert state["written_df"].at[1, "OnlinerID"] == "222"
    assert state["written_df"].at[2, "OnlinerID"] == "333"
    assert state["review_queue"] == {}
    assert state["manual_bindings"] == {}
    assert state["id_cache"] == {}
    assert state["journals"][0]["action"] == "clear_all_nonpc_onliner_ids"


def test_clear_ntech_duplicate_onliner_ids_clears_duplicate_ids_only(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("exists", encoding="utf-8")
    df = pd.DataFrame({
        "Поставщик": ["N-TECH", "NTECH", "N-TECH", "Other"],
        "Название": ["SSD A", "SSD B", "Mouse", "Other duplicate"],
        "OnlinerID": ["111", "111", "222", "111"],
        "Ссылка": ["u1", "u2", "u3", "u4"],
    })
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "review_queue": {normalize_name_key("SSD A"): {"queued": True}, normalize_name_key("Mouse"): {"queued": True}},
        "manual_bindings": {normalize_name_key("SSD A"): {"id": "111"}, normalize_name_key("Mouse"): {"id": "222"}},
        "id_cache": {"art-SSD A": {"id": "111"}, "art-Mouse": {"id": "222"}},
    })

    result = svc.clear_ntech_duplicate_onliner_ids(
        tmp_path,
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        normalize_name_key=normalize_name_key,
        get_id_cache_key_for_name=lambda name: f"art-{name}",
    )

    assert result["status"] == "ok"
    assert result["cleared"] == 2
    assert result["duplicate_ids"] == 1
    assert pd.isna(state["written_df"].at[0, "OnlinerID"])
    assert pd.isna(state["written_df"].at[1, "OnlinerID"])
    assert state["written_df"].at[2, "OnlinerID"] == "222"
    assert state["written_df"].at[3, "OnlinerID"] == "111"
    assert state["review_queue"] == {normalize_name_key("Mouse"): {"queued": True}}
    assert state["manual_bindings"] == {normalize_name_key("Mouse"): {"id": "222"}}
    assert state["id_cache"] == {"art-Mouse": {"id": "222"}}
    assert state["journals"][0]["action"] == "clear_ntech_duplicate_onliner_ids"


def test_clear_ntech_duplicate_onliner_ids_reports_clean_state(tmp_path):
    (tmp_path / "consolidated_price.xlsx").write_text("exists", encoding="utf-8")
    df = pd.DataFrame({
        "Поставщик": ["N-TECH"],
        "Название": ["SSD"],
        "OnlinerID": ["111"],
    })
    _state, read_df, write_df, write_json = memory_callbacks(df)

    result = svc.clear_ntech_duplicate_onliner_ids(
        tmp_path,
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        append_id_change_journal=lambda entry: None,
        load_review_queue=lambda: {},
        save_review_queue=lambda payload: None,
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=lambda payload: None,
        load_id_cache=lambda: {},
        save_id_cache=lambda payload: None,
    )

    assert result == {
        "status": "ok",
        "cleared": 0,
        "duplicate_ids": 0,
        "message": "У N-Tech не найдено дублирующихся OnlinerID.",
    }
