from price_mixer.services.category_repair_runtime import (
    CategoryRepairRuntime,
    json_row_needs_category_repair,
)


def test_json_row_repair_detects_known_misclassification():
    def needs_repair(name, raw, current):
        return json_row_needs_category_repair(
            name,
            raw,
            current,
            normalize_internal_category_name=lambda value: value,
            canonical_ui_category_name=lambda value: value,
            normalize_catalog_category_name=lambda value: value,
            infer_category=lambda _name: "Кронштейны",
            should_repair_catalog_category=lambda current, inferred: (current != inferred),
        )

    assert needs_repair("Кронштейн для монитора", "Монитор", "Монитор")
    assert not needs_repair("Кронштейн", "Кронштейны", "Кронштейны")


def test_category_repair_prefers_catalog_category_and_visibility(tmp_path):
    rows = [["12", "Product", 1, "IVEN", 12, 2, 1, 1, 0, "RAW"]]
    cache = {}
    runtime = CategoryRepairRuntime(
        read_rows=lambda *_args, **_kwargs: rows,
        compatibility_rows_reader=lambda _path: rows,
        cache_key=lambda _session, _path, visible: ("key", visible),
        get_cached_rows=cache.get,
        set_cached_rows=lambda key, value: cache.__setitem__(key, value),
        load_visibility_map=lambda _session: {"*": ["Монитор"]},
        canonical_ui_category_name=lambda value: str(value),
        get_categories_by_ids=lambda _ids: {"12": "Монитор"},
        get_categories_by_exact_names=lambda _names: {},
        load_category_overrides=lambda: {},
        load_manual_category_overrides=lambda: {},
        supplier_visibility_known_categories=lambda: set(),
        normalize_internal_category_name=lambda value: str(value),
        repair_saved_category_for_product=lambda category, _name: category,
        category_override_for_row=lambda _row, _overrides: "",
        looks_like_raw_supplier_category=lambda value: value == "RAW",
        normalize_onliner_id=lambda value: str(value),
        native_catalog_category_for_product=lambda value, _name: value,
        normalize_name_key=lambda value: str(value).casefold(),
        raw_supplier_inferred_category_for_product=lambda *_args: "",
        strong_inferred_category_for_product=lambda _name: "",
        sorting_review_category=lambda value: f"sort:{value}",
        json_row_needs_repair=lambda *_args: False,
        row_category=lambda row, **_kwargs: row["Категория"],
        build_item_category_keys=lambda _row: [],
        infer_category=lambda _name: "",
    )

    full = runtime.correct_rows(tmp_path, apply_visibility=False)
    visible = runtime.correct_rows(tmp_path, apply_visibility=True)

    assert full[0][9] == "Монитор"
    assert visible == []
    assert runtime.correct_rows(tmp_path, apply_visibility=False) is full
