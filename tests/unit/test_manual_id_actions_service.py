"""Unit tests for manual Onliner ID actions."""

import pandas as pd

from price_mixer.services import manual_id_actions as svc
from price_mixer.services.product_normalization import normalize_name_key


def memory_callbacks(df, state=None):
    state = state or {}
    state.setdefault("written_df", None)
    state.setdefault("json_written", False)
    state.setdefault("id_cache", {})
    state.setdefault("manual_bindings", {})
    state.setdefault("review_queue", {})
    state.setdefault("journals", [])
    state.setdefault("saved_journal", None)

    def read_df(session_dir):
        return df.copy()

    def write_df(session_dir, out_df):
        state["written_df"] = out_df.copy()

    def write_json(out_df, path):
        state["json_written"] = True

    return state, read_df, write_df, write_json


def sanitize(cache):
    return cache if isinstance(cache, dict) else {}, False


def test_confirm_manual_id_batch_updates_row_bindings_queue_and_journal(tmp_path):
    df = pd.DataFrame({
        "Название": ["SSD", "Mouse"],
        "OnlinerID": ["", "222"],
        "Ссылка": ["", "u2"],
    })
    name_key = normalize_name_key("SSD")
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "review_queue": {name_key: {"queued": True}},
    })

    result = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "test", "items": [{"name": "SSD", "onliner_id": "111", "row_idx": 0}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        fetch_onliner_product_info=lambda oid, **kwargs: {"url": "https://catalog/111"},
        normalize_name_key_func=normalize_name_key,
    )

    assert result == {"status": "ok", "updated": 1}
    assert state["written_df"].at[0, "OnlinerID"] == "111"
    assert state["written_df"].at[0, "Ссылка"] == "https://catalog/111"
    assert state["manual_bindings"] == {name_key: {"id": "111", "url": "https://catalog/111"}}
    assert state["review_queue"] == {}
    assert state["journals"][0]["action"] == "manual_id_confirm_batch"
    assert state["json_written"] is True


def test_confirm_manual_id_batch_updates_current_row_by_name_without_row_idx(tmp_path):
    df = pd.DataFrame({
        "Название": ["Cable A", "Cable B"],
        "OnlinerID": ["", ""],
        "Ссылка": ["", ""],
    })
    name_key = normalize_name_key("Cable B")
    state, read_df, write_df, write_json = memory_callbacks(df)

    result = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "test", "items": [{"name": "Cable B", "onliner_id": "333", "url": "https://catalog/333"}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )

    assert result == {"status": "ok", "updated": 1}
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert state["written_df"].at[1, "OnlinerID"] == "333"
    assert state["written_df"].at[1, "Ссылка"] == "https://catalog/333"
    assert state["manual_bindings"] == {name_key: {"id": "333", "url": "https://catalog/333"}}
    assert state["json_written"] is True


def test_confirm_manual_id_batch_scopes_binding_to_row_supplier(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN", "IVEN_zakaz"],
        "Название": ["Ноутбук Lenovo A", "Ноутбук Lenovo A"],
        "OnlinerID": ["", ""],
        "Ссылка": ["", ""],
    })
    name_key = normalize_name_key("Ноутбук Lenovo A")
    state, read_df, write_df, write_json = memory_callbacks(df)

    result = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "inline_noid_picker", "items": [{"name": "Ноутбук Lenovo A", "supplier": "IVEN_zakaz", "onliner_id": "777", "row_idx": 1}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )

    assert result == {"status": "ok", "updated": 1}
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert state["written_df"].at[1, "OnlinerID"] == "777"
    assert state["manual_bindings"] == {"supplier:iven_zakaz:" + name_key: {"id": "777", "url": "", "suppliers": ["IVEN_zakaz"]}}


def test_confirm_manual_id_batch_keeps_same_name_separate_by_supplier(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN", "IVEN_zakaz"],
        "Название": ["Ноутбук Lenovo A", "Ноутбук Lenovo A"],
        "OnlinerID": ["", ""],
        "Ссылка": ["", ""],
    })
    name_key = normalize_name_key("Ноутбук Lenovo A")
    state, read_df, write_df, write_json = memory_callbacks(df)

    first = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "inline_noid_picker", "items": [{"name": "Ноутбук Lenovo A", "supplier": "IVEN", "onliner_id": "111", "row_idx": 0}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )
    second = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "inline_noid_picker", "items": [{"name": "Ноутбук Lenovo A", "supplier": "IVEN_zakaz", "onliner_id": "222", "row_idx": 1}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )

    assert first == {"status": "ok", "updated": 1}
    assert second == {"status": "ok", "updated": 1}
    assert state["manual_bindings"]["supplier:iven:" + name_key]["id"] == "111"
    assert state["manual_bindings"]["supplier:iven_zakaz:" + name_key]["id"] == "222"


