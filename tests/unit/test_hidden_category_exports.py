from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pandas as pd
import pytest

import app as app_module
from price_mixer.services.product_type_categories import specific_product_category


NAMES = [
    "Чайник электрический Bosch TWK3P420 корпус сталь",
    "Сплит-система Centek CT-65K07 WiFi белый",
    "Кулер AEL L-AEL-016 напольный белый",
    "Картридж Гейзер PP 5-10BB для проточных фильтров",
    "Набор инструментов Deko DKMT82 жесткий кейс",
    "Радиоприемник Hyundai USB microSD",
    "Умная лампа Gauss E27 Wi-Fi",
]


@pytest.mark.parametrize("supplier", ["IVEN", "IVEN_zakaz", "Tradex", "N-Tech", "Techlab"])
def test_saved_sessions_json_google_and_xlsx_share_hidden_category_guards(monkeypatch, tmp_path, supplier):
    rows = [[str(i + 1), name, 100, supplier, 12, 2, 120, 130, i, "Корпус"] for i, name in enumerate(NAMES)]
    rows.append(["999", "Корпус Chieftec ATX", 100, supplier, 12, 2, 120, 130, len(rows), "Корпус"])
    hidden = {specific_product_category(name) for name in NAMES}
    cache = {}
    runtime = replace(
        app_module._get_category_repair_runtime(),
        read_rows=lambda *_a, **_kw: rows,
        cache_key=lambda _session, _path, visible: (visible, tuple(sorted(hidden))),
        get_cached_rows=cache.get,
        set_cached_rows=lambda key, value: cache.__setitem__(key, value),
        load_visibility_map=lambda _: {"__global__": list(hidden)},
        get_categories_by_ids=lambda ids: {str(oid): "Корпус" for oid in ids},
        get_categories_by_exact_names=lambda _: {},
        load_category_overrides=lambda: {},
        load_manual_category_overrides=lambda: {},
        supplier_visibility_known_categories=lambda: set(),
    )
    # Even a stale PC category stored in the catalog must not override the product type.
    corrected = runtime.correct_rows(tmp_path, apply_visibility=False)
    assert [r[9] for r in corrected[:-1]] == [specific_product_category(name) for name in NAMES]
    assert len(runtime.correct_rows(tmp_path, apply_visibility=True)) == 1
    assert all(r[9] == "Корпус" for r in rows)

    def read_frame(_path, **_kwargs):
        return app_module._consolidated_dataframe_from_rows(runtime.correct_rows(tmp_path, apply_visibility=False))

    monkeypatch.setattr(app_module, "_consolidated_json_df", read_frame)
    monkeypatch.setattr(app_module, "load_manual_id_bindings", lambda: {})
    monkeypatch.setattr(app_module, "load_category_markups", lambda: {})
    monkeypatch.setattr(app_module, "read_consolidated_json_fast_df", lambda _: (_ for _ in ()).throw(AssertionError("uncorrected SQL export")))
    monkeypatch.setattr(app_module, "apply_visibility_filter", lambda df, _: app_module._category_apply_visibility_filter(
        df, tmp_path, load_visibility_map_func=lambda _: {"__global__": list(hidden)},
        normalize_category=app_module._canonical_ui_category_name,
    ))
    monkeypatch.setattr(app_module, "_has_consolidated_session_file", lambda _: True)
    monkeypatch.setattr(app_module, "_session_revision_token", lambda _: tuple(sorted(hidden)))
    monkeypatch.setattr(app_module, "_export_settings_with_onliner_structure", lambda: {"export": {}})
    monkeypatch.setattr(app_module, "EXPORT_RUNTIME", None)
    monkeypatch.setattr(app_module, "EXPORT_DELIVERY_RUNTIME", None)
    google_frame, _ = app_module._prepare_consolidated_for_google_export(tmp_path)
    content, _ = app_module._get_export_delivery_runtime().xlsx(
        tmp_path, {"export": {}}, revision_token=app_module._session_revision_token(tmp_path),
    )
    xlsx_frame = pd.read_excel(BytesIO(content))
    assert google_frame["Название"].tolist() == xlsx_frame["Название"].tolist() == ["Корпус Chieftec ATX"]

    # Re-enabling categories must invalidate both the rows and the export artifact.
    hidden.clear()
    enabled_frame, _ = app_module._prepare_consolidated_for_google_export(tmp_path)
    enabled_content, _ = app_module._get_export_delivery_runtime().xlsx(
        tmp_path, {"export": {}}, revision_token=app_module._session_revision_token(tmp_path),
    )
    assert len(enabled_frame) == len(pd.read_excel(BytesIO(enabled_content))) == len(rows)


