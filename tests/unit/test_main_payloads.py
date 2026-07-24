"""Unit tests for main endpoint payload builders."""

import numpy as np
import pandas as pd

from price_mixer.services import main_payloads as svc
from price_mixer.services.consolidated_io import delivery_days_from_row, safe_json_value


def test_build_consolidated_table_rows_keeps_frontend_column_order():
    df = pd.DataFrame({
        "OnlinerID": [" 123 "],
        "Название": [" SSD "],
        "Цена": [10.126],
        "Поставщик": ["A"],
        "Гарантия": ["24"],
        "Дней доставки": ["до 5 дней"],
        "РРЦ": [20],
        "Цена без скидки": [np.nan],
        "Категория": ["SSD"],
    }, index=[7])

    rows = svc.build_consolidated_table_rows(
        df,
        safe_json_value=safe_json_value,
        delivery_days_from_row=delivery_days_from_row,
        row_category=lambda row: row.get("Категория", ""),
    )

    assert rows == [["123", "SSD", 10.13, "A", "24", "5", 20, "", 7, "SSD"]]


def test_build_consolidated_table_rows_handles_missing_optional_columns():
    df = pd.DataFrame({"Название": ["Mouse"]})

    rows = svc.build_consolidated_table_rows(
        df,
        safe_json_value=safe_json_value,
        delivery_days_from_row=delivery_days_from_row,
        row_category=lambda row: "Мышь",
    )

    assert rows == [["", "Mouse", 0, "", "", "2", "", "", 0, "Мышь"]]


def test_build_stats_payload_uses_injected_counters():
    df = pd.DataFrame({"OnlinerID": ["1", "", "1"]})

    assert svc.build_stats_payload(
        df,
        count_without_onliner_id=lambda frame: 1,
        count_duplicate_onliner_id=lambda frame: 2,
        export_row_count=7,
    ) == {"without_id": 1, "duplicate_id_rows": 2, "export_rows": 7}


def test_empty_stats_payload():
    assert svc.empty_stats_payload() == {"without_id": 0, "duplicate_id_rows": 0, "export_rows": 0}