def test_confirm_manual_id_batch_blocks_duplicate_id_for_distinct_name(tmp_path):
    df = pd.DataFrame({
        "Название": ["SSD A", "SSD B"],
        "OnlinerID": ["111", ""],
        "Ссылка": ["u1", ""],
    })
    state, read_df, write_df, write_json = memory_callbacks(df)

    result, status = svc.confirm_manual_id_batch(
        tmp_path,
        {"items": [{"name": "SSD B", "onliner_id": "111", "row_idx": 1}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )

    assert status == 409
    assert result["code"] == "duplicate_id_assigned"
    assert result["updated"] == 0
    assert result["blocked"][0]["conflicts"][0]["name"] == "SSD A"
    assert "SSD A" in result["message"]
    assert state["written_df"].at[1, "OnlinerID"] == ""
    assert state["journals"] == []


def test_confirm_manual_id_batch_allows_duplicate_id_for_same_strong_model(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN", "IVEN"],
        "Название": [
            "Кулер ID-Cooling DK-03 (ID-CPU-DK-03), 100W",
            "Кулер ID-Cooling DK-03 (ID-CPU-DK-03), 100W (LGA1700 Ready)",
        ],
        "OnlinerID": ["", "998213"],
        "Ссылка": ["", ""],
    })
    state, read_df, write_df, write_json = memory_callbacks(df)

    result = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "inline_noid_picker", "items": [{"name": df.at[0, "Название"], "supplier": "IVEN", "onliner_id": "998213", "row_idx": 0}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )

    assert result == {"status": "ok", "updated": 1}
    assert state["written_df"].at[0, "OnlinerID"] == "998213"


def test_confirm_manual_id_batch_allows_durable_binding_for_same_compact_parenthesized_model(tmp_path):
    current_name = "Видеокарта AMD Radeon OCPC RX 550 (OCVARX550G4SE) 4GB GDDR5 DVI+HDMI+DP"
    old_name = "видеокарта amd radeon ocpc rx550 se (ocvarx550g4se) 4gb gddr5 dvi+hdmi+dp"
    df = pd.DataFrame({
        "Поставщик": ["N-Tech"],
        "Название": [current_name],
        "OnlinerID": [""],
        "Ссылка": [""],
    })
    binding_key = "supplier:n_tech:" + normalize_name_key(old_name)
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "manual_bindings": {
            binding_key: {"id": "5050403", "url": "", "suppliers": ["N-Tech"]},
        },
    })

    result = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "inline_noid_picker", "items": [{
            "name": current_name,
            "supplier": "N-Tech",
            "onliner_id": "5050403",
            "row_idx": 0,
        }]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )

    assert result == {"status": "ok", "updated": 1}
    assert state["written_df"].at[0, "OnlinerID"] == "5050403"


def test_compact_parenthesized_models_do_not_match_when_code_differs():
    assert svc._same_strong_model(
        "Видеокарта OCPC RX 550 (OCVARX550G4SE)",
        "Видеокарта OCPC RX 550 (OCVARX550G8SE)",
    ) is False


def test_reject_iven_match_clears_row_and_manual_binding(tmp_path):
    df = pd.DataFrame([{
        "Поставщик": "IVEN",
        "Название": "Kingston NV2",
        "OnlinerID": "123",
        "Ссылка": "u",
    }])
    name_key = normalize_name_key("Kingston NV2")
    binding_key = "supplier:iven:" + name_key
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "manual_bindings": {
            binding_key: {"id": "123", "url": "u", "suppliers": ["IVEN"]},
        },
    })

    result = svc.reject_iven_match_payload(
        tmp_path,
        {"name": "Kingston NV2", "supplier": "IVEN", "row_idx": 0},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        normalize_name_key=normalize_name_key,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        blank_id_value="",
    )

    assert result == {"status": "ok", "cleared": 1}
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert state["written_df"].at[0, "Ссылка"] == ""
    assert state["manual_bindings"] == {}


