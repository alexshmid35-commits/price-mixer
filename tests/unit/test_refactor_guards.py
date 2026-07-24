"""Regression tests for refactor boundary fixes."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from flask import session

import app as app_module
from price_mixer.services import processing_pipeline
from price_mixer.services.export_stats import (
    export_category_counts_from_json_rows,
    export_row_count_from_json_rows,
)
from price_mixer.web_helpers import active_session_dir, basic_auth_matches, resolve_session_dir


def test_b2b_client_imports_package_config():
    module = importlib.import_module("price_mixer.clients.onliner_b2b")
    client = module.OnlinerB2BClient(
        settings={
            "base_url": "https://example.test",
            "price_api_base_url": "https://price.example.test",
            "token_url": "https://auth.example.test/token",
            "client_id": "id",
            "client_secret": "secret",
        }
    )

    assert client.base_url == "https://example.test"
    assert client.token_url == "https://auth.example.test/token"


def test_active_session_dir_uses_session_id_only(monkeypatch, tmp_path):
    session_dir = tmp_path / "abc12345"
    session_dir.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path)

    with app_module.app.test_request_context("/"):
        session["session_id"] = "abc12345"
        session["session_dir"] = "/tmp/should-not-be-used"
        session["output_path"] = "/tmp/should-not-be-used.xlsx"

        assert app_module.get_active_session_dir() == str(session_dir.resolve())
        assert "session_dir" not in session
        assert "output_path" not in session


def test_web_helper_resolves_only_valid_session_ids(tmp_path):
    valid = tmp_path / "abc12345"
    valid.mkdir()

    assert resolve_session_dir(tmp_path, "abc12345") == valid.resolve()
    assert resolve_session_dir(tmp_path, "../abc12345") is None
    assert resolve_session_dir(tmp_path, "not valid") is None


def test_web_helper_active_session_dir_scrubs_mapping(tmp_path):
    session_dir = tmp_path / "feedbeef"
    session_dir.mkdir()
    session_data = {
        "session_id": "feedbeef",
        "session_dir": "/tmp/old",
        "output_path": "/tmp/old.xlsx",
    }

    assert active_session_dir(tmp_path, session_data) == session_dir.resolve()
    assert session_data == {"session_id": "feedbeef"}


def test_basic_auth_matches_expected_credentials():
    good = SimpleNamespace(username="admin", password="secret")
    bad = SimpleNamespace(username="admin", password="wrong")

    assert basic_auth_matches(good, "admin", "secret")
    assert not basic_auth_matches(bad, "admin", "secret")
    assert not basic_auth_matches(None, "admin", "secret")


def test_all_onliner_reparse_items_skip_already_categorized_ids(monkeypatch):
    rows = [
        ["111", "SSD A", "120", "N-Tech", "", "", "", "", 0, "SSD"],
        ["111", "SSD A duplicate", "121", "IVEN", "", "", "", "", 1, "SSD"],
        ["222", "Кронштейн B", "33", "Tradex", "", "", "", "", 2, "Кронштейны"],
        ["333", "Unknown C", "44", "Tradex", "", "", "", "", 3, "Требует сортировки · родитель: Кабели"],
        ["", "No ID", "10", "Tradex", "", "", "", "", 3, "Кабели и переходники"],
    ]
    monkeypatch.setattr(app_module, "get_active_session_dir", lambda: "/tmp/session")
    monkeypatch.setattr(app_module, "_correct_consolidated_json_rows", lambda session_dir, apply_visibility=True: rows)
    monkeypatch.setattr(app_module, "db_get_categories_by_ids", lambda ids: {"111": "SSD", "333": "Кабели"})

    assert app_module._all_onliner_reparse_items() == [
        {"onliner_id": "222", "name": "Кронштейн B", "parent_category": "Кронштейны", "strict_api": True},
        {
            "onliner_id": "333",
            "name": "Unknown C",
            "parent_category": "Требует сортировки · родитель: Кабели",
            "strict_api": True,
        },
    ]


def test_sorting_reparse_db_write_clears_corrected_rows_cache(monkeypatch):
    app_module.CORRECTED_JSON_ROWS_CACHE["x"] = [["cached"]]
    monkeypatch.setattr(app_module, "_onliner_db_update_categories", lambda results: 1)

    assert app_module._write_sorting_reparse_results_to_db([{"onliner_id": "1", "category": "SSD"}]) == 1
    assert app_module.CORRECTED_JSON_ROWS_CACHE == {}


def test_sorting_reparse_service_is_not_restarted_when_healthy(monkeypatch):
    monkeypatch.setattr(app_module, "_sorting_reparse_service_healthy", lambda timeout=1.0: True)

    def unexpected_launch():
        raise AssertionError("Healthy parser must not be restarted")

    monkeypatch.setattr(app_module, "_sorting_reparse_launch_spec", unexpected_launch)

    assert app_module._ensure_sorting_reparse_service() is None


def test_sorting_reparse_service_starts_on_demand(monkeypatch, tmp_path):
    script_path = tmp_path / "ui_server.py"
    script_path.touch()
    log_path = tmp_path / "parser_stdout.log"
    health_checks = iter([False, False, True])
    launches = []

    monkeypatch.setattr(
        app_module,
        "_sorting_reparse_service_healthy",
        lambda timeout=1.0: next(health_checks),
    )
    monkeypatch.setattr(
        app_module,
        "_sorting_reparse_launch_spec",
        lambda: (["python", str(script_path)], Path(tmp_path), log_path),
    )
    monkeypatch.setattr(app_module.subprocess, "Popen", lambda *args, **kwargs: launches.append((args, kwargs)))

    assert app_module._ensure_sorting_reparse_service() is None
    assert len(launches) == 1
    assert launches[0][0][0] == ["python", str(script_path)]


def test_export_row_count_from_json_rows_matches_export_rules():
    rows = [
        ["1", "SSD A", "120", "IVEN", "", "", "", "", 0, "SSD"],
        ["1", "SSD B", "100", "N-Tech", "", "", "", "", 1, "SSD"],
        ["2", "Monitor", "300", "N-Tech", "", "", "", "", 2, "Монитор"],
        ["", "No ID", "10", "N-Tech", "", "", "", "", 3, "Кабели и переходники"],
        ["3", "ПЭВМ TGPC Office", "900", "TGPC", "", "", "", "", 4, "Системный блок"],
        ["4", "Клавиатура TGPC", "20", "TGPC", "", "", "", "", 5, "Клавиатура"],
    ]
    settings = {
        "export": {
            "include_without_id": False,
            "keep_lowest_price_per_onliner_id": True,
            "exclude_duplicate_id_suppliers": ["N-Tech"],
            "only_pc_suppliers": ["TGPC"],
        }
    }

    assert export_row_count_from_json_rows(
        rows,
        settings,
        normalize_onliner_id=app_module.normalize_onliner_id,
        normalize_name_key=app_module._normalize_name_key,
        normalize_supplier_name_list=app_module._export_normalize_supplier_name_list,
        is_pc_export_row=app_module._is_pc_export_row,
    ) == 3


def test_export_category_counts_from_json_rows_match_export_rules():
    rows = [
        ["1", "SSD A", "120", "IVEN", "", "", "", "", 0, "SSD"],
        ["1", "SSD B", "100", "N-Tech", "", "", "", "", 1, "SSD"],
        ["2", "Monitor", "300", "N-Tech", "", "", "", "", 2, "Монитор"],
        ["", "No ID", "10", "N-Tech", "", "", "", "", 3, "Кабели и переходники"],
        ["3", "ПЭВМ TGPC Office", "900", "TGPC", "", "", "", "", 4, "Системный блок"],
        ["4", "Клавиатура TGPC", "20", "TGPC", "", "", "", "", 5, "Клавиатура"],
    ]
    settings = {
        "export": {
            "include_without_id": False,
            "keep_lowest_price_per_onliner_id": True,
            "exclude_duplicate_id_suppliers": ["N-Tech"],
            "only_pc_suppliers": ["TGPC"],
        }
    }

    assert export_category_counts_from_json_rows(
        rows,
        settings,
        normalize_onliner_id=app_module.normalize_onliner_id,
        normalize_name_key=app_module._normalize_name_key,
        normalize_supplier_name_list=app_module._export_normalize_supplier_name_list,
        is_pc_export_row=app_module._is_pc_export_row,
        category_sort_key=app_module._category_sort_key,
    ) == [
        {"category": "SSD", "count": 1},
        {"category": "Монитор", "count": 1},
        {"category": "Системный блок", "count": 1},
    ]


def test_iven_pc_code_queries_extract_series_and_code():
    assert app_module._iven_pc_code_queries("Компьютер IVEN BY Gaming Black 180547 Ryzen") == [
        "Iven Gaming 180547",
        "IVEN BY Gaming 180547",
        "Gaming 180547",
        "180547",
    ]
    assert app_module._iven_pc_code_queries("Компьютер Iven Office 201993") == [
        "Iven Office 201993",
        "IVEN BY Office 201993",
        "Office 201993",
        "201993",
    ]


def test_native_catalog_category_repairs_bad_cable_tool_categories():
    assert app_module._native_catalog_category_for_product(
        "Кабели и переходники",
        "Система охлаждения ID-Cooling FS-04 (FS-04 PWM)",
    ) == "Охлаждение"
    assert app_module._native_catalog_category_for_product(
        "Кабели и переходники",
        "Стойка для дрели TEH TCD8160-STD",
    ) == "Строительный, слесарный, монтажный инструмент"
    assert app_module._native_catalog_category_for_product(
        "Кабели и переходники",
        "Переходник Milwaukee SDS Max на SDS+ (4932359490)",
    ) == "Строительный, слесарный, монтажный инструмент"
    assert app_module._native_catalog_category_for_product(
        "Кабели и переходники",
        "Кабель компьютер - сеть 220V, 1.8м",
    ) == "Кабели и переходники"
    assert app_module._native_catalog_category_for_product(
        "Воздуходувки",
        "Вентилятор Makita DCF102Z",
    ) == "Воздуходувки"
    assert app_module._native_catalog_category_for_product(
        "Охлаждение",
        "Вентилятор для корпуса Deepcool 120 PWM",
    ) == "Охлаждение"


def test_saved_category_repair_does_not_keep_tool_accessory_in_cables():
    assert app_module._repair_saved_category_for_product(
        "Кабели и переходники",
        "Адаптер для бит P.I.T. ATAM01-0002",
    ) == "Строительный, слесарный, монтажный инструмент"
    assert app_module._repair_saved_category_for_product(
        "Кабели и переходники",
        "Кабель компьютер - сеть 220V, 1.8м",
    ) == "Кабели и переходники"


def test_json_category_repair_detects_tool_accessory_in_cables():
    assert app_module._json_row_needs_category_repair(
        "Адаптер Milwaukee 4932493148",
        "Кабели и переходники",
        "Кабели и переходники",
    )


def test_strong_inferred_category_ignores_legacy_first_word_fallback():
    assert app_module._strong_inferred_category_for_product("Кухонная плита Gefest ПГ 1200-С6") == "Кухонные плиты"
    assert app_module._strong_inferred_category_for_product("Анкер забивной Fischer EA М16 25шт (90163)") == "Крепеж"
    assert app_module._strong_inferred_category_for_product("Непонятный товар без матрицы") == ""


def test_iven_pc_search_prefers_code_candidate(monkeypatch):
    monkeypatch.setattr(app_module, "db_find_exact_id_for_name", lambda name: None)
    monkeypatch.setattr(app_module, "_db_search_iven_pc_code_candidates", lambda name, limit=12: [{
        "id": "5137272",
        "name": "Компьютер Iven Office 201993",
        "url": "",
        "score": 1.0,
        "source": "db_iven_pc_code",
    }])
    monkeypatch.setattr(app_module, "db_find_top_candidates", lambda *args, **kwargs: [{
        "id": "4515809",
        "name": "Компьютер Iven GameBasic 186363",
        "url": "",
        "score": 0.8,
    }])

    result = app_module.db_search_iven_pc_candidates("Компьютер Iven Office 201993 Intel Core i3", limit=5)

    assert result[0]["id"] == "5137272"
    assert result[0]["source"] == "db_iven_pc_code"


def test_iven_pc_search_rejects_different_catalog_code(monkeypatch):
    monkeypatch.setattr(app_module, "db_find_exact_id_for_name", lambda name: None)
    monkeypatch.setattr(app_module, "_db_search_iven_pc_code_candidates", lambda name, limit=12: [])
    monkeypatch.setattr(app_module, "db_find_top_candidates", lambda *args, **kwargs: [{
        "id": "5136699",
        "name": "Компьютер Iven Gaming White 180554",
        "url": "",
        "score": 0.99,
    }])

    assert app_module.db_search_iven_pc_candidates(
        "Компьютер IVEN BY Gaming Black 180557 Ryzen 5",
        limit=5,
    ) == []


def test_iven_pc_identity_supports_gamebasic_and_prefers_code_after_series():
    name = "Компьютер IVEN GameBasic 186518 Core i5-12400 / 16Gb / 500000Mb SSD"

    assert app_module._is_iven_pc_name(name)
    assert app_module._extract_iven_pc_series(name) == "gamebasic"
    assert app_module._extract_iven_pc_code(name) == "186518"


def test_iven_pc_manual_binding_uses_code_alias(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "db_get_product_by_id",
        lambda oid: {"name": "Компьютер Iven Office 201993"} if str(oid) == "5137272" else None,
    )
    bindings = {
        "iven_pc:201993": {"id": "5137272", "url": ""},
    }

    assert app_module._lookup_manual_binding_for_name(
        bindings,
        "Системный блок Iven Office 201993 AMD Ryzen 5",
    ) == {"id": "5137272", "url": ""}


def test_iven_pc_manual_binding_rejects_different_catalog_code(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "db_get_product_by_id",
        lambda oid: {"name": "Компьютер Iven Gaming White 180554"} if str(oid) == "5136699" else None,
    )
    bindings = {
        "iven_pc:180557": {"id": "5136699", "url": ""},
    }

    assert app_module._lookup_manual_binding_for_name(
        bindings,
        "Компьютер IVEN BY Gaming Black 180557 Ryzen 5",
    ) is None


def test_clear_duplicate_onliner_ids_for_supplier_keeps_lowest_price():
    df = pd.DataFrame([
        {"Поставщик": "IVEN", "Название": "A", "OnlinerID": "42", "Ссылка": "u1", "Цена": "200"},
        {"Поставщик": "IVEN", "Название": "B", "OnlinerID": "42", "Ссылка": "u2", "Цена": "150"},
        {"Поставщик": "N-Tech", "Название": "C", "OnlinerID": "42", "Ссылка": "u3", "Цена": "100"},
    ])

    assert app_module._clear_duplicate_onliner_ids_for_suppliers(df, ["IVEN"]) == 1
    assert df.at[0, "OnlinerID"] == ""
    assert df.at[0, "Ссылка"] == ""
    assert df.at[1, "OnlinerID"] == "42"
    assert df.at[2, "OnlinerID"] == "42"


def test_iven_laptop_name_detects_only_notebooks():
    assert app_module._is_iven_laptop_name("Ноутбук IVEN Lenovo ThinkPad", "Ноутбук")
    assert app_module._is_iven_laptop_name("HP EliteBook 840", "Ноутбук")
    assert not app_module._is_iven_laptop_name("Сумка для ноутбука IVEN 15.6", "Ноутбук")
    assert not app_module._is_iven_laptop_name("Компьютер IVEN BY Gaming Black 180547", "Системный блок")


def test_iven_laptop_candidate_filters_accessories():
    assert app_module._is_iven_laptop_candidate("Игровой ноутбук Lenovo LOQ 15IRX10")
    assert not app_module._is_iven_laptop_candidate("Сумка для ноутбука Lenovo 15.6")


def test_tradex_laptop_name_detects_only_notebooks():
    assert app_module._is_tradex_laptop_name("Ноутбук Acer Aspire 5", "Ноутбук")
    assert app_module._is_tradex_laptop_name("HP EliteBook 840", "Ноутбук")
    assert not app_module._is_tradex_laptop_name("Сумка для ноутбука Acer 15.6", "Ноутбук")
    assert not app_module._is_tradex_laptop_name("Блок питания для ноутбука Lenovo", "Аксессуары")


def test_tradex_laptop_review_handler_builds_manual_queue(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_tradex_laptop_review_candidates",
        lambda name, top_n=5: [{
            "id": "123",
            "name": "Ноутбук Acer Aspire 5 A515",
            "url": "https://catalog.onliner.by/notebook/acer/a515",
            "score": 0.91,
            "source": "tradex_laptop_db",
        }],
    )
    is_target, build_row_result = app_module._build_tradex_laptop_review_handler()

    assert is_target({}, "Ноутбук Acer Aspire 5 A515", "Ноутбук")
    result = build_row_result(
        7,
        {"Поставщик": "Tradex"},
        "Ноутбук Acer Aspire 5 A515",
        "Ноутбук",
        123456,
    )

    assert result["action"] == "queued"
    assert result["queue_item"]["reason"] == "tradex_laptop_manual"
    assert result["queue_item"]["supplier"] == "Tradex"
    assert result["queue_item"]["laptop_brand"] == "Tradex"
    assert result["queue_item"]["candidates"][0]["source"] == "tradex_laptop_db"


def test_iven_zakaz_laptop_review_handler_uses_supplier_scoped_queue(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_iven_zakaz_laptop_review_candidates",
        lambda name, top_n=5: [{
            "id": "777",
            "name": "Ноутбук Lenovo IdeaPad",
            "url": "https://catalog.onliner.by/notebook/lenovo/777",
            "score": 0.91,
            "source": "iven_zakaz_laptop_db",
        }],
    )
    is_target, build_row_result = app_module._build_iven_zakaz_laptop_review_handler()

    result = build_row_result(
        3,
        {"Поставщик": "IVEN_zakaz"},
        "Ноутбук Lenovo IdeaPad",
        "Ноутбук",
        123456,
    )

    assert is_target({}, "Ноутбук Lenovo IdeaPad", "Ноутбук")
    assert result["action"] == "queued"
    assert result["name_key"].startswith("supplier:iven_zakaz:")
    assert result["queue_item"]["match_name_key"] == app_module._normalize_name_key("Ноутбук Lenovo IdeaPad")
    assert result["queue_item"]["supplier"] == "IVEN_zakaz"
    assert result["queue_item"]["reason"] == "iven_zakaz_laptop_manual"


def test_review_queue_supplier_scope_comes_from_entry_supplier():
    assert app_module._review_queue_unique_supplier_names({"supplier": "Tradex"}) == ["Tradex"]
    assert app_module._review_queue_unique_supplier_names({"suppliers": ["IVEN", "Tradex"]}) == ["IVEN", "Tradex"]
    assert app_module._review_queue_unique_supplier_names({"reason": "tradex_laptop_manual"}) == ["Tradex"]


def test_review_queue_pick_updates_only_entry_supplier(monkeypatch):
    product_name = "Видеокарта ASUS Prime Radeon RX 9070"
    name_key = app_module._normalize_name_key(product_name)
    df = pd.DataFrame([
        {"Поставщик": "Tradex", "Название": product_name, "OnlinerID": "", "Ссылка": "", "Цена": "2344"},
        {"Поставщик": "N-Tech", "Название": product_name, "OnlinerID": "", "Ссылка": "", "Цена": "2400"},
    ])
    queue = {
        name_key: {
            "name": product_name,
            "supplier": "Tradex",
            "candidates": [{"id": "4986332", "name": "Видеокарта ASUS Prime Radeon RX 9070"}],
        }
    }
    saved = {}
    written = {}

    monkeypatch.setattr(app_module, "load_review_queue", lambda: dict(queue))
    monkeypatch.setattr(app_module, "save_review_queue", lambda payload: saved.update(queue=payload))
    monkeypatch.setattr(app_module, "load_manual_id_bindings", lambda: {})
    monkeypatch.setattr(app_module, "save_manual_id_bindings", lambda payload: saved.update(manual=payload))
    monkeypatch.setattr(app_module, "get_active_session_dir", lambda: "/tmp/session")
    monkeypatch.setattr(app_module, "read_consolidated_json_fast_df", lambda session_dir: df.copy())
    monkeypatch.setattr(app_module, "write_consolidated_json", lambda frame, path: written.update(df=frame.copy()))
    monkeypatch.setattr(app_module, "write_consolidated_df_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "append_id_change_journal", lambda payload: None)

    with app_module.app.test_request_context(
        "/api/review-queue-pick",
        method="POST",
        json={"name_key": name_key, "onliner_id": "4986332", "url": "https://catalog.onliner.by/videocard/4986332"},
    ):
        resp = app_module.api_review_queue_pick()

    assert resp.status_code == 200
    assert saved["manual"]["supplier:tradex:" + name_key]["suppliers"] == ["Tradex"]
    assert written["df"].at[0, "OnlinerID"] == "4986332"
    assert written["df"].at[1, "OnlinerID"] == ""


def test_manual_binding_with_supplier_scope_does_not_cross_suppliers(monkeypatch):
    product_name = "Видеокарта ASUS Prime Radeon RX 9070"
    name_key = app_module._normalize_name_key(product_name)
    monkeypatch.setattr(
        app_module,
        "load_manual_id_bindings",
        lambda: {name_key: {"id": "4986332", "url": "https://catalog.onliner.by/videocard/4986332", "suppliers": ["Tradex"]}},
    )
    df = pd.DataFrame([
        {"Поставщик": "Tradex", "Название": product_name, "OnlinerID": "", "Ссылка": "", "Категория": "Видеокарта"},
        {"Поставщик": "N-Tech", "Название": product_name, "OnlinerID": "", "Ссылка": "", "Категория": "Видеокарта"},
    ])

    result = app_module._apply_manual_bindings_to_consolidated_df(df)

    assert result.at[0, "OnlinerID"] == "4986332"
    assert result.at[1, "OnlinerID"] == ""


def test_lookup_manual_binding_prefers_supplier_scoped_record():
    product_name = "Ноутбук Lenovo A"
    name_key = app_module._normalize_name_key(product_name)
    manual = {
        name_key: {"id": "100"},
        "supplier:iven:" + name_key: {"id": "111", "suppliers": ["IVEN"]},
        "supplier:iven_zakaz:" + name_key: {"id": "222", "suppliers": ["IVEN_zakaz"]},
    }

    assert app_module._lookup_manual_binding_for_name(manual, product_name, "IVEN")["id"] == "111"
    assert app_module._lookup_manual_binding_for_name(manual, product_name, "IVEN_zakaz")["id"] == "222"
    assert app_module._lookup_manual_binding_for_name(manual, product_name, "Tradex") is None


def test_strict_candidate_allows_exact_article_across_marketing_brands():
    local = "Видеокарта NVIDIA GeForce Gigabyte RTX 5060 Ti (GV-N506TEAGLE OC-8GD)"
    candidate = "Видеокарта Gigabyte GeForce RTX 5060 Ti Eagle OC 8G GV-N506TEAGLE OC-8GD"

    assert app_module.calc_name_match(local, candidate)["score"] == 1.0
    assert app_module._strict_candidate_allowed(local, candidate) == (True, "strong_identity")


def test_manual_confirmed_checker_uses_supplier_without_undefined_row(monkeypatch):
    product_name = "Ноутбук Lenovo A"
    name_key = app_module._normalize_name_key(product_name)
    monkeypatch.setattr(
        app_module,
        "load_manual_id_bindings",
        lambda: {"supplier:iven_zakaz:" + name_key: {"id": "222", "suppliers": ["IVEN_zakaz"]}},
    )

    checker = app_module._manual_confirmed_checker()

    assert checker(product_name, "222", "IVEN_zakaz")
    assert not checker(product_name, "222", "IVEN")


def test_processing_pipeline_respects_supplier_scoped_manual_binding():
    manual = {"id": "4986332", "suppliers": ["Tradex"]}

    assert processing_pipeline._manual_binding_applies_to_supplier(manual, "Tradex")
    assert not processing_pipeline._manual_binding_applies_to_supplier(manual, "N-Tech")
    assert processing_pipeline._manual_binding_applies_to_supplier({"id": "4986332"}, "N-Tech")


def test_all_supplier_scoped_manual_bindings_are_allowed_on_reload():
    assert app_module._allow_manual_binding_for_supplier("IVEN", "Материнская плата MSI", "Материнская плата")
    assert app_module._allow_manual_binding_for_supplier("IVEN", "Видеокарта ASUS", "Видеокарта")
    assert app_module._allow_manual_binding_for_supplier("IVEN_zakaz", "Моноблок Acer", "Моноблоки")
    assert app_module._allow_manual_binding_for_supplier("Tradex", "Ноутбук Lenovo", "Ноутбук")
    assert app_module._allow_manual_binding_for_supplier("N-Tech", "SSD Kingston", "SSD")


def test_review_queue_migration_scopes_legacy_entries_without_losing_data():
    queue = {
        "same-product": {
            "name": "Same Product",
            "supplier": "N-Tech",
            "candidates": [{"id": "111"}],
        },
        "supplier:tradex:same-product": {
            "name": "Same Product",
            "match_name_key": "same-product",
            "supplier": "Tradex",
            "candidates": [{"id": "222"}],
        },
    }

    migrated, changed = app_module._migrate_review_queue_supplier_scope(queue)

    assert changed is True
    assert "same-product" not in migrated
    assert migrated["supplier:n_tech:same-product"]["candidates"][0]["id"] == "111"
    assert migrated["supplier:tradex:same-product"]["candidates"][0]["id"] == "222"


def test_preferred_brand_skips_case_fan_and_bag_descriptors():
    assert app_module._preferred_brand_token("Вентилятор для корпуса Montech AX140 PWM") == "Montech"
    assert app_module._preferred_brand_token("Комплект вентиляторов для корпуса ID-Cooling AF-127") == "ID-Cooling"
    assert app_module._preferred_brand_token('Сумка для ноутбука 15,6" MIRU Elegance Red (1030)') == "MIRU"
    assert app_module._preferred_brand_token("Кабель соединительный DP-DP 4K@60Hz, медь, Telecom (TCG715-5M)") == "Telecom"
    assert app_module._preferred_brand_token("Кабель DP-HDMI Cablexpert (CC-DP-HDMI-3M)") == "Cablexpert"
    assert app_module._preferred_brand_token(
        "Наушники с микрофоном Logitech H390 (981-000406) Black RTL"
    ) == "Logitech"
    assert app_module._preferred_brand_token(
        "Офисная гарнитура Logitech H390 (черный)"
    ) == "Logitech"
    assert app_module._preferred_brand_token(
        "Кабель VGA 15 male - VGA 15 male VCOM (VVG6448-1.8MO) 2f 1.8м"
    ) == "VCOM"
    assert app_module._preferred_brand_token(
        "Micro SD 32 Gb Netac P500 Extreme Pro microSDHC (NT02P500PRO-032G-R)"
    ) == "Netac"


def test_ntech_manual_matching_uses_headset_cable_and_microsd_tokens():
    headset = app_module.calc_name_match(
        "Наушники с микрофоном Logitech H390 (981-000406) Black RTL",
        "Офисная гарнитура Logitech H390 (черный)",
    )
    cable = app_module.calc_name_match(
        "Кабель VGA 15 male - VGA 15 male VCOM (VVG6448-1.8MO) 2f 1.8м",
        "Кабель VCOM VVG6448-1.8MO VGA - VGA (1.8 м, черный)",
    )
    microsd = app_module.calc_name_match(
        "Micro SD 32 Gb Netac P500 Extreme Pro microSDHC (NT02P500PRO-032G-R) с адаптером",
        "Карта памяти Netac P500 Extreme Pro 32GB NT02P500PRO-032G-R (с адаптером)",
    )

    assert headset["match"] is True
    assert headset["score"] >= 0.8
    assert cable == {"score": 1.0, "match": True, "reason": "article"}
    assert microsd == {"score": 1.0, "match": True, "reason": "article"}


def test_iven_laptop_duplicate_conflict_detects_other_iven_row():
    df = pd.DataFrame([
        {"Поставщик": "IVEN", "Название": "Ноутбук Acer A", "OnlinerID": "123"},
        {"Поставщик": "IVEN", "Название": "Ноутбук Acer B", "OnlinerID": ""},
        {"Поставщик": "N-Tech", "Название": "Ноутбук Acer C", "OnlinerID": "123"},
    ])

    conflict = app_module._df_onliner_id_conflict_for_supplier(
        df,
        app_module._normalize_name_key("Ноутбук Acer B"),
        "123",
        ["IVEN"],
    )

    assert conflict["name"] == "Ноутбук Acer A"


def test_iven_laptop_duplicate_conflict_ignores_ntech_rows():
    df = pd.DataFrame([
        {"Поставщик": "N-Tech", "Название": "Ноутбук Acer N-Tech", "OnlinerID": "123"},
        {"Поставщик": "IVEN", "Название": "Ноутбук Acer IVEN", "OnlinerID": ""},
    ])

    conflict = app_module._df_onliner_id_conflict_for_supplier(
        df,
        app_module._normalize_name_key("Ноутбук Acer IVEN"),
        "123",
        ["IVEN"],
    )

    assert conflict is None


def test_review_queue_unique_supplier_names_cover_laptop_layers():
    assert app_module._review_queue_unique_supplier_names({"reason": "iven_laptop_manual"}) == ["IVEN"]
    assert app_module._review_queue_unique_supplier_names({"reason": "tradex_laptop_manual"}) == ["Tradex"]
    assert app_module._review_queue_unique_supplier_names({"reason": "ntech_category_manual"}) == []


def test_iven_pc_cache_keys_include_stable_code_aliases():
    assert app_module._id_cache_keys_for_iven_pc_name("Компьютер IVEN BY Gaming Black 180547 Ryzen") == [
        "iven_pc:180547",
        "iven_pc:gaming:180547",
    ]


def test_expand_iven_pc_manual_aliases_backfills_existing_full_name(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "db_get_product_by_id",
        lambda oid: {"name": "Компьютер Iven Office 201993"} if str(oid) == "5137272" else None,
    )
    expanded, changed = app_module._expand_iven_pc_manual_aliases({
        "системный блок iven office 201993 amd ryzen 5": {"id": "5137272", "url": ""},
    })

    assert changed is True
    assert expanded["iven_pc:201993"]["id"] == "5137272"
    assert expanded["iven_pc:office:201993"]["id"] == "5137272"


def test_expand_iven_pc_manual_aliases_preserves_supplier_scope(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "db_get_product_by_id",
        lambda oid: {"name": "Компьютер Iven Office 201993"} if str(oid) == "5137272" else None,
    )
    source_key = "supplier:iven:системный блок iven office 201993 amd ryzen 5"
    expanded, changed = app_module._expand_iven_pc_manual_aliases({
        source_key: {"id": "5137272", "url": "", "suppliers": ["IVEN"]},
    })

    assert changed is True
    assert expanded["supplier:iven:iven_pc:201993"]["id"] == "5137272"
    assert expanded["supplier:iven:iven_pc:office:201993"]["id"] == "5137272"
    assert "iven_pc:201993" not in expanded
    assert "iven_pc:office:201993" not in expanded


def test_google_and_xlsx_export_share_revision_cached_runtime(monkeypatch):
    calls = 0

    def prepare(*args, **kwargs):
        nonlocal calls
        calls += 1
        return pd.DataFrame({"value": [1]}), "price.xlsx"

    monkeypatch.setattr(app_module, "EXPORT_RUNTIME", None)
    monkeypatch.setattr(app_module, "_session_revision_token", lambda session_dir: (session_dir, 1))
    monkeypatch.setattr(app_module, "_export_prepare_consolidated", prepare)

    first, first_name = app_module._prepare_consolidated_for_google_export("session")
    first.at[0, "value"] = 99
    second, second_name = app_module._prepare_consolidated_for_export("session")

    assert calls == 1
    assert first_name == second_name == "price.xlsx"
    assert second.at[0, "value"] == 1


def test_consolidated_page_applies_server_side_no_id_filter(monkeypatch):
    rows = [
        ["10", "SSD", 100, "IVEN", "", "2", "", "", 1, "SSD"],
        ["", "Mouse", 20, "N-Tech", "", "2", "", "", 2, "Мышь"],
    ]
    monkeypatch.setattr(app_module, "get_active_session_dir", lambda: "session")
    monkeypatch.setattr(app_module, "_has_consolidated_session_file", lambda session_dir: True)
    monkeypatch.setattr(
        app_module,
        "_correct_consolidated_json_rows",
        lambda session_dir, apply_visibility=True: rows,
    )
    monkeypatch.setattr(app_module, "_filter_json_rows_by_export_name_exclusions", lambda value: value)

    with app_module.app.test_request_context(
        "/api/consolidated-page?draw=3&filter_mode=no_id&start=0&length=100"
    ):
        response = app_module.api_consolidated_page()

    payload = response.get_json()
    assert payload["draw"] == 3
    assert payload["recordsTotal"] == 2
    assert payload["recordsFiltered"] == 1
    assert payload["data"][0][1] == "Mouse"
    assert payload["meta"]["badge_counts"]["mouse"] == 1


def test_legacy_session_dir_is_migrated_when_safe(monkeypatch, tmp_path):
    session_dir = tmp_path / "deadbeef"
    session_dir.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path)

    with app_module.app.test_request_context("/"):
        session["session_dir"] = str(session_dir)
        session["output_path"] = str(session_dir / "consolidated_price.xlsx")

        assert app_module.get_active_session_dir() == str(session_dir.resolve())
        assert session["session_id"] == "deadbeef"
        assert "session_dir" not in session
        assert "output_path" not in session


def test_legacy_session_dir_rejects_paths_outside_uploads(monkeypatch, tmp_path):
    outside = tmp_path.parent / "outside-session"
    outside.mkdir(exist_ok=True)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path)

    with app_module.app.test_request_context("/"):
        session["session_dir"] = str(outside)
        session["output_path"] = str(outside / "consolidated_price.xlsx")

        assert app_module.get_active_session_dir() is None
        assert "session_dir" not in session
        assert "output_path" not in session
