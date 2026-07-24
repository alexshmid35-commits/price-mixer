"""Consolidated price DataFrame and JSON persistence helpers."""

import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from price_mixer.product_schema import ProductField, ProductWireIndex


_CONSOLIDATED_IO_LOCK = threading.RLock()
_CONS_DF_CACHE = {}  # {path_str: (mtime, df)}


def has_consolidated_data(session_dir):
    if not session_dir:
        return False
    session_path = Path(session_dir)
    return (session_path / "consolidated.json").exists() or (
        session_path / "consolidated_price.xlsx"
    ).exists()


def safe_json_value(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    if isinstance(value, (np.floating, float)):
        fv = float(value)
        if not math.isfinite(fv):
            return ""
        return round(fv, 2)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def delivery_days_from_row(row):
    value = row.get("Дней доставки", row.get("Под заказ", "2"))
    value = safe_json_value(value)
    text = str(value).strip()
    if not text:
        return "2"
    match = re.search(r"(\d+)", text)
    if match:
        return match.group(1)
    return text


def consolidated_json_rows(df):
    rows = []
    for index, row in df.iterrows():
        rows.append([
            safe_json_value(row.get(ProductField.ONLINER_ID, "")),
            safe_json_value(row.get(ProductField.NAME, "")),
            safe_json_value(row.get(ProductField.PRICE, 0)),
            safe_json_value(row.get(ProductField.SUPPLIER, "")),
            safe_json_value(row.get(ProductField.WARRANTY, "")),
            delivery_days_from_row(row),
            safe_json_value(row.get(ProductField.RRC, "")),
            safe_json_value(row.get(ProductField.NO_DISCOUNT, "")),
            int(index),
            safe_json_value(row.get(ProductField.CATEGORY, "")),
        ])
    return rows


def write_consolidated_json(df, json_path):
    write_consolidated_json_rows(consolidated_json_rows(df), json_path)


def write_consolidated_json_rows(rows, json_path):
    json_path = Path(json_path)
    payload = {"data": [list(row) for row in rows or []]}
    tmp_path = None
    with _CONSOLIDATED_IO_LOCK:
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=json_path.parent,
                prefix=json_path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as f:
                tmp_path = Path(f.name)
                json.dump(payload, f, ensure_ascii=False, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, json_path)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


def read_consolidated_json_rows(json_path):
    with open(str(json_path), "r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, list)]


def dataframe_from_consolidated_json_rows(rows):
    records = []
    index = []
    for pos, row in enumerate(rows or []):
        if not isinstance(row, list):
            continue
        padded = list(row) + [""] * max(0, 10 - len(row))
        try:
            row_index = int(padded[ProductWireIndex.ROW_INDEX])
        except Exception:
            row_index = pos
        index.append(row_index)
        records.append({
            ProductField.ONLINER_ID: safe_json_value(padded[ProductWireIndex.ONLINER_ID]),
            ProductField.NAME: safe_json_value(padded[ProductWireIndex.NAME]),
            ProductField.PRICE: safe_json_value(padded[ProductWireIndex.PRICE]),
            ProductField.SUPPLIER: safe_json_value(padded[ProductWireIndex.SUPPLIER]),
            ProductField.WARRANTY: safe_json_value(padded[ProductWireIndex.WARRANTY]),
            ProductField.DELIVERY_DAYS: safe_json_value(padded[ProductWireIndex.DELIVERY_DAYS]),
            ProductField.RRC: safe_json_value(padded[ProductWireIndex.RRC]),
            ProductField.NO_DISCOUNT: safe_json_value(padded[ProductWireIndex.NO_DISCOUNT]),
            ProductField.CATEGORY: safe_json_value(padded[ProductWireIndex.CATEGORY]),
        })
    return pd.DataFrame(records, index=index)


def read_consolidated_df(session_dir, filename="consolidated_price.xlsx"):
    cons_path = Path(session_dir) / filename
    with _CONSOLIDATED_IO_LOCK:
        json_path = Path(session_dir) / "consolidated.json"
        source_path = cons_path if cons_path.exists() else json_path
        try:
            mtime = source_path.stat().st_mtime_ns
        except OSError:
            mtime = None
        cache_key = str(source_path)
        cached = _CONS_DF_CACHE.get(cache_key)
        if cached and cached[0] == mtime and mtime is not None:
            return cached[1].copy()
        if source_path == json_path and mtime is not None:
            df = dataframe_from_consolidated_json_rows(read_consolidated_json_rows(json_path))
            _CONS_DF_CACHE[cache_key] = (mtime, df)
            return df.copy()
        df = pd.read_excel(cons_path)
        _CONS_DF_CACHE[cache_key] = (mtime, df)
        return df.copy()


def write_consolidated_df(session_dir, df, filename="consolidated_price.xlsx"):
    session_path = Path(session_dir)
    cons_path = session_path / filename
    tmp_path = session_path / (Path(filename).stem + ".tmp" + Path(filename).suffix)
    with _CONSOLIDATED_IO_LOCK:
        df.to_excel(tmp_path, index=False)
        os.replace(tmp_path, cons_path)
        try:
            _CONS_DF_CACHE[str(cons_path)] = (cons_path.stat().st_mtime, df.copy())
        except OSError:
            _CONS_DF_CACHE.pop(str(cons_path), None)


def clear_consolidated_df_cache():
    with _CONSOLIDATED_IO_LOCK:
        _CONS_DF_CACHE.clear()