def test_confirm_manual_id_batch_still_blocks_duplicate_id_for_different_model(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN", "IVEN"],
        "Название": [
            "Кулер Formula 110W",
            "Кулер ID-Cooling DK-03 (ID-CPU-DK-03), 100W (LGA1700 Ready)",
        ],
        "OnlinerID": ["", "998213"],
        "Ссылка": ["", ""],
    })
    state, read_df, write_df, write_json = memory_callbacks(df)

    result, status = svc.confirm_manual_id_batch(
        tmp_path,
        {"source": "inline_noid_picker", "items": [{"name": df.at[0, "Название"], "supplier": "IVEN", "onliner_id": "998213", "row_idx": 0}]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
    )

    assert status == 409
    assert result["code"] == "duplicate_id_assigned"
    assert "ID-Cooling DK-03" in result["message"]
    assert state["written_df"].at[0, "OnlinerID"] == ""


def test_clear_manual_id_clears_row_blocks_binding_and_cleans_cache_queue(tmp_path):
    df = pd.DataFrame({
        "Название": ["SSD"],
        "OnlinerID": ["111"],
        "Ссылка": ["u1"],
    })
    name_key = normalize_name_key("SSD")
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "id_cache": {"art-SSD": {"id": "111"}},
        "manual_bindings": {name_key: {"id": "111", "url": "u1"}},
        "review_queue": {name_key: {"queued": True}},
    })

    result = svc.clear_manual_id(
        tmp_path,
        {"source": "test", "item": {"name": "SSD", "row_idx": 0}},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: state["id_cache"],
        save_id_cache=lambda payload: state.update(id_cache=payload.copy()),
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: state["review_queue"],
        save_review_queue=lambda payload: state.update(review_queue=payload.copy()),
        append_id_change_journal=lambda entry: state["journals"].append(entry),
        normalize_name_key_func=normalize_name_key,
        get_id_cache_key_for_name=lambda name: f"art-{name}",
    )

    assert result == {"status": "ok", "cleared": 1}
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert state["written_df"].at[0, "Ссылка"] == ""
    assert state["id_cache"] == {}
    assert state["manual_bindings"] == {name_key: {"id": "", "url": "", "blocked": True}}
    assert state["review_queue"] == {}
    assert state["journals"][0]["action"] == "manual_id_clear"


def test_clear_manual_id_validates_payload_and_row(tmp_path):
    df = pd.DataFrame({"Название": ["SSD"], "OnlinerID": ["111"]})
    state, read_df, write_df, write_json = memory_callbacks(df)

    bad_payload, bad_status = svc.clear_manual_id(
        tmp_path,
        {"item": {"name": "SSD"}},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: {},
        save_id_cache=lambda payload: None,
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: {},
        save_manual_id_bindings=lambda payload: None,
        load_review_queue=lambda: {},
        save_review_queue=lambda payload: None,
        append_id_change_journal=lambda entry: None,
    )

    assert bad_status == 400
    assert "row_idx" in bad_payload["message"]
    assert state["written_df"] is None


def test_rollback_last_manual_id_change_restores_last_matching_session(tmp_path):
    df = pd.DataFrame({
        "Название": ["SSD", "Mouse"],
        "OnlinerID": ["111", "222"],
        "Ссылка": ["new", "u2"],
    })
    rows = [
        {"session_dir": "/other", "changes": [{"row_idx": 0, "old_onliner_id": "999", "old_url": "other"}]},
        {"session_dir": str(tmp_path), "changes": [{"row_idx": 0, "old_onliner_id": "", "old_url": ""}]},
    ]
    state, read_df, write_df, write_json = memory_callbacks(df)

    result = svc.rollback_last_manual_id_change(
        tmp_path,
        load_id_change_journal=lambda: list(rows),
        save_id_change_journal=lambda payload: state.update(saved_journal=payload),
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
    )

    assert result == {"status": "ok", "restored": 1}
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert state["written_df"].at[0, "Ссылка"] == ""
    assert state["saved_journal"] == [rows[0]]


