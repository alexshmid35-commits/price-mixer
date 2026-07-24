import pandas as pd

from price_mixer.services.quality_pipeline import (
    apply_quality_visibility_filter,
    count_suspicious_price_rows_from_json,
    hidden_categories_from_visibility_map,
)


def test_quality_visibility_filter_suppresses_globally_hidden_categories():
    df = pd.DataFrame({
        "Поставщик": ["N-Tech", "N-Tech"],
        "Название": ["UPS battery", "Mouse"],
        "Категория": ["АККУМУЛЯТОРНАЯ", "Мышь"],
    })

    result = apply_quality_visibility_filter(
        df,
        "/tmp/session",
        apply_visibility_filter=lambda frame, session_dir: frame,
        load_visibility_map=lambda session_dir: {"IVEN": ["АККУМУЛЯТОР"]},
        normalize_category=lambda value: str(value).replace("НАЯ", "").upper(),
    )

    assert list(result["Название"]) == ["Mouse"]


def test_quality_visibility_filter_keeps_frame_when_category_column_is_missing():
    df = pd.DataFrame({"Название": ["Mouse"]})

    result = apply_quality_visibility_filter(
        df,
        "/tmp/session",
        apply_visibility_filter=lambda frame, session_dir: frame,
        load_visibility_map=lambda session_dir: {"IVEN": ["МЫШЬ"]},
        normalize_category=lambda value: str(value).upper(),
    )

    assert result is df


def test_hidden_categories_from_visibility_map_normalizes_and_drops_blank_values():
    result = hidden_categories_from_visibility_map(
        {"A": [" ssd ", ""], "B": ["Мышь"]},
        normalize_category=lambda value: str(value).strip().upper(),
    )

    assert result == {"SSD", "МЫШЬ"}


def test_count_suspicious_price_rows_from_json_skips_hidden_categories():
    rows = [
        ["1", "Hidden bad margin", "100", "A", "", "", "90", "", 0, "SSD"],
        ["2", "Visible bad margin", "100", "A", "", "", "103", "", 1, "Мышь"],
        ["3", "Visible good margin", "100", "A", "", "", "130", "", 2, "RAM"],
        ["4", "Visible invalid price", "", "A", "", "", "130", "", 3, "Клавиатура"],
    ]

    result = count_suspicious_price_rows_from_json(
        rows,
        hidden_categories={"SSD"},
        normalize_category=lambda value: str(value).strip().upper(),
    )

    assert result == 2


def test_count_suspicious_price_rows_from_json_can_match_export_filters():
    rows = [
        ["", "Without id", "100", "A", "", "", "90", "", 0, "SSD"],
        ["2", "Review category", "100", "A", "", "", "90", "", 1, "Требует сортировки · родитель: SSD"],
        ["3", "Outside structure", "100", "A", "", "", "90", "", 2, "Кухонные плиты"],
        ["4", "Exported suspicious", "100", "A", "", "", "103", "", 3, "SSD"],
        ["5", "Exported ok", "100", "A", "", "", "130", "", 4, "Мышь"],
    ]

    result = count_suspicious_price_rows_from_json(
        rows,
        normalize_category=lambda value: str(value).strip(),
        allowed_categories=["SSD", "Мышь"],
        exclude_category_prefixes=["Требует сортировки · родитель:"],
        require_onliner_id=True,
        has_onliner_id=lambda value: bool(str(value or "").strip()),
    )

    assert result == 1
