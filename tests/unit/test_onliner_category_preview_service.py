import pandas as pd

from price_mixer.services.onliner_category_preview import (
    build_onliner_category_preview_payload,
    collect_onliner_ids,
)


def _norm_id(value):
    text = str(value or "").strip()
    return text if text and text != "nan" else ""


def _norm_cat(value):
    return str(value or "").strip()


def test_collect_onliner_ids_returns_unique_sorted_non_blank_ids():
    df = pd.DataFrame({"OnlinerID": ["42", "", "7", "42", None]})

    assert collect_onliner_ids(df, normalize_onliner_id=_norm_id) == ["42", "7"]


def test_build_onliner_category_preview_payload_counts_transitions_and_markups():
    df = pd.DataFrame([
        {"OnlinerID": "1", "Категория": "Old CPU", "Название": "CPU A"},
        {"OnlinerID": "2", "Категория": "SSD", "Название": "SSD A"},
        {"OnlinerID": "3", "Категория": "Old CPU", "Название": "CPU B"},
        {"OnlinerID": "4", "Категория": "Monitor", "Название": "Monitor A"},
        {"OnlinerID": "", "Категория": "Cable", "Название": "Cable A"},
    ])

    payload = build_onliner_category_preview_payload(
        df,
        catalog_categories={"1": "CPU", "2": "SSD", "3": "CPU"},
        markups={"CPU": {"percent": 10}},
        normalize_onliner_id=_norm_id,
        normalize_catalog_category_name=_norm_cat,
    )

    assert payload["summary"] == {
        "total": 5,
        "with_id": 4,
        "without_id": 1,
        "mapped": 3,
        "missing_catalog_category": 1,
        "changed": 2,
        "unchanged": 1,
        "categories": 2,
        "categories_without_markup": 1,
    }
    assert payload["categories"] == [
        {
            "name": "CPU",
            "count": 2,
            "changed": 2,
            "has_markup": True,
            "examples": ["CPU A", "CPU B"],
        },
        {
            "name": "SSD",
            "count": 1,
            "changed": 0,
            "has_markup": False,
            "examples": ["SSD A"],
        },
    ]
    assert payload["transitions"] == [
        {"from": "Old CPU", "to": "CPU", "count": 2, "examples": ["CPU A", "CPU B"]},
    ]


def test_build_onliner_category_preview_payload_handles_empty_frame():
    payload = build_onliner_category_preview_payload(
        pd.DataFrame(),
        catalog_categories={},
        markups={},
        normalize_onliner_id=_norm_id,
        normalize_catalog_category_name=_norm_cat,
    )

    assert payload == {"status": "ok", "summary": {}, "categories": [], "transitions": []}