def test_confirm_uses_name_and_supplier_when_report_row_index_is_stale(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN", "Tradex"],
        "Название": ["Товар A", "Товар B"],
        "OnlinerID": ["", ""],
        "Ссылка": ["", ""],
    })
    state, read_df, write_df, write_json = memory_callbacks(df)

    result = svc.confirm_manual_id_batch(
        tmp_path,
        {"items": [{
            "name": "Товар B",
            "supplier": "Tradex",
            "onliner_id": "222",
            "row_idx": 0,
        }]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: {},
        save_id_cache=lambda payload: None,
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: {},
        save_review_queue=lambda payload: None,
        append_id_change_journal=lambda entry: state["journals"].append(entry),
    )

    assert result == {"status": "ok", "updated": 1}
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert state["written_df"].at[1, "OnlinerID"] == "222"
    key = "supplier:tradex:" + normalize_name_key("Товар B")
    assert state["manual_bindings"][key]["id"] == "222"


def test_confirm_rejects_stale_report_item_instead_of_writing_wrong_row(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN"],
        "Название": ["Новый товар после загрузки"],
        "OnlinerID": [""],
        "Ссылка": [""],
    })
    state, read_df, write_df, write_json = memory_callbacks(df)

    body, status = svc.confirm_manual_id_batch(
        tmp_path,
        {"items": [{
            "name": "Старый товар из отчёта",
            "supplier": "IVEN",
            "onliner_id": "111",
            "row_idx": 0,
        }]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: {},
        save_id_cache=lambda payload: None,
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: {},
        save_review_queue=lambda payload: None,
        append_id_change_journal=lambda entry: state["journals"].append(entry),
    )

    assert status == 409
    assert body["code"] == "stale_price_row"
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert state["manual_bindings"] == {}


def test_rollback_removes_new_durable_binding_so_it_cannot_return_on_reload(tmp_path):
    name_key = normalize_name_key("SSD")
    binding_key = "supplier:tradex:" + name_key
    df = pd.DataFrame({
        "Поставщик": ["Tradex"],
        "Название": ["SSD"],
        "OnlinerID": ["111"],
        "Ссылка": ["new"],
    })
    rows = [{
        "session_dir": str(tmp_path),
        "changes": [{
            "row_idx": 0,
            "name": "SSD",
            "supplier": "Tradex",
            "binding_key": binding_key,
            "old_manual_binding": {},
            "old_onliner_id": "",
            "old_url": "",
        }],
    }]
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "manual_bindings": {
            binding_key: {"id": "111", "url": "new", "suppliers": ["Tradex"]},
        },
    })

    result = svc.rollback_last_manual_id_change(
        tmp_path,
        load_id_change_journal=lambda: list(rows),
        save_id_change_journal=lambda payload: state.update(saved_journal=payload),
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
    )

    assert result == {"status": "ok", "restored": 1}
    assert state["written_df"].at[0, "OnlinerID"] == ""
    assert binding_key not in state["manual_bindings"]


def test_confirm_blocks_hidden_duplicate_in_same_supplier_durable_cache(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN"],
        "Название": ["Новый другой товар"],
        "OnlinerID": [""],
        "Ссылка": [""],
    })
    old_key = "supplier:iven:" + normalize_name_key("Старый товар вне прайса")
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "manual_bindings": {
            old_key: {"id": "111", "url": "u", "suppliers": ["IVEN"]},
        },
    })

    body, status = svc.confirm_manual_id_batch(
        tmp_path,
        {"items": [{
            "name": "Новый другой товар",
            "supplier": "IVEN",
            "onliner_id": "111",
            "row_idx": 0,
        }]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: {},
        save_id_cache=lambda payload: None,
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: {},
        save_review_queue=lambda payload: None,
        append_id_change_journal=lambda entry: None,
    )

    assert status == 409
    assert body["code"] == "duplicate_id_assigned"
    assert body["blocked"][0]["conflicts"][0]["source"] == "durable_binding"
    assert state["written_df"].at[0, "OnlinerID"] == ""


def test_confirm_allows_same_id_already_bound_to_another_supplier(tmp_path):
    df = pd.DataFrame({
        "Поставщик": ["IVEN"],
        "Название": ["Товар IVEN"],
        "OnlinerID": [""],
        "Ссылка": [""],
    })
    tradex_key = "supplier:tradex:" + normalize_name_key("Товар Tradex")
    state, read_df, write_df, write_json = memory_callbacks(df, {
        "manual_bindings": {
            tradex_key: {"id": "111", "url": "u", "suppliers": ["Tradex"]},
        },
    })

    result = svc.confirm_manual_id_batch(
        tmp_path,
        {"items": [{
            "name": "Товар IVEN",
            "supplier": "IVEN",
            "onliner_id": "111",
            "row_idx": 0,
        }]},
        read_consolidated_df=read_df,
        write_consolidated_df=write_df,
        write_consolidated_json=write_json,
        load_id_cache=lambda: {},
        save_id_cache=lambda payload: None,
        sanitize_id_cache=sanitize,
        load_manual_id_bindings=lambda: state["manual_bindings"],
        save_manual_id_bindings=lambda payload: state.update(manual_bindings=payload.copy()),
        load_review_queue=lambda: {},
        save_review_queue=lambda payload: None,
        append_id_change_journal=lambda entry: None,
    )

    assert result == {"status": "ok", "updated": 1}
    assert state["written_df"].at[0, "OnlinerID"] == "111"
    assert state["manual_bindings"]["supplier:iven:" + normalize_name_key("Товар IVEN")]["id"] == "111"


def test_rollback_last_manual_id_change_reports_missing_journal(tmp_path):
    result, status = svc.rollback_last_manual_id_change(
        tmp_path,
        load_id_change_journal=lambda: [],
        save_id_change_journal=lambda payload: None,
        read_consolidated_df=lambda session_dir: pd.DataFrame(),
        write_consolidated_df=lambda session_dir, df: None,
        write_consolidated_json=lambda df, path: None,
    )

    assert status == 400
    assert result["message"] == "Журнал замен пуст"
