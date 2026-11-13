import threading

import pandas as pd
import pytest

import app as app_module
from price_mixer.services.autofill_workers import make_pc_autofill_status, run_tgpc_pc_worker
from price_mixer.services.experimental_noid import is_separate_pevm_row
from price_mixer.services.export_pipeline import prepare_consolidated_for_export
from price_mixer.services.id_reporting import build_id_replace_candidates_payload
from price_mixer.services.product_matching import calc_name_match
from price_mixer.services.product_normalization import infer_category, normalize_name_key
from price_mixer.services.tradex_pc import (
    extract_tradex_pc_code, find_tradex_pc_candidates, is_tradex_pc_name,
)


@pytest.mark.parametrize("name,code", [
    ("WOUK Game N000021BK", "N000021BK"),
    ("WOUK Multi N000001WH", "N000001WH"),
    ("Компьютер WOUK Night L000017BK", "L000017BK"),
    ("WOUK Pulse E71390BK", "E71390BK"),
    ("[Компьютеры] Wouk Game n000021bk", "N000021BK"),
])
def test_wouk_desktops_are_detected_without_losing_sku_prefix_or_color(name, code):
    assert is_tradex_pc_name(name)
    assert extract_tradex_pc_code(name) == code
    assert infer_category(name) == "Системный блок"


@pytest.mark.parametrize("name", ["Корпус WOUK Game N000021BK", "Компьютер IVEN BY Gaming 12345", "Видеокарта RTX 5060"])
def test_other_hardware_does_not_become_tradex_pc(name):
    assert not is_tradex_pc_name(name)
    assert extract_tradex_pc_code(name) == ""


@pytest.mark.parametrize("candidate", [
    "Компьютер WOUK Game N000021WH", "Компьютер WOUK Night L000021BK",
    "Компьютер WOUK Game N000020BK", "Компьютер WOUK Game N0000210BK",
    "Компьютер WOUK Game N000021BK-REV2",
    "Компьютер WOUK Game", "Компьютер IVEN N000021BK",
])
def test_generic_matching_rejects_similar_desktops(candidate):
    result = calc_name_match("WOUK Game N000021BK", candidate)
    assert result["score"] < 0.2
    assert result["match"] is False


def test_exact_code_candidates_are_deduplicated_and_ambiguous_ids_are_not_confident():
    items = [
        {"id": "1", "name": "Компьютер WOUK Game N000021BK", "url": "u1"},
        {"id": "1", "name": "WOUK Game N000021BK", "url": "u1"},
        {"id": "2", "name": "WOUK Game N000021WH", "url": "u2"},
    ]
    found = find_tradex_pc_candidates("WOUK Game N000021BK", search=lambda _: {"items": items})
    assert len(found) == 1
    assert found[0]["score"] == 1.0
    assert found[0]["id"] == "1"
    items.append({"id": "3", "name": "WOUK Game N000021BK"})
    found = find_tradex_pc_candidates("WOUK Game N000021BK", search=lambda _: {"items": items})
    assert len(found) == 2
    assert all(item["score"] < 0.92 for item in found)


def test_old_name_index_alias_cannot_assign_an_id_for_a_different_current_model():
    assert find_tradex_pc_candidates(
        "WOUK Game N000021BK",
        search=lambda _: {"items": [{"id": "1", "name": "WOUK Game N000021BK"}]},
        get_product_by_id=lambda _: {"name": "Компьютер WOUK Night L000021BK"},
    ) == []


def test_fast_picker_final_payload_accepts_exact_sku_and_rejects_wrong_high_scores():
    exact = {"id": "1", "name": "Компьютер WOUK Game N000021BK", "score": 1.0}
    wrong = {"id": "2", "name": "Компьютер WOUK Night L000021BK", "score": 1.0}
    result = build_id_replace_candidates_payload(
        {"name": "WOUK Game N000021BK", "category": "Компьютеры"},
        specialized_candidates=lambda *_a, **_kw: [exact],
        db_find_top_candidates=lambda *_a, **_kw: [wrong],
        score_candidate=calc_name_match, candidate_allowed=app_module._strict_candidate_allowed,
    )
    assert [item["id"] for item in result["items"]] == ["1"]
    assert result["items"][0]["score"] == 1.0
    assert result["items"][0]["reason"] == "wouk_code_exact"


