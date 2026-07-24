"""Regression tests for supplier-scoped IDs across a fresh price upload."""

from pathlib import Path

import pandas as pd

from price_mixer.services.manual_id_store import (
    build_supplier_binding_record,
    supplier_scoped_binding_key,
)
from price_mixer.services.processing_pipeline import process_supplier_files
from price_mixer.services.product_normalization import normalize_name_key, normalize_onliner_id


def _run_upload(
    tmp_path,
    source_df,
    bindings,
    *,
    ensure_category_column=None,
    apply_saved_markups_to_df=None,
):
    source = tmp_path / "prices.xlsx"
    source.touch()
    written = {}

    def lookup(records, name, supplier=""):
        return records.get(supplier_scoped_binding_key(normalize_name_key(name), supplier))

    result = process_supplier_files(
        [{"filepath": source, "display_name": source.name, "supplier_name": "ignored"}],
        session_id="session-test",
        session_dir=tmp_path / "session-test",
        create_session_dir=lambda: ("unused", tmp_path / "unused"),
        load_app_settings=lambda: {},
        parse_generic_excel=lambda filepath, supplier: source_df.copy(),
        consolidate_simple=lambda df: df.copy(),
        normalize_consolidated_columns=lambda df: df.copy(),
        ensure_category_column=ensure_category_column or (lambda df: df.copy()),
        apply_saved_markups_to_df=apply_saved_markups_to_df or (lambda df: df.copy()),
        load_manual_id_bindings=lambda: dict(bindings),
        expand_iven_pc_manual_aliases=lambda records: (records, False),
        save_manual_id_bindings=lambda records: None,
        load_id_cache=lambda: {},
        sanitize_id_cache=lambda cache: (cache, False),
        save_id_cache=lambda cache: None,
        build_id_fanout_map=lambda cache: {},
        normalize_name_key=normalize_name_key,
        normalize_onliner_id=normalize_onliner_id,
        is_iven_pc_name=lambda name: False,
        iven_pc_onliner_id_mismatch_known=lambda name, oid: False,
        allow_manual_binding_for_supplier=lambda supplier, name, category: True,
        lookup_manual_binding_for_name=lookup,
        id_cache_keys_for_iven_pc_name=lambda name: [],
        get_id_cache_key_for_name=lambda name: "",
        is_trusted_cached_id=lambda *args, **kwargs: False,
        iven_pc_onliner_id_matches_name=lambda name, oid: False,
        clear_duplicate_onliner_ids_for_suppliers=lambda df, suppliers: 0,
        write_consolidated_df=lambda session_dir, df: (_ for _ in ()).throw(
            AssertionError("XLSX write must be deferred")
        ),
        write_consolidated_json=lambda df, path: written.update(json=df.copy()),
        save_session_supplier_diff=lambda session_dir, value: None,
        count_rows_without_onliner_id=lambda df: int((df["OnlinerID"] == "").sum()),
        count_rows_with_duplicate_onliner_id=lambda df: 0,
        coerce_bool=lambda value, default=False: bool(value if value is not None else default),
        maybe_cleanup_old_uploads=lambda **kwargs: None,
    )
    return result, written["json"]


def test_new_upload_restores_different_ids_for_same_name_across_all_suppliers(tmp_path):
    suppliers = ["IVEN", "IVEN_zakaz", "Tradex", "N-Tech"]
    ids = ["111", "222", "333", "444"]
    product_name = "Одинаковая материнская плата"
    source_df = pd.DataFrame({
        "Поставщик": suppliers,
        "Название": [product_name] * 4,
        "OnlinerID": [""] * 4,
        "Ссылка": [""] * 4,
        "Категория": ["Материнская плата"] * 4,
    })
    bindings = {
        supplier_scoped_binding_key(normalize_name_key(product_name), supplier):
            build_supplier_binding_record(oid, "u" + oid, supplier)
        for supplier, oid in zip(suppliers, ids)
    }

    _result, uploaded = _run_upload(tmp_path, source_df, bindings)

    assert uploaded["OnlinerID"].tolist() == ids
    assert uploaded["Ссылка"].tolist() == ["u111", "u222", "u333", "u444"]


def test_new_upload_applies_block_only_to_its_supplier(tmp_path):
    product_name = "SSD Same"
    source_df = pd.DataFrame({
        "Поставщик": ["IVEN", "Tradex"],
        "Название": [product_name, product_name],
        "OnlinerID": ["source-iven", "source-tradex"],
        "Ссылка": ["iven-url", "tradex-url"],
        "Категория": ["SSD", "SSD"],
    })
    bindings = {
        supplier_scoped_binding_key(normalize_name_key(product_name), "IVEN"):
            build_supplier_binding_record("", "", "IVEN", blocked=True),
        supplier_scoped_binding_key(normalize_name_key(product_name), "Tradex"):
            build_supplier_binding_record("333", "u333", "Tradex"),
    }

    _result, uploaded = _run_upload(tmp_path, source_df, bindings)

    assert uploaded.at[0, "OnlinerID"] == ""
    assert uploaded.at[0, "Ссылка"] == ""
    assert uploaded.at[1, "OnlinerID"] == "333"
    assert uploaded.at[1, "Ссылка"] == "u333"


def test_new_upload_recalculates_categories_only_for_changed_ids_and_markups_once(tmp_path):
    source_df = pd.DataFrame({
        "Поставщик": ["IVEN", "Tradex"],
        "Название": ["Changed product", "Unchanged product"],
        "OnlinerID": ["", "source-id"],
        "Ссылка": ["", "source-url"],
        "Категория": ["SSD", "SSD"],
    })
    bindings = {
        supplier_scoped_binding_key(normalize_name_key("Changed product"), "IVEN"):
            build_supplier_binding_record("manual-id", "manual-url", "IVEN"),
    }
    ensured_row_counts = []
    markup_calls = []

    def ensure_categories(df):
        ensured_row_counts.append(len(df))
        return df.copy()

    def apply_markups(df):
        markup_calls.append(len(df))
        return df.copy()

    _result, uploaded = _run_upload(
        tmp_path,
        source_df,
        bindings,
        ensure_category_column=ensure_categories,
        apply_saved_markups_to_df=apply_markups,
    )

    assert uploaded["OnlinerID"].tolist() == ["manual-id", "source-id"]
    assert ensured_row_counts == [2, 1]
    assert markup_calls == [2]
