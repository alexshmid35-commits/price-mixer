"""Tests for generic N-Tech and supplier laptop review helpers."""

from price_mixer.services.ntech_review_extra import (
    build_generic_category_review_handler,
    build_supplier_laptop_review_handler,
    find_review_candidates,
)


def test_find_review_candidates_filters_duplicates_and_low_scores():
    candidates = find_review_candidates(
        "Test product",
        top_n=5,
        db_find_exact_id_for_name=lambda _name: {
            "id": "1",
            "name": "Exact",
            "score": 0.1,
            "source": "exact_db",
        },
        db_find_top_candidates=lambda *_args, **_kwargs: [
            {"id": "1", "name": "Duplicate", "score": 0.99},
            {"id": "2", "name": "Good", "score": 0.91},
            {"id": "3", "name": "Too low", "score": 0.1},
        ],
        normalize_onliner_id=lambda value: str(value or "").strip(),
    )

    assert [item["id"] for item in candidates] == ["2", "1"]
    assert candidates[1]["source"] == "exact_db"


def test_supplier_laptop_handler_builds_supplier_scoped_queue():
    is_target, build_row_result = build_supplier_laptop_review_handler(
        supplier_label="Tradex",
        is_laptop_name=lambda name, category: category == "Ноутбук",
        candidates_func=lambda _name, top_n=5: [{
            "id": "123",
            "name": "Acer Aspire",
            "score": 0.9,
            "source": "tradex_laptop_db",
        }],
        reason="tradex_laptop_manual",
        reason_label="manual",
        normalize_name_key=lambda name: name.casefold(),
        supplier_scoped_review_queue_key=lambda key, supplier: (
            f"supplier:{supplier.casefold()}:{key}"
        ),
    )

    result = build_row_result(
        7,
        {"Поставщик": "Tradex"},
        "Ноутбук Acer Aspire",
        "Ноутбук",
        123,
    )

    assert is_target({}, "Ноутбук Acer Aspire", "Ноутбук")
    assert result["action"] == "queued"
    assert result["name_key"].startswith("supplier:tradex:")
    assert result["queue_item"]["reason"] == "tradex_laptop_manual"
    assert result["queue_item"]["supplier"] == "Tradex"
    assert result["report_item"]["generic_issue"] == "queued"


def test_generic_category_handler_reports_missing_candidates():
    is_target, build_row_result = build_generic_category_review_handler(
        {"label": "ИБП", "categories": {"ИБП"}},
        normalize_catalog_category_name=lambda value: value,
        normalize_name_key=lambda name: name.casefold(),
        supplier_scoped_review_queue_key=lambda key, supplier: (
            f"{supplier.casefold()}::{key}"
        ),
        candidates_func=lambda _name, top_n=5: [],
    )

    result = build_row_result(
        4,
        {"Поставщик": "N-Tech"},
        "ИБП Test",
        "ИБП",
        321,
    )

    assert is_target({}, "ИБП Test", "ИБП")
    assert result["action"] == "no_candidates"
    assert result["report_item"]["generic_issue"] == "no_candidates"
