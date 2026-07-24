"""Unit tests for category markup/config service helpers."""

import math

import pandas as pd

from price_mixer.services import category_config
from price_mixer.services.category_config import (
    apply_markup_to_df,
    build_markup_preview_payload,
    calc_rrc_and_no_discount,
    get_category_markup_config,
    load_category_overrides,
    load_manual_category_overrides,
    load_category_markups,
    parse_markup_request,
    save_category_overrides,
    save_manual_category_overrides,
    save_category_markups,
    update_markups_for_categories,
)


def test_get_category_markup_config_accepts_legacy_numeric_value():
    cfg = get_category_markup_config({"SSD": "12.5"}, "SSD")

    assert cfg == {
        "percent": 12.5,
        "threshold": 0.0,
        "min_profit": 0.0,
        "no_discount_percent": 0.0,
        "base_mode": "wholesale",
    }


def test_get_category_markup_config_clamps_invalid_dict_fields():
    cfg = get_category_markup_config({
        "SSD": {
            "percent": "bad",
            "threshold": -10,
            "min_profit": "15",
            "no_discount_percent": -5,
            "base_mode": "unknown",
        },
    }, "SSD")

    assert cfg == {
        "percent": 0.0,
        "threshold": 0.0,
        "min_profit": 15.0,
        "no_discount_percent": 0.0,
        "base_mode": "wholesale",
    }


def test_calc_rrc_and_no_discount_uses_min_profit_threshold_and_rounding():
    rrc, no_discount = calc_rrc_and_no_discount(
        100,
        10,
        threshold=150,
        min_profit=25,
        no_discount_percent=10,
    )

    assert rrc == 130.0
    assert no_discount == 140.0


def test_calc_rrc_and_no_discount_returns_nan_for_bad_price():
    rrc, no_discount = calc_rrc_and_no_discount("bad", 10)

    assert math.isnan(rrc)
    assert math.isnan(no_discount)


def test_category_markups_round_trip(tmp_path, monkeypatch):
    markups_file = tmp_path / "category_markups.json"
    monkeypatch.setattr(category_config, "CATEGORY_MARKUPS_FILE", markups_file)

    save_category_markups({"SSD": {"percent": 10}})

    assert load_category_markups() == {"SSD": {"percent": 10}}


def test_load_category_markups_prefers_canonical_category_over_legacy_alias(tmp_path, monkeypatch):
    markups_file = tmp_path / "category_markups.json"
    monkeypatch.setattr(category_config, "CATEGORY_MARKUPS_FILE", markups_file)
    markups_file.write_text(
        """
        {
          "USB2": {"percent": 0, "threshold": 200, "min_profit": 15},
          "Накопители USB": {"percent": 20, "threshold": 100, "min_profit": 15}
        }
        """,
        encoding="utf-8",
    )

    markups = load_category_markups()

    assert markups["Накопители USB"]["percent"] == 20


def test_category_overrides_round_trip_uses_json_and_cleans_suspicious(tmp_path, monkeypatch):
    overrides_file = tmp_path / "category_overrides.json"
    manual_overrides_file = tmp_path / "manual_category_overrides.json"
    monkeypatch.setattr(category_config, "CATEGORY_OVERRIDES_FILE", overrides_file)
    monkeypatch.setattr(category_config, "MANUAL_CATEGORY_OVERRIDES_FILE", manual_overrides_file)

    save_category_overrides({
        "Fast SSD": "SSD",
        "art:123": "SSD",
        "Cooler case": "Блок питания",
    })

    assert load_category_overrides() == {"Fast SSD": "SSD"}


def test_manual_category_overrides_are_merged_with_highest_priority(tmp_path, monkeypatch):
    overrides_file = tmp_path / "category_overrides.json"
    manual_overrides_file = tmp_path / "manual_category_overrides.json"
    monkeypatch.setattr(category_config, "CATEGORY_OVERRIDES_FILE", overrides_file)
    monkeypatch.setattr(category_config, "MANUAL_CATEGORY_OVERRIDES_FILE", manual_overrides_file)

    save_category_overrides({"name:item": "Автоматическая"})
    save_manual_category_overrides({"name:item": "Ручная"})

    assert load_manual_category_overrides() == {"name:item": "Ручная"}
    assert load_category_overrides() == {"name:item": "Ручная"}


def test_parse_markup_request_validates_and_normalizes_payload():
    cfg, error = parse_markup_request({
        "categories": [" SSD ", ""],
        "percent": "12.5",
        "threshold": "100",
        "min_profit": "20",
        "no_discount_percent": "5",
        "base_mode": "onliner_min",
    })

    assert error == ""
    assert cfg == {
        "categories": ["SSD"],
        "percent": 12.5,
        "threshold": 100.0,
        "min_profit": 20.0,
        "no_discount_percent": 5.0,
        "base_mode": "onliner_min",
    }

    cfg, error = parse_markup_request({"categories": ["SSD"], "percent": "-1"})
    assert cfg is None
    assert error == "Процент не может быть отрицательным"


def test_apply_markup_to_df_updates_selected_categories_from_market_base():
    df = pd.DataFrame({
        "Название": ["Fast SSD", "Gaming Mouse"],
        "Категория": ["SSD", "Мышь"],
        "Цена": [100, 50],
        "OnlinerID": ["111", "222"],
    })
    calls = {}

    def market_stats(ids, max_workers=None, id_hints=None):
        calls["ids"] = ids
        calls["id_hints"] = id_hints
        return {"111": {"min": 200}}

    updated, result = apply_markup_to_df(
        df,
        {
            "categories": ["SSD"],
            "percent": 10,
            "threshold": 0,
            "min_profit": 0,
            "no_discount_percent": 5,
            "base_mode": "onliner_min",
        },
        row_category=lambda row: row.get("Категория", ""),
        normalize_onliner_id=lambda value: str(value or "").strip(),
        get_onliner_market_stats_bulk=market_stats,
    )

    assert result["status"] == "ok"
    assert result["updated"] == 1
    assert result["eligible"] == 1
    assert result["market_checked"] == 1
    assert calls["ids"] == ["111"]
    assert updated.loc[0, "РРЦ"] == 220.0
    assert updated.loc[0, "Цена без скидки"] == 230.0
    assert updated.loc[1, "РРЦ"] == ""


def test_update_markups_for_categories_persists_full_config():
    result = update_markups_for_categories(
        {"Мышь": {"percent": 5}},
        {
            "categories": ["SSD"],
            "percent": 10,
            "threshold": 100,
            "min_profit": 20,
            "no_discount_percent": 5,
            "base_mode": "wholesale",
        },
    )

    assert result["SSD"] == {
        "percent": 10,
        "threshold": 100,
        "min_profit": 20,
        "no_discount_percent": 5,
        "base_mode": "wholesale",
    }
    assert result["Мышь"] == {"percent": 5}


def test_build_markup_preview_payload_limits_selected_rows():
    df = pd.DataFrame({
        "Название": ["Fast SSD", "Gaming Mouse"],
        "Категория": ["SSD", "Мышь"],
        "Цена": [100, 50],
        "РРЦ": [110, ""],
    })

    payload = build_markup_preview_payload(
        df,
        {"categories": ["SSD"], "percent": 20, "limit": 5},
        row_category=lambda row: row.get("Категория", ""),
    )

    assert payload == {
        "items": [{
            "category": "SSD",
            "name": "Fast SSD",
            "price": 100.0,
            "old_rrc": 110.0,
            "new_rrc": 120.0,
        }]
    }
