import pandas as pd

from price_mixer.services.review_queue import (
    build_list_items,
    match_name_key,
    migrate_supplier_scope,
    supplier_scoped_key,
    unique_supplier_names,
)


def _normalize(value):
    return str(value or "").strip().casefold()


def test_supplier_helpers_preserve_supplier_scope_and_legacy_reasons():
    assert supplier_scoped_key("same product", "N-Tech") == (
        "supplier:n_tech:same product"
    )
    assert unique_supplier_names({"suppliers": ["IVEN", "Tradex", "IVEN"]}) == [
        "IVEN",
        "Tradex",
    ]
    assert unique_supplier_names({"reason": "iven_zakaz_laptop_manual"}) == [
        "IVEN_zakaz"
    ]
    assert match_name_key(
        "supplier:tradex:same product",
        {"match_name_key": "same product"},
    ) == "same product"


def test_migrate_supplier_scope_keeps_existing_scoped_decision():
    queue = {
        "same product": {
            "name": "Same Product",
            "supplier": "Tradex",
            "candidates": [{"id": "legacy"}],
        },
        "supplier:tradex:same product": {
            "name": "Same Product",
            "match_name_key": "same product",
            "supplier": "Tradex",
            "candidates": [{"id": "current"}],
        },
    }

    migrated, changed = migrate_supplier_scope(queue)

    assert changed is True
    assert "same product" not in migrated
    assert migrated["supplier:tradex:same product"]["candidates"] == [
        {"id": "current"}
    ]


def test_build_list_items_resolves_rows_per_supplier_and_removes_only_stale():
    frame = pd.DataFrame(
        [
            {
                "Поставщик": "Tradex",
                "Название": "Same Product",
                "OnlinerID": "111",
            },
            {
                "Поставщик": "N-Tech",
                "Название": "Same Product",
                "OnlinerID": "",
            },
        ]
    )
    queue = {
        "supplier:tradex:same product": {
            "name": "Same Product",
            "match_name_key": "same product",
            "supplier": "Tradex",
            "added_at": 10,
        },
        "supplier:n_tech:same product": {
            "name": "Same Product",
            "match_name_key": "same product",
            "supplier": "N-Tech",
            "added_at": 20,
        },
    }

    items, stale_keys = build_list_items(
        queue,
        frame,
        normalize_name_key=_normalize,
        normalize_onliner_id=lambda value: str(value or "").strip(),
    )

    assert stale_keys == {"supplier:tradex:same product"}
    assert [item["name_key"] for item in items] == [
        "supplier:n_tech:same product"
    ]
    assert items[0]["row_idx"] == 1
