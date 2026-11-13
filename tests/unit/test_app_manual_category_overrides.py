"""Regression tests for durable manual category choices in the JSON fast path."""

import json

import app
import pandas as pd


def test_current_session_repairs_junk_categories_without_changing_products(tmp_path, monkeypatch):
    app.APP_SERVICES.reset("category_repair")
    original = [
        ["", "G&G toner-cartridge for Kyocera MFP (GG-TK1178)", 40, "Techlab", 12, 2, 50, 60, 0, "G"],
        ["", "1.92Tb Netac ENSP401 (NS1T921P4HH6PA01)", 100, "IVEN_zakaz", 12, 2, 120, 140, 1, "1"],
        ["", "3.84Tb Lenovo ThinkSystem 4XB7A38275", 200, "IVEN_zakaz", 12, 2, 220, 240, 2, "3"],
    ]
    (tmp_path / "consolidated.json").write_text(json.dumps({"data": original}))
    monkeypatch.setattr(app, "db_get_categories_by_ids", lambda ids: {})
    monkeypatch.setattr(app, "db_get_categories_by_exact_names", lambda names: {})
    monkeypatch.setattr(app, "load_category_overrides", lambda: {})
    monkeypatch.setattr(app, "load_manual_category_overrides", lambda: {})
    monkeypatch.setattr(app, "load_visibility_map", lambda _: {"__global__": ["Картриджи"]})
    full = app._correct_consolidated_json_rows(tmp_path, apply_visibility=False)
    assert [r[9] for r in full] == ["Картриджи", "SSD", "SSD"]
    assert [r[:9] for r in full] == [r[:9] for r in original]
    visible = app._correct_consolidated_json_rows(tmp_path, apply_visibility=True)
    assert len(visible) == 2
    app.APP_SERVICES.reset("category_repair")


def test_appliance_accessory_rejects_unrelated_catalog_parent():
    name = "Компоненты для пылесоса Trouver Water Filter"
    assert app._native_catalog_category_for_product("Миски, поилки, кормушки для животных", name) == ""
    assert app._native_catalog_category_for_product("Пылесосы", name) == "Пылесосы"


def test_cartridge_markup_does_not_use_printer_percentage(monkeypatch):
    frame = pd.DataFrame([{
        "Название": "Картридж HP LaserJet для MFP M134", "Категория": "Принтеры",
        "Цена": 100, "OnlinerID": "",
    }])
    monkeypatch.setattr(app, "load_category_markups", lambda: {
        "Принтеры": {"percent": 15}, "Картриджи": {"percent": 25},
    })
    result = app.apply_saved_markups_to_df(frame)
    assert result.iloc[0]["РРЦ"] == app.round_price_to_90(125)


def test_ensure_category_column_only_infers_rows_missing_catalog_category(monkeypatch):
    df = pd.DataFrame({
        "OnlinerID": ["1", "2", ""],
        "Название": ["Catalog product", "Unknown ID", "No ID"],
        "Категория": ["", "", ""],
    })
    inferred_indices = []

    def infer_subset(frame, **kwargs):
        inferred_indices.extend(frame.index.tolist())
        result = frame.copy()
        result["Категория"] = "inferred"
        return result

    monkeypatch.setattr(app, "load_category_overrides", lambda: {})
    monkeypatch.setattr(app, "db_get_categories_by_ids", lambda ids: {"1": "catalog"})
    monkeypatch.setattr(app, "_native_catalog_category_for_product", lambda category, name: category)
    monkeypatch.setattr(app, "_category_ensure_column", infer_subset)

    result = app.ensure_category_column(df)

    assert inferred_indices == [1, 2]
    assert result["Категория"].tolist() == ["catalog", "inferred", "inferred"]


def test_correct_consolidated_rows_prioritizes_onliner_category_for_known_id(tmp_path, monkeypatch):
    (tmp_path / "consolidated.json").write_text(
        json.dumps({
            "data": [[
                "123",
                "Controller USB",
                10,
                "IVEN",
                12,
                "2",
                12,
                14,
                0,
                "Требует сортировки · родитель: КОНТРОЛЛЕР",
            ]],
        }),
        encoding="utf-8",
    )
    rule = {"name:controller usb": "Контроллеры"}
    monkeypatch.setattr(app, "db_get_categories_by_ids", lambda ids: {"123": "Мониторы"})
    monkeypatch.setattr(app, "db_get_categories_by_exact_names", lambda names: {})
    monkeypatch.setattr(app, "load_category_overrides", lambda: rule)
    monkeypatch.setattr(app, "load_manual_category_overrides", lambda: rule)

    rows = app._correct_consolidated_json_rows(tmp_path, apply_visibility=False)

    assert rows[0][9] == "Монитор"


