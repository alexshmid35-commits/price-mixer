"""Category override, markup, and pricing configuration helpers."""

import copy
import re
import threading
from pathlib import Path

from price_mixer.runtime_paths import get_runtime_paths
import numpy as np
import pandas as pd

from price_mixer.services.product_normalization import normalize_internal_category_name, round_price_to_90
from price_mixer.services.category_state_store import (
    CATEGORY_MARKUPS_STATE,
    CATEGORY_OVERRIDES_STATE,
    MANUAL_CATEGORY_OVERRIDES_STATE,
    category_state_signature,
    load_category_state,
    save_category_state,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATHS = get_runtime_paths()
DEFAULT_CATEGORY_MARKUPS_FILE = RUNTIME_PATHS.state_file("category_markups.json")
DEFAULT_CATEGORY_OVERRIDES_FILE = RUNTIME_PATHS.state_file("category_overrides.json")
DEFAULT_MANUAL_CATEGORY_OVERRIDES_FILE = RUNTIME_PATHS.state_file("manual_category_overrides.json")
CATEGORY_MARKUPS_FILE = DEFAULT_CATEGORY_MARKUPS_FILE
CATEGORY_OVERRIDES_FILE = DEFAULT_CATEGORY_OVERRIDES_FILE
MANUAL_CATEGORY_OVERRIDES_FILE = DEFAULT_MANUAL_CATEGORY_OVERRIDES_FILE
_NORMALIZED_STATE_CACHE = {}
_NORMALIZED_STATE_CACHE_LOCK = threading.RLock()

CATEGORY_MARKUP_FALLBACKS = {
    "Кулеры": "Кулер",
    "Принтеры": "Принтер и МФУ",
    "Компьютеры": "Системный блок",
    "Системные блоки": "Системный блок",
    "Моноблоки": "Системный блок",
    "Картриджи": "КАРТРИДЖ",
    "Сумки и чехлы для ноутбуков": "СУМКА",
    "Стабилизаторы и сетевые фильтры": "Сеть",
    "Портативные колонки": "Акустика",
    "Умные часы": "Аксессуары",
    "Планшеты": "Аксессуары",
    "Коммутаторы": "Сеть",
    "Коврики для мыши": "КОВРИК",
    "Карты памяти": "Аксессуары",
    "USB-хабы": "Аксессуары",
    "Wi-Fi роутеры": "Сеть",
    "Внешние накопители": "Жесткий диск",
    "Саундбары": "Акустика",
    "Комплекты периферии": "Периферия",
    "Точки доступа Wi-Fi": "Сеть",
    "Беспроводные адаптеры": "Сеть",
    "Боксы для накопителей": "Аксессуары",
    "Термопасты и термопрокладки": "Охлаждение",
    "Веб-камеры": "Периферия",
    "Моддинг ПК": "Аксессуары",
    "Картридеры": "Аксессуары",
    "Аксессуары для наушников": "Наушники",
    "Игровые приставки": "Аксессуары",
    "Чистящие средства": "Аксессуары",
    "Сетевые адаптеры": "Сеть",
    "DSL-модемы": "Сеть",
    "Звуковые карты": "Акустика",
    "Оптические приводы": "Аксессуары",
    "Автомобильные держатели": "Аксессуары",
}


def load_category_overrides():
    overrides = _load_normalized_state(
        CATEGORY_OVERRIDES_STATE,
        CATEGORY_OVERRIDES_FILE,
        DEFAULT_CATEGORY_OVERRIDES_FILE,
        _clean_category_overrides,
    )
    overrides.update(load_manual_category_overrides())
    return overrides


def save_category_overrides(overrides):
    save_category_state(
        _clean_category_overrides(overrides),
        CATEGORY_OVERRIDES_STATE,
        CATEGORY_OVERRIDES_FILE,
        sqlite_primary=Path(CATEGORY_OVERRIDES_FILE) == DEFAULT_CATEGORY_OVERRIDES_FILE,
    )
    _clear_normalized_state_cache(CATEGORY_OVERRIDES_STATE)


def load_manual_category_overrides():
    return _load_normalized_state(
        MANUAL_CATEGORY_OVERRIDES_STATE,
        MANUAL_CATEGORY_OVERRIDES_FILE,
        DEFAULT_MANUAL_CATEGORY_OVERRIDES_FILE,
        _clean_category_overrides,
    )


def save_manual_category_overrides(overrides):
    save_category_state(
        _clean_category_overrides(overrides),
        MANUAL_CATEGORY_OVERRIDES_STATE,
        MANUAL_CATEGORY_OVERRIDES_FILE,
        sqlite_primary=Path(MANUAL_CATEGORY_OVERRIDES_FILE) == DEFAULT_MANUAL_CATEGORY_OVERRIDES_FILE,
    )
    _clear_normalized_state_cache(MANUAL_CATEGORY_OVERRIDES_STATE)


def _clean_category_overrides(data):
    if not isinstance(data, dict):
        return {}
    cleaned = {
        k: normalize_internal_category_name(v)
        for k, v in data.items()
        if not str(k).startswith("art:")
    }
    suspicious = []
    for key, value in cleaned.items():
        key_text = str(key or "").lower()
        value_text = str(value or "").strip()
        if value_text == "Блок питания":
            if re.search(r"\bкорпус\b|\bcase\b|\bкулер\b|cooler|охлажден|сжо|водян|fan", key_text):
                suspicious.append(key)
    for key in suspicious:
        cleaned.pop(key, None)
    return cleaned


def load_category_markups():
    return _load_normalized_state(
        CATEGORY_MARKUPS_STATE,
        CATEGORY_MARKUPS_FILE,
        DEFAULT_CATEGORY_MARKUPS_FILE,
        _normalize_category_markups,
        deep_copy=True,
    )


def _normalize_category_markups(data):
    if not isinstance(data, dict):
        return {}
    normalized = {}
    source_is_exact = {}
    for category, config in data.items():
        canonical = normalize_internal_category_name(category)
        if not canonical:
            continue
        is_exact = str(category or "").strip() == canonical
        if canonical not in normalized or (is_exact and not source_is_exact.get(canonical, False)):
            normalized[canonical] = config
            source_is_exact[canonical] = is_exact
    for target, source in CATEGORY_MARKUP_FALLBACKS.items():
        if target not in normalized and source in normalized:
            normalized[target] = normalized[source]
    return normalized


def save_category_markups(markups):
    normalized = {}
    for category, config in dict(markups or {}).items():
        canonical = normalize_internal_category_name(category)
        if canonical:
            normalized[canonical] = config
    save_category_state(
        normalized,
        CATEGORY_MARKUPS_STATE,
        CATEGORY_MARKUPS_FILE,
        sqlite_primary=Path(CATEGORY_MARKUPS_FILE) == DEFAULT_CATEGORY_MARKUPS_FILE,
    )
    _clear_normalized_state_cache(CATEGORY_MARKUPS_STATE)


def _load_normalized_state(state_key, path, default_path, normalizer, *, deep_copy=False):
    sqlite_primary = Path(path) == Path(default_path)
    if not sqlite_primary:
        return normalizer(load_category_state(state_key, path, sqlite_primary=False))

    signature = category_state_signature([state_key])
    with _NORMALIZED_STATE_CACHE_LOCK:
        cached = _NORMALIZED_STATE_CACHE.get(state_key)
        if cached is not None and cached[0] == signature:
            return copy.deepcopy(cached[1]) if deep_copy else dict(cached[1])

    normalized = normalizer(load_category_state(state_key, path, sqlite_primary=True))
    with _NORMALIZED_STATE_CACHE_LOCK:
        _NORMALIZED_STATE_CACHE[state_key] = (signature, copy.deepcopy(normalized))
    return copy.deepcopy(normalized) if deep_copy else dict(normalized)


def _clear_normalized_state_cache(state_key):
    with _NORMALIZED_STATE_CACHE_LOCK:
        _NORMALIZED_STATE_CACHE.pop(state_key, None)


def get_category_markup_config(markups, category):
    raw = (markups or {}).get(category)
    if isinstance(raw, dict):
        try:
            percent = float(raw.get("percent", 0))
        except Exception:
            percent = 0.0
        try:
            threshold = float(raw.get("threshold", 0))
        except Exception:
            threshold = 0.0
        try:
            min_profit = float(raw.get("min_profit", 0))
        except Exception:
            min_profit = 0.0
        try:
            no_discount_percent = float(raw.get("no_discount_percent", 0))
        except Exception:
            no_discount_percent = 0.0
        base_mode = str(raw.get("base_mode", "wholesale")).strip().lower()
    else:
        try:
            percent = float(raw)
        except Exception:
            percent = 0.0
        threshold = 0.0
        min_profit = 0.0
        no_discount_percent = 0.0
        base_mode = "wholesale"
    if base_mode not in {"wholesale", "onliner_min", "onliner_avg", "onliner_max"}:
        base_mode = "wholesale"
    return {
        "percent": percent,
        "threshold": max(0.0, threshold),
        "min_profit": max(0.0, min_profit),
        "no_discount_percent": max(0.0, no_discount_percent),
        "base_mode": base_mode,
    }


def calc_rrc_and_no_discount(base_price, percent, threshold=0.0, min_profit=0.0, no_discount_percent=0.0):
    base_price = pd.to_numeric(base_price, errors="coerce")
    if pd.isna(base_price):
        return np.nan, np.nan
    base_price = float(base_price)
    percent = max(0.0, float(percent or 0.0))
    threshold = max(0.0, float(threshold or 0.0))
    min_profit = max(0.0, float(min_profit or 0.0))
    no_discount_percent = max(0.0, float(no_discount_percent or 0.0))

    calc_rrc = base_price * (1.0 + percent / 100.0)
    if base_price <= threshold and threshold > 0:
        calc_rrc = max(calc_rrc, base_price + min_profit)
    rrc = round_price_to_90(calc_rrc)

    no_discount_price = np.nan
    if not pd.isna(rrc):
        no_discount_price = round_price_to_90(float(rrc) * (1.0 + no_discount_percent / 100.0))

    return rrc, no_discount_price


def parse_markup_request(payload):
    payload = payload or {}
    categories = payload.get("categories", [])
    if not isinstance(categories, list) or not categories:
        return None, "Категории не выбраны"

    parsed = {
        "categories": [str(category).strip() for category in categories if str(category).strip()],
        "base_mode": str(payload.get("base_mode", "wholesale")).strip().lower(),
    }
    if parsed["base_mode"] not in {"wholesale", "onliner_min", "onliner_avg", "onliner_max"}:
        parsed["base_mode"] = "wholesale"
    if not parsed["categories"]:
        return None, "Категории не выбраны"

    fields = [
        ("percent", "Некорректный процент", "Процент не может быть отрицательным"),
        ("threshold", "Некорректный порог опта", "Порог опта не может быть отрицательным"),
        ("min_profit", "Некорректная мин. прибыль", "Мин. прибыль не может быть отрицательной"),
        ("no_discount_percent", "Некорректный процент для цены без скидки", "Процент цены без скидки не может быть отрицательным"),
    ]
    defaults = {
        "percent": None,
        "threshold": 0,
        "min_profit": 0,
        "no_discount_percent": 0,
    }
    for field, invalid_message, negative_message in fields:
        try:
            value = float(payload.get(field, defaults[field]))
        except Exception:
            return None, invalid_message
        if value < 0:
            return None, negative_message
        parsed[field] = value
    return parsed, ""


def apply_markup_to_df(
    df,
    markup_cfg,
    *,
    row_category,
    normalize_onliner_id,
    get_onliner_market_stats_bulk=None,
    market_max_ids=400,
    market_max_workers=22,
):
    if "Название" not in df.columns or "Цена" not in df.columns:
        return df, {"status": "error", "message": "В файле нет нужных колонок"}

    df = df.copy()
    if "РРЦ" not in df.columns:
        df["РРЦ"] = ""
    if "Цена без скидки" not in df.columns:
        df["Цена без скидки"] = ""
    df["РРЦ"] = df["РРЦ"].astype("object")
    df["Цена без скидки"] = df["Цена без скидки"].astype("object")

    selected = set(markup_cfg["categories"])
    base_mode = str(markup_cfg.get("base_mode", "wholesale")).strip().lower()
    market_map = {}
    market_checked = 0
    if base_mode in {"onliner_min", "onliner_avg", "onliner_max"} and callable(get_onliner_market_stats_bulk):
        ids = []
        id_hints_bulk = {}
        for _, row in df.iterrows():
            category = row_category(row)
            if category not in selected:
                continue
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if oid:
                ids.append(oid)
                if oid not in id_hints_bulk:
                    id_hints_bulk[oid] = {
                        "name": str(row.get("Название", "") or ""),
                        "category": category,
                    }
        unique_ids = list(dict.fromkeys(ids))[: int(market_max_ids)]
        market_checked = len(unique_ids)
        market_map = get_onliner_market_stats_bulk(
            unique_ids,
            max_workers=int(market_max_workers),
            id_hints=id_hints_bulk,
        )

    updated = 0
    eligible = 0
    missing_market = 0
    for index, row in df.iterrows():
        category = row_category(row)
        if category not in selected:
            continue
        eligible += 1
        base_price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        if pd.isna(base_price):
            continue
        calc_base = float(base_price)
        if base_mode in {"onliner_min", "onliner_avg", "onliner_max"}:
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            stats = market_map.get(oid, {}) if oid else {}
            if base_mode == "onliner_min":
                market_price = stats.get("min")
            elif base_mode == "onliner_avg":
                market_price = stats.get("avg")
            else:
                market_price = stats.get("max")
            if market_price is None:
                missing_market += 1
                continue
            calc_base = float(market_price)
        rrc, no_discount_price = calc_rrc_and_no_discount(
            calc_base,
            markup_cfg["percent"],
            threshold=markup_cfg["threshold"],
            min_profit=markup_cfg["min_profit"],
            no_discount_percent=markup_cfg["no_discount_percent"],
        )
        df.at[index, "РРЦ"] = rrc
        df.at[index, "Цена без скидки"] = no_discount_price
        updated += 1

    return df, {
        "status": "ok",
        "updated": int(updated),
        "eligible": int(eligible),
        "total": int(len(df)),
        "percent": markup_cfg["percent"],
        "threshold": markup_cfg["threshold"],
        "min_profit": markup_cfg["min_profit"],
        "no_discount_percent": markup_cfg["no_discount_percent"],
        "base_mode": base_mode,
        "market_checked": int(market_checked),
        "missing_market": int(missing_market),
    }


def update_markups_for_categories(markups, markup_cfg):
    markups = dict(markups or {})
    for category in set(markup_cfg["categories"]):
        markups[category] = {
            "percent": markup_cfg["percent"],
            "threshold": markup_cfg["threshold"],
            "min_profit": markup_cfg["min_profit"],
            "no_discount_percent": markup_cfg["no_discount_percent"],
            "base_mode": markup_cfg["base_mode"],
        }
    return markups


def build_markup_preview_payload(
    df,
    payload,
    *,
    row_category,
    round_price_to_90_func=round_price_to_90,
):
    payload = payload or {}
    categories = payload.get("categories", [])
    try:
        percent = float(payload.get("percent", 0))
    except Exception:
        percent = 0.0
    try:
        limit = int(payload.get("limit", 8))
    except Exception:
        limit = 8
    limit = max(1, min(limit, 20))

    selected = {str(category).strip() for category in categories if str(category).strip()}
    if not selected or df is None or df.empty or "Название" not in df.columns or "Цена" not in df.columns:
        return {"items": []}

    items = []
    for _, row in df.iterrows():
        category = row_category(row)
        if category not in selected:
            continue
        price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        if pd.isna(price):
            continue
        old_rrc = pd.to_numeric(row.get("РРЦ", np.nan), errors="coerce")
        calc_rrc = round_price_to_90_func(float(price) * (1.0 + percent / 100.0))
        items.append({
            "category": category,
            "name": str(row.get("Название", "")),
            "price": round(float(price), 2),
            "old_rrc": "" if pd.isna(old_rrc) else round(float(old_rrc), 2),
            "new_rrc": round(float(calc_rrc), 2),
        })
        if len(items) >= limit:
            break
    return {"items": items}
