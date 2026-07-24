"""Unit tests for All_Catalog ID consistency helpers."""

import json

import pandas as pd

from price_mixer.services import catalog_consistency as svc
from price_mixer.services.product_normalization import normalize_onliner_id


def lookup(name):
    mapping = {
        "Set missing": ("100", "https://100.test"),
        "Correct conflict": ("200", "https://200.test"),
        "Already ok": ("300", "https://300.test"),
    }
    return mapping.get(str(name), ("", ""))


def test_reconcile_ids_from_catalog_sets_and_corrects_ids():
    df = pd.DataFrame({
        "Название": ["Set missing", "Correct conflict", "Already ok", "Unknown"],
        "OnlinerID": ["", "old", "300", ""],
    })

    corrected = svc.reconcile_ids_from_catalog(
        df,
        lookup_id_from_catalog_sheet=lookup,
        normalize_onliner_id=normalize_onliner_id,
    )

    assert corrected == 2
    assert list(df["OnlinerID"]) == ["100", "200", "300", ""]
    assert list(df["Ссылка"]) == ["https://100.test", "https://200.test", "https://300.test", ""]


def test_enforce_catalog_consistency_corrects_sets_and_clears_ids(tmp_path):
    saved = {}

    def save_summary(path, payload):
        saved[str(path)] = payload
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    df = pd.DataFrame({
        "Поставщик": ["A", "B", "C", "D"],
        "Название": ["Set missing", "Correct conflict", "No catalog article", "Plain item"],
        "OnlinerID": ["", "old", "777", "888"],
    })

    summary = svc.enforce_catalog_consistency(
        df,
        session_dir=tmp_path,
        lookup_id_from_catalog_sheet=lookup,
        normalize_onliner_id=normalize_onliner_id,
        get_article_from_name=lambda name: "ART" if "article" in str(name).lower() else "",
        save_summary=save_summary,
    )

    assert summary == {
        "checked": 4,
        "set_from_catalog": 1,
        "corrected_conflicts": 1,
        "cleared_unverified": 1,
        "report_rows": 2,
    }
    assert list(df["OnlinerID"]) == ["100", "200", "", "888"]
    assert list(df["Ссылка"]) == ["https://100.test", "https://200.test", "", ""]
    assert (tmp_path / "id_quality_report.csv").exists()
    assert saved[str(tmp_path / "id_quality_report.json")]["report_rows"] == 2


def test_enforce_catalog_consistency_returns_empty_summary_without_id_column():
    df = pd.DataFrame({"Название": ["Item"]})

    assert svc.enforce_catalog_consistency(df) == {
        "checked": 0,
        "set_from_catalog": 0,
        "corrected_conflicts": 0,
        "cleared_unverified": 0,
        "report_rows": 0,
    }