def test_correct_consolidated_rows_uses_exact_name_category_without_id(tmp_path, monkeypatch):
    (tmp_path / "consolidated.json").write_text(
        json.dumps({
            "data": [[
                "",
                "IP-камера Dahua DH-IPC-C2KP-P-0360B",
                10,
                "Tradex",
                12,
                "2",
                12,
                14,
                0,
                "IP-КАМЕРА",
            ]],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "db_get_categories_by_ids", lambda ids: {})
    monkeypatch.setattr(app, "db_get_categories_by_exact_names", lambda names: {
        "ip-камера dahua dh-ipc-c2kp-p-0360b": "IP-камеры",
    })
    monkeypatch.setattr(app, "load_category_overrides", lambda: {})
    monkeypatch.setattr(app, "load_manual_category_overrides", lambda: {})

    rows = app._correct_consolidated_json_rows(tmp_path, apply_visibility=False)

    assert rows[0][9] == "IP-камеры"


def test_correct_consolidated_rows_repairs_raw_supplier_category_without_id(tmp_path, monkeypatch):
    (tmp_path / "consolidated.json").write_text(
        json.dumps({
            "data": [[
                "",
                "Сетевая карта Cudy UE10A USB3.0 1xRJ-45",
                10,
                "N-Tech",
                12,
                "2",
                12,
                14,
                0,
                "СЕТЕВАЯ",
            ]],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "db_get_categories_by_ids", lambda ids: {})
    monkeypatch.setattr(app, "db_get_categories_by_exact_names", lambda names: {})
    monkeypatch.setattr(app, "load_category_overrides", lambda: {})
    monkeypatch.setattr(app, "load_manual_category_overrides", lambda: {})

    rows = app._correct_consolidated_json_rows(tmp_path, apply_visibility=False)

    assert rows[0][9] == "Сетевые адаптеры"


def test_quality_visibility_filter_suppresses_category_hidden_for_another_supplier(monkeypatch):
    df = pd.DataFrame({
        "Поставщик": ["N-Tech", "N-Tech"],
        "Название": ["UPS battery", "Mouse"],
        "Категория": ["АККУМУЛЯТОРНАЯ", "Мышь"],
    })
    monkeypatch.setattr(app, "apply_visibility_filter", lambda frame, session_dir: frame)
    monkeypatch.setattr(app, "load_visibility_map", lambda session_dir: {"IVEN": ["АККУМУЛЯТОР"]})

    result = app.apply_quality_visibility_filter(df, "/tmp/session")

    assert list(result["Название"]) == ["Mouse"]


def test_normalize_visibility_map_ignores_legacy_supplier_visibility():
    assert app._normalize_visibility_map({"IVEN": ["SSD"], "Tradex": ["Средства для стирки"]}) == {}


def test_normalize_visibility_map_preserves_global_visibility():
    assert app._normalize_visibility_map({app.GLOBAL_VISIBILITY_KEY: ["Кулер"]}) == {
        app.GLOBAL_VISIBILITY_KEY: ["Кулер", "Кулеры"],
    }


def test_supplier_categories_payload_mirrors_structure_categories(tmp_path, monkeypatch):
    df = pd.DataFrame([
        {
            "Поставщик": "Tradex",
            "Категория": "Средства для стирки",
            "Название": "Парфюмированные гранулы для белья Lenor",
            "Цена": 10,
            "РРЦ": 12,
            "Цена без скидки": 15,
        },
        {
            "Поставщик": "IVEN",
            "Категория": "SSD",
            "Название": "SSD Test",
            "Цена": 20,
            "РРЦ": 25,
            "Цена без скидки": 30,
        },
        {
            "Поставщик": "Tradex",
            "Категория": "Биты и насадки",
            "Название": "Угловая насадка Milwaukee OSD 2",
            "Цена": 30,
            "РРЦ": 35,
            "Цена без скидки": 40,
        },
        {
            "Поставщик": "Tradex",
            "Категория": "СТАНИНА",
            "Название": "Станина Milwaukee",
            "Цена": 40,
            "РРЦ": 50,
            "Цена без скидки": 60,
        },
        {
            "Поставщик": "IVEN",
            "Категория": "IP",
            "Название": "Raw IP heading",
            "Цена": 70,
            "РРЦ": 80,
            "Цена без скидки": 90,
        },
        {
            "Поставщик": "IVEN",
            "Категория": "MOXA",
            "Название": "Raw brand heading",
            "Цена": 100,
            "РРЦ": 110,
            "Цена без скидки": 120,
        },
    ])
    monkeypatch.setattr(app, "get_active_session_dir", lambda: tmp_path)
    monkeypatch.setattr(app, "_has_consolidated_session_file", lambda session_dir: True)
    monkeypatch.setattr(app, "_consolidated_json_df", lambda session_dir, apply_visibility=False: df)
    monkeypatch.setattr(app, "load_category_overrides", lambda: {})
    monkeypatch.setattr(app, "load_visibility_map", lambda session_dir: {})

    payload = app._supplier_categories_payload(app.GLOBAL_VISIBILITY_KEY)

    assert [item["name"] for item in payload["categories"]] == ["SSD", "Сеть", "Биты и насадки", "Средства для стирки"]


def test_visible_onliner_category_preserves_native_name_but_normalizes_slug():
    assert app._canonical_visible_onliner_category_name("Биты и насадки") == "Биты и насадки"
    assert app._canonical_visible_onliner_category_name("bits heads") == "Биты и насадки"


def test_hidden_category_counts_use_global_visibility(monkeypatch):
    monkeypatch.setattr(
        app,
        "load_visibility_map",
        lambda session_dir: {app.GLOBAL_VISIBILITY_KEY: ["Средства для стирки"]},
    )
    rows = [
        ["1", "Lenor", 10, "Tradex", "", "", "", "", "", "Средства для стирки"],
        ["2", "SSD", 20, "IVEN", "", "", "", "", "", "SSD"],
    ]

    assert app._hidden_category_counts_from_json_rows(rows, "/tmp/session") == [
        {"category": "Средства для стирки", "count": 1},
    ]
