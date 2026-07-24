"""Unit tests for consolidated price IO helpers."""

import json
import math
import os

import numpy as np
import pandas as pd

from price_mixer.services import consolidated_io as svc


def test_has_consolidated_data_accepts_json_or_xlsx(tmp_path):
    assert svc.has_consolidated_data(tmp_path) is False

    json_path = tmp_path / "consolidated.json"
    json_path.write_text("{}", encoding="utf-8")
    assert svc.has_consolidated_data(tmp_path) is True

    json_path.unlink()
    (tmp_path / "consolidated_price.xlsx").write_text("placeholder", encoding="utf-8")
    assert svc.has_consolidated_data(tmp_path) is True


def test_safe_json_value_normalizes_common_pandas_values():
    assert svc.safe_json_value(None) == ""
    assert svc.safe_json_value(np.nan) == ""
    assert svc.safe_json_value(float("inf")) == ""
    assert svc.safe_json_value(np.float64(10.126)) == 10.13
    assert svc.safe_json_value(np.int64(7)) == 7
    assert svc.safe_json_value("  text  ") == "text"


def test_delivery_days_from_row_prefers_delivery_days_and_extracts_number():
    assert svc.delivery_days_from_row({"Дней доставки": "до 5 дней", "Под заказ": "9"}) == "5"
    assert svc.delivery_days_from_row({"Дней доставки": "", "Под заказ": "3"}) == "2"
    assert svc.delivery_days_from_row({"Под заказ": "под заказ"}) == "под заказ"


def test_write_consolidated_json_uses_safe_serializable_rows(tmp_path):
    df = pd.DataFrame({
        "OnlinerID": [" 123 "],
        "Название": ["  SSD  "],
        "Цена": [math.nan],
        "Поставщик": [" A "],
        "Гарантия": ["24"],
        "Дней доставки": ["1-2 дня"],
        "РРЦ": [np.float64(10.126)],
        "Цена без скидки": [float("inf")],
        "Категория": ["SSD"],
    })
    json_path = tmp_path / "consolidated.json"

    svc.write_consolidated_json(df, json_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload == {"data": [["123", "SSD", "", "A", "24", "1", 10.13, "", 0, "SSD"]]}
    assert svc.read_consolidated_json_rows(json_path) == payload["data"]


def test_read_consolidated_df_returns_cached_copies_and_write_invalidates_cache(tmp_path):
    svc.clear_consolidated_df_cache()
    first = pd.DataFrame({"Название": ["A"], "Цена": [1]})
    second = pd.DataFrame({"Название": ["B"], "Цена": [2]})

    svc.write_consolidated_df(tmp_path, first)
    read_first = svc.read_consolidated_df(tmp_path)
    read_first.at[0, "Название"] = "mutated"

    assert svc.read_consolidated_df(tmp_path).at[0, "Название"] == "A"

    svc.write_consolidated_df(tmp_path, second)
    read_second = svc.read_consolidated_df(tmp_path)

    assert read_second.to_dict("records") == [{"Название": "B", "Цена": 2}]


def test_read_consolidated_df_caches_json_and_invalidates_after_rewrite(tmp_path, monkeypatch):
    svc.clear_consolidated_df_cache()
    json_path = tmp_path / "consolidated.json"
    first_payload = {"data": [["1", "A", 10, "S", "", "2", "", "", 0, "C"]]}
    json_path.write_text(json.dumps(first_payload), encoding="utf-8")

    original_reader = svc.read_consolidated_json_rows
    read_count = 0

    def counted_reader(path):
        nonlocal read_count
        read_count += 1
        return original_reader(path)

    monkeypatch.setattr(svc, "read_consolidated_json_rows", counted_reader)

    first = svc.read_consolidated_df(tmp_path)
    first.iloc[0, 1] = "mutated"
    second = svc.read_consolidated_df(tmp_path)

    assert read_count == 1
    assert second.iloc[0, 1] == "A"

    old_stat = json_path.stat()
    second_payload = {"data": [["1", "B", 10, "S", "", "2", "", "", 0, "C"]]}
    json_path.write_text(json.dumps(second_payload), encoding="utf-8")
    new_stat = json_path.stat()
    if new_stat.st_mtime_ns == old_stat.st_mtime_ns:
        os.utime(
            json_path,
            ns=(new_stat.st_atime_ns, new_stat.st_mtime_ns + 1_000_000),
        )

    rewritten = svc.read_consolidated_df(tmp_path)

    assert read_count == 2
    assert rewritten.iloc[0, 1] == "B"


def test_read_consolidated_df_falls_back_to_json_when_xlsx_missing(tmp_path):
    payload = {
        "data": [
            ["5144062", "Notebook", 2450.7, "IVEN_zakaz", "12", "2", 2620, 3010, 42, "Ноутбук"],
        ],
    }
    (tmp_path / "consolidated.json").write_text(json.dumps(payload), encoding="utf-8")

    df = svc.read_consolidated_df(tmp_path)

    assert df.index.tolist() == [42]
    assert df.at[42, "OnlinerID"] == "5144062"
    assert df.at[42, "Название"] == "Notebook"
    assert df.at[42, "Поставщик"] == "IVEN_zakaz"