def test_manual_picker_dispatches_to_tradex_and_badges_only_count_its_rows(monkeypatch):
    monkeypatch.setattr(app_module, "db_search_tradex_pc_candidates", lambda name, limit: [{"id": "1", "name": name}])
    # The runtime is immutable; use its dependencies with a fresh test instance.
    from dataclasses import replace
    runtime = replace(app_module._get_manual_id_search_runtime(), search_tradex_pc_candidates=app_module.db_search_tradex_pc_candidates)
    assert runtime.candidates("WOUK Game N000021BK", category="WOUK")[0]["id"] == "1"
    rows = [
        ["", "WOUK Game N000021BK", 100, "Tradex", 24, 2, 100, 100, 0, "Компьютеры"],
        ["2", "WOUK Game N000022BK", 100, "Tradex", 24, 2, 100, 100, 1, "Компьютеры"],
        ["", "WOUK Game N000021BK", 100, "IVEN", 24, 2, 100, 100, 2, "Компьютеры"],
    ]
    assert app_module._main_table_badge_counts(rows)["tradex-pc"] == 1
    assert is_separate_pevm_row(
        {"Поставщик": "Tradex", "Название": "WOUK Game N000021BK"},
        canonical_supplier_name=lambda value: value, is_ntech_pevm_name=lambda _: False, is_iven_pevm_name=lambda _: False,
    )


def test_old_wouk_category_is_repaired_and_only_assigned_ids_reach_export(monkeypatch):
    monkeypatch.setattr(app_module, "db_get_categories_by_ids", lambda _: {})
    frame = pd.DataFrame({
        "Название": ["WOUK Game N000021BK", "WOUK Multi N000001WH"],
        "Поставщик": ["Tradex", "Tradex"], "OnlinerID": ["123", ""],
        "Категория": ["WOUK", "WOUK"], "Цена": [100, 200],
    })
    corrected = app_module.ensure_category_column(frame, overrides={})
    assert corrected["Категория"].tolist() == ["Компьютеры", "Компьютеры"]
    exported, _ = prepare_consolidated_for_export(
        "session", {"export": {"allowed_categories": ["Компьютеры"], "include_without_id": False}},
        read_consolidated_df=lambda _: corrected,
        apply_visibility_filter=lambda df, _: df, has_consolidated_data=lambda _: True,
    )
    assert exported["OnlinerID"].tolist() == ["123"]


@pytest.mark.parametrize("candidates,expected", [([], 0), ([{"id": "1", "name": "WOUK Game N000021BK", "score": 1.0}], 1), ([{"id": "1", "score": 0.90}], 0)])
def test_pc_worker_keeps_missing_ids_and_only_updates_tradex(candidates, expected):
    name = "WOUK Game N000021BK"
    df = pd.DataFrame({
        "Название": [name] * 3, "OnlinerID": ["", "", "already-set"],
        "Поставщик": ["Tradex", "IVEN", "Tradex"], "Ссылка": [""] * 3,
    })
    saved = {}
    status = make_pc_autofill_status()
    run_tgpc_pc_worker(
        "session", status=status, lock=threading.RLock(),
        read_consolidated_df=lambda _: df.copy(), load_app_settings=lambda: {},
        row_category=lambda _: "Компьютеры", is_tgpc_pc_name=is_tradex_pc_name,
        db_search_tgpc_pc_candidates=lambda *a, **kw: candidates,
        get_id_cache_key_for_name=lambda _: "shared", get_id_cache_keys_for_name=lambda _: [],
        normalize_name_key=normalize_name_key,
        load_id_cache=lambda: {}, save_id_cache=lambda value: saved.update(cache=value),
        load_manual_id_bindings=lambda: {}, save_manual_id_bindings=lambda value: saved.update(bindings=value),
        append_id_change_journal=lambda _: None,
        write_consolidated_df=lambda _, value: saved.update(frame=value), write_consolidated_json=lambda *_: None,
        target_supplier_names=["Tradex"], pc_label="Компьютеры Tradex",
        get_match_identity_for_name=extract_tradex_pc_code,
    )
    assert status["total"] == 1
    assert status["applied"] == expected
    assert saved["frame"]["OnlinerID"].tolist() == (["1", "", "already-set"] if expected else ["", "", "already-set"])
    assert saved["cache"] == {}
    assert all(key.startswith("supplier:tradex:") for key in saved["bindings"])