def test_visibility_normalizes_equivalent_category_titles():
    hidden = app_module._normalize_visibility_map({"__global__": [
        "USB-хабы и док-станции", "Электрические чайники", "Кулеры для воды", "Чехлы для телефонов",
    ]})["__global__"]
    for category in ["USB-хабы", "Электрочайники и термопоты", "Диспенсеры", "Чехлы для смартфонов"]:
        assert category in hidden


def test_export_rechecks_catalog_category_after_durable_manual_id_overlay(monkeypatch):
    frame = pd.DataFrame([{"OnlinerID": "1", "Название": "Модель X", "Категория": "Корпус"}])
    monkeypatch.setattr(app_module, "_consolidated_json_df", lambda *_a, **_kw: frame.copy())
    monkeypatch.setattr(app_module, "_apply_manual_bindings_to_consolidated_df", lambda df: df.assign(OnlinerID="2"))
    monkeypatch.setattr(app_module, "db_get_categories_by_ids", lambda ids: {"2": "Пылесосы"})
    monkeypatch.setattr(app_module, "load_category_overrides", lambda: {})
    monkeypatch.setattr(app_module, "load_category_markups", lambda: {})
    exported = app_module.read_consolidated_export_df("session")
    assert exported.iloc[0]["OnlinerID"] == "2"
    assert exported.iloc[0]["Категория"] == "Пылесосы"


def test_catalog_changes_invalidate_category_rows_and_export_without_scanning_catalog(monkeypatch, tmp_path):
    catalog = tmp_path / "onliner_products.db"
    catalog.write_bytes(b"catalog")
    monkeypatch.setattr(app_module, "RUNTIME_PATHS", SimpleNamespace(
        data_file=lambda _: catalog, state_file=lambda name: tmp_path / name, cache_file=lambda name: tmp_path / name,
    ))
    monkeypatch.setattr(app_module, "SESSION_PRODUCT_STORE", SimpleNamespace(canonical=False))
    monkeypatch.setattr(app_module, "_category_state_signature", lambda *_: ())
    monkeypatch.setattr(app_module, "SESSION_DATA_RUNTIME", SimpleNamespace(revision_token=lambda *_a, **kw: kw["extra"]))
    before_rows = app_module._corrected_json_rows_cache_key(tmp_path, tmp_path / "consolidated.json", True)
    before_export = app_module._session_revision_token(tmp_path)
    catalog.with_name(catalog.name + "-wal").write_bytes(b"new categories")
    assert app_module._corrected_json_rows_cache_key(tmp_path, tmp_path / "consolidated.json", True) != before_rows
    assert app_module._session_revision_token(tmp_path) != before_export


@pytest.mark.parametrize("title", ["USB-хабы и док-станции", "USB-хабы"])
def test_category_alias_can_be_reenabled_after_loading_legacy_visibility(monkeypatch, title):
    saved = {}
    runtime = replace(
        app_module._get_category_management_runtime(),
        get_active_session_dir=lambda: "session",
        load_visibility_map=lambda _: app_module._normalize_visibility_map({"__global__": ["USB-хабы и док-станции"]}),
        save_visibility_map=lambda _, value: saved.update(value),
    )
    result, status = runtime.visibility({"categories": [title], "hidden": False})
    assert status == 200
    assert result["categories"] == []
    assert saved == {}
