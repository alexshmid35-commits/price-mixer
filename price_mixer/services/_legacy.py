#!/usr/bin/env python3
"""
Price Mixer — сводит прайсы поставщиков в единый прайс с привязкой к onliner.by

Запуск: python3 mixer.py
Результат: consolidated_price.xlsx
"""

import os
import re
import glob
import json
import time
import urllib.request
import threading
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# КОНФИГУРАЦИЯ ПОСТАВЩИКОВ
# Редактируйте этот раздел при изменении форматов или добавлении новых поставщиков
# ============================================================

SCRIPT_DIR = Path(__file__).parent.parent.resolve()
OUTPUT_FILE = SCRIPT_DIR / "consolidated_price.xlsx"

SUPPLIERS = {
    "BN-1030Z": {
        "file_pattern": "1030ZpriceBN*.xlsx",
        "sheet": 0,  # первый лист
        "header_row": 8,  # строка с заголовками (0-based)
        "columns": {
            0: "supplier_code",
            1: "product_name",
            3: "price_byn",
            4: "warranty",
            5: "onliner_id",
            6: "onliner_name",
        },
        "description": "BN заказ (полный ассортимент)",
    },
    "BN-1030": {
        "file_pattern": "1030priceBN*.xlsx",
        "sheet": 0,
        "header_row": 8,
        "columns": {
            0: "supplier_code",
            1: "product_name",
            2: "quantity",
            3: "price_byn",
            4: "warranty",
            5: "onliner_id",
            6: "onliner_name",
        },
        "description": "BN наличие",
    },
    "BN-1374": {
        "file_pattern": "1374priceBN*.xlsx",
        "sheet": 0,
        "header_row": 8,
        "columns": {
            0: "supplier_code",
            1: "product_name",
            2: "quantity",
            3: "price_byn",
            4: "warranty",
            5: "onliner_id",
            6: "onliner_name",
        },
        "description": "BN-1374 (ПК и комплектующие)",
    },
    "Tradex": {
        "file_pattern": "Tradex*.xlsx",
        "sheet_pattern": "Склад Минск",  # ищем лист по началу имени
        "header_row": 0,
        "columns": {
            0: "supplier_code",
            1: "product_name",
            2: "price_byn",
            4: "quantity",
            6: "status",
            9: "article",
            10: "warranty",
            13: "onliner_name",
            14: "onliner_id",
        },
        "filter": {"status": "В наличии"},
        "description": "Tradex (дистрибутор)",
    },
    "TGPC": {
        "file_pattern": "price_bn_*.xls*",
        "sheet": 0,
        "header_row": 0,
        "columns": {
            0: "supplier_code",
            2: "product_name",
            3: "warranty",
            6: "price_byn",
        },
        "description": "TGPC (безнал BYN)",
    },
}


# ============================================================
# ONLINER URL CACHE
# ============================================================

CACHE_FILE = SCRIPT_DIR / "onliner_cache.json"


def load_url_cache():
    """Загрузить кэш onliner_id -> url из файла."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_url_cache(cache):
    """Сохранить кэш в файл."""
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


ONLINER_ID_CACHE = SCRIPT_DIR / "onliner_id_cache.json"

QUERY_CACHE = {}
QUERY_CACHE_LOCK = threading.Lock()
API_REQUEST_TIMEOUT = 12
API_REQUEST_RETRIES = 3
API_RETRY_DELAY = 1.2

CATALOG_SPREADSHEET_ID = os.getenv("ONLINER_CATALOG_SPREADSHEET_ID", "11zEGNWLqcOxhlm6SubOlW2xFvjQSrJAJJaUm-ga8iHM")
CATALOG_SHEET_NAME = os.getenv("ONLINER_CATALOG_SHEET_NAME", "All_Catalog")
_default_catalog_key = SCRIPT_DIR / "ai2025-462421-df1d36f12313.json"
_fallback_catalog_key = SCRIPT_DIR.parent / "Parsing_19_Сategories" / "ai2025-462421-df1d36f12313.json"
CATALOG_KEY_FILE = os.getenv(
    "ONLINER_CATALOG_KEY_FILE",
    str(_default_catalog_key if _default_catalog_key.exists() else _fallback_catalog_key),
)
CATALOG_INDEX = None
CATALOG_INDEX_LIGHT = None
CATALOG_INDEX_LOCK = threading.Lock()
ID_CACHE_IO_LOCK = threading.Lock()


def load_id_cache():
    if ONLINER_ID_CACHE.exists():
        try:
            with open(ONLINER_ID_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            try:
                backup = ONLINER_ID_CACHE.with_suffix(".broken.json")
                ONLINER_ID_CACHE.replace(backup)
                print(f"[id_cache] Файл кэша поврежден, перенесен в {backup.name}: {e}", flush=True)
            except Exception:
                print(f"[id_cache] Файл кэша поврежден: {e}", flush=True)
            return {}
    return {}


def save_id_cache(cache):
    # Serialize writes to avoid concurrent .tmp replace races.
    with ID_CACHE_IO_LOCK:
        tmp = ONLINER_ID_CACHE.with_name(
            f"{ONLINER_ID_CACHE.stem}.{os.getpid()}.{threading.get_ident()}.tmp{ONLINER_ID_CACHE.suffix}"
        )
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(ONLINER_ID_CACHE)

def prune_negative_id_cache(cache=None, save=True):
    """
    Удалить из ID-кэша записи без найденного ID, чтобы они повторно проверялись.
    Возвращает (очищенный_кэш, удалено_записей).
    """
    if cache is None:
        cache = load_id_cache()
    initial_count = len(cache)
    pruned = {k: v for k, v in cache.items() if str((v or {}).get("id", "")).strip()}
    removed = initial_count - len(pruned)
    if save and removed > 0:
        save_id_cache(pruned)
    return pruned, removed


def build_id_fanout_map(cache=None):
    """
    Построить карту: onliner_id -> количество ключей кэша, которые ссылаются на этот ID.
    Нужна для отсечения явно "загрязненных" соответствий.
    """
    if cache is None:
        cache = load_id_cache()
    fanout = {}
    for _, rec in (cache or {}).items():
        oid = str((rec or {}).get("id", "")).strip()
        if not oid:
            continue
        fanout[oid] = fanout.get(oid, 0) + 1
    return fanout


def is_trusted_cached_id(cache_key, cached_record, id_fanout=None, max_fanout=20):
    """
    Проверка надежности записи ID-кэша.
    - должен быть непустой ID
    - ключ должен выглядеть как "артикул" (не fallback-кусок названия)
    - ID не должен быть связан со слишком большим числом разных ключей
    """
    oid = str((cached_record or {}).get("id", "")).strip()
    if not oid:
        return False

    key = str(cache_key or "").strip()
    if not _clean_article_token(key):
        return False

    if id_fanout is None:
        id_fanout = build_id_fanout_map()
    if int(id_fanout.get(oid, 0)) > int(max_fanout):
        return False
    return True


def _normalize_compact(value):
    """Нормализовать строку для нечувствительного сравнения артикулов."""
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _clean_article_token(token):
    """Привести токен к формату артикула и отфильтровать мусор."""
    token = str(token or "").strip().upper()
    token = token.strip(".,;:()[]{}")
    token = token.replace("–", "-").replace("—", "-")
    if len(token) < 8:
        return ""
    if not any(c.isdigit() for c in token):
        return ""
    if not re.fullmatch(r"[A-Z0-9\-\.\/_]+", token):
        return ""
    compact = re.sub(r"[^A-Z0-9]+", "", token)
    # Generic platform/socket markers are not unique product articles.
    generic_patterns = [
        r"^SOC\d{3,5}[A-Z]*$",
        r"^SOCKET[A-Z0-9]{3,}$",
        r"^LGA\d{3,5}[A-Z]*$",
        r"^AM\d+[A-Z]*$",
        r"^FM\d+[A-Z]*$",
        r"^TR\d+[A-Z]*$",
    ]
    if any(re.fullmatch(p, compact) for p in generic_patterns):
        return ""
    return token


def extract_article_candidates(name):
    """Вернуть список кандидатов-артикулов из названия (в порядке приоритета)."""
    text = str(name or "")
    if not text:
        return []

    candidates = []
    seen = set()

    def _add(token):
        cleaned = _clean_article_token(token)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            candidates.append(cleaned)

    bracket_parts = re.findall(r"\(([^)]+)\)", text)
    for part in bracket_parts:
        _add(part)
        for token in re.split(r"[\s,;/|]+", part):
            _add(token)

    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-\._/]{7,}", text):
        _add(token)

    return candidates


def _tokenize_match_text(text, min_len=4):
    """Разбить текст на токены для матчинга и нормализовать их."""
    if not text:
        return set()
    tokens = set()
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,}", str(text)):
        norm = _normalize_compact(token)
        if len(norm) >= min_len:
            tokens.add(norm)
    return tokens


def _prefix_words(text):
    words = re.findall(r"[A-Za-zА-Яа-я0-9]+", str(text or "").lower())
    out = []
    for w in words:
        if len(w) < 2:
            continue
        out.append(w)
        if len(out) >= 6:
            break
    return out


def _prefix_match_score(a_text, b_text):
    a = _prefix_words(a_text)
    b = _prefix_words(b_text)
    if not a or not b:
        return 0.0
    # Compare starts in order; tolerate longer supplier names.
    limit = min(len(a), len(b), 4)
    if limit <= 0:
        return 0.0
    same = 0
    for i in range(limit):
        if a[i] == b[i]:
            same += 1
    return same / float(limit)


def _head_match_score(a_text, b_text, limit=6):
    """
    Сравнить начало названий "мягко":
    берём первые слова и считаем долю пересечения без строгого порядка.
    """
    a = _prefix_words(a_text)[:limit]
    b = _prefix_words(b_text)[:limit]
    if not a or not b:
        return 0.0
    return len(set(a) & set(b)) / float(max(1, min(len(a), len(b))))


def _name_token_match_score(a_text, b_text):
    """
    Оценить сходство названий по токенам, чтобы не зависеть от "Socket/RET/OEM".
    """
    a_tokens = _tokenize_match_text(a_text, min_len=4)
    b_tokens = _tokenize_match_text(b_text, min_len=4)
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / float(max(1, min(len(a_tokens), len(b_tokens))))


def _article_intersection(a_text, b_text):
    a_articles = set(extract_article_candidates(a_text))
    b_articles = set(extract_article_candidates(b_text))
    return a_articles & b_articles

def _load_catalog_sheet_index(force_reload=False, light=False):
    """
    Загрузить индекс из Google Sheets All_Catalog:
    A -> Category, E -> CatalogID, F -> ссылка, H -> эталонное название.
    """
    global CATALOG_INDEX, CATALOG_INDEX_LIGHT
    with CATALOG_INDEX_LOCK:
        target = CATALOG_INDEX_LIGHT if light else CATALOG_INDEX
        if not force_reload and isinstance(target, dict) and target.get("by_id"):
            return target
        last_good = target if isinstance(target, dict) and target.get("by_id") else None

        if not os.path.exists(CATALOG_KEY_FILE):
            print(f"[catalog-index] key file not found: {CATALOG_KEY_FILE}")
            return last_good or {}

        try:
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
        except Exception as e:
            print(f"[catalog-index] gspread import error: {e}")
            return last_good or {}

        try:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CATALOG_KEY_FILE, scope)
            client = gspread.authorize(creds)
            ws = client.open_by_key(CATALOG_SPREADSHEET_ID).worksheet(CATALOG_SHEET_NAME)
            rows = ws.get_all_values()
        except Exception as e:
            print(f"[catalog-index] sheet load error: {e}")
            return last_good or {}

        by_id = {}
        by_token = {}
        records = []
        for row in rows[1:]:
            category = str(row[0]).strip() if len(row) > 0 else ""
            catalog_id = str(row[4]).strip() if len(row) > 4 else ""
            url = str(row[5]).strip() if len(row) > 5 else ""
            brand = str(row[1]).strip() if len(row) > 1 else ""
            model = str(row[2]).strip() if len(row) > 2 else ""
            title_h = str(row[7]).strip() if len(row) > 7 else ""
            if not catalog_id:
                continue
            if not url:
                url = ""

            by_id[catalog_id] = {
                "id": catalog_id,
                "url": url,
                "model": title_h or model,
                "model_h": title_h,
                "category": category,
            }
            if light:
                continue
            row_tokens = set()
            row_tokens.update(_tokenize_match_text(title_h, min_len=4))
            row_tokens.update(_tokenize_match_text(model, min_len=4))
            row_tokens.update(_tokenize_match_text(url, min_len=4))
            row_tokens.update(_tokenize_match_text(f"{brand} {model}", min_len=4))
            row_tokens.update(_tokenize_match_text(f"{brand} {title_h}", min_len=4))

            for norm in row_tokens:
                if not norm:
                    continue
                bucket = by_token.setdefault(norm, [])
                pair = (catalog_id, url)
                if pair not in bucket:
                    bucket.append(pair)

            if row_tokens:
                records.append({
                    "id": catalog_id,
                    "url": url,
                    "tokens": row_tokens,
                    "model": title_h or model,
                    "model_h": title_h,
                    "category": category,
                })

        built = {"by_token": by_token, "by_id": by_id, "records": records}
        if light:
            CATALOG_INDEX_LIGHT = built
        else:
            CATALOG_INDEX = built
        return built

def _lookup_id_from_catalog_sheet(product_name):
    """
    Попытаться найти CatalogID и URL по артикулу из названия
    через индекс Google Sheets (лист All_Catalog).
    """
    index = _load_catalog_sheet_index()
    if not index:
        return None, None

    by_token = index.get("by_token", {})
    records = index.get("records", [])

    candidates = extract_article_candidates(product_name)
    candidates.extend(re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,}", str(product_name or "")))

    normalized_candidates = []
    seen = set()
    for candidate in candidates:
        norm = _normalize_compact(candidate)
        if len(norm) >= 4 and norm not in seen:
            seen.add(norm)
            normalized_candidates.append(norm)

    for norm in normalized_candidates:
        matches = by_token.get(norm, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Не берем неоднозначный токен, чтобы не подставить чужой ID.
            continue

    return None, None


def lookup_id_from_catalog_sheet(product_name):
    """
    Публичный безопасный lookup в All_Catalog.
    Возвращает (onliner_id, url) только при однозначном совпадении.
    """
    return _lookup_id_from_catalog_sheet(product_name)


def lookup_catalog_match_details(product_name):
    """
    Вернуть расширенную информацию о сопоставлении с All_Catalog.
    Используется для UI-проверки и ручной привязки.
    """
    index = _load_catalog_sheet_index()
    if not index:
        return {"id": "", "url": "", "model": "", "score": 0.0, "matched": False}

    records = index.get("records", [])
    candidates = extract_article_candidates(product_name)
    name_tokens = _tokenize_match_text(product_name, min_len=4)

    # Сначала ищем по артикулам из названия.
    for candidate in candidates:
        norm = _normalize_compact(candidate)
        if not norm:
            continue
        matched = []
        for rec in records:
            if norm in rec["tokens"]:
                matched.append(rec)
        if len(matched) == 1:
            rec = matched[0]
            return {"id": rec["id"], "url": rec["url"], "model": rec["model"], "score": 1.0, "matched": True}

    # Затем сравниваем полное название по токенам из колонки H как по основному эталону.
    best_rec = None
    best_score = 0.0
    if name_tokens:
        for rec in records:
            h_tokens = _tokenize_match_text(rec.get("model_h", ""), min_len=4)
            rec_tokens = h_tokens or rec["tokens"]
            overlap = len(name_tokens & rec_tokens)
            if not overlap:
                continue
            score = overlap / max(1, min(len(name_tokens), len(rec_tokens)))
            if score > best_score:
                best_score = score
                best_rec = rec
        if best_rec and best_score >= 0.55:
            return {
                "id": best_rec["id"],
                "url": best_rec["url"],
                "model": best_rec["model"],
                "score": round(float(best_score), 3),
                "matched": True,
            }

    return {"id": "", "url": "", "model": "", "score": round(float(best_score), 3), "matched": False}


def verify_catalog_id_with_prefix(onliner_id, product_name, catalog_index=None):
    """
    Проверка валидности текущего OnlinerID:
    1) ID должен существовать в All_Catalog (колонка E),
    2) начало названия товара должно совпадать с началом названия из каталога.
    """
    oid = str(onliner_id or "").strip()
    if not oid:
        return {
            "status": "no_id",
            "score": 0.0,
            "catalog_id": "",
            "catalog_name": "",
            "url": "",
        }

    index = catalog_index if isinstance(catalog_index, dict) else _load_catalog_sheet_index()
    if not index:
        return {
            "status": "unverified",
            "score": 0.0,
            "catalog_id": "",
            "catalog_name": "",
            "url": "",
        }

    by_id = index.get("by_id", {})
    rec = by_id.get(oid)
    if rec:
        catalog_name = str(rec.get("model_h") or rec.get("model") or "").strip()
        if not catalog_name:
            return {
                "status": "match",
                "score": 1.0,
                "catalog_id": oid,
                "catalog_name": "",
                "url": str(rec.get("url", "")).strip(),
            }

        # ID из прайса уже найден в All_Catalog по колонке E.
        # Это главный признак валидности привязки. Текстовый score оставляем только как справку.
        article_hits = _article_intersection(product_name, catalog_name)
        article_match = bool(article_hits)
        prefix_score = _prefix_match_score(product_name, catalog_name)
        head_score = _head_match_score(product_name, catalog_name)
        token_score = _name_token_match_score(product_name, catalog_name)
        score = (0.20 * prefix_score) + (0.30 * head_score) + (0.50 * token_score)
        if article_match:
            score = max(score, 0.95)
        score = max(score, 0.7)

        return {
            "status": "match",
            "score": round(float(score), 3),
            "catalog_id": oid,
            "catalog_name": catalog_name,
            "url": str(rec.get("url", "")).strip(),
        }

    # Для "облегчённого" индекса (проверка по ID) не запускаем тяжёлый поиск по имени.
    if isinstance(index, dict) and not index.get("records"):
        return {
            "status": "mismatch",
            "score": 0.0,
            "catalog_id": "",
            "catalog_name": "",
            "url": "",
        }

    # ID not found in E column: suggest probable record by name to help manual fix.
    guessed = lookup_catalog_match_details(product_name)
    return {
        "status": "mismatch",
        "score": round(float(guessed.get("score", 0.0) or 0.0), 3),
        "catalog_id": str(guessed.get("id", "")).strip(),
        "catalog_name": str(guessed.get("model", "")).strip(),
        "url": str(guessed.get("url", "")).strip(),
    }


def _fetch_onliner_products(query):
    """Выполнить запрос к Onliner API и вернуть список продуктов."""
    q = str(query or "").strip()
    if not q:
        return []

    with QUERY_CACHE_LOCK:
        if q in QUERY_CACHE:
            return QUERY_CACHE[q]

    url = f"https://catalog.api.onliner.by/search/products?query={quote(query)}"
    products = []
    last_error = None
    for attempt in range(1, API_REQUEST_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            })
            resp = urllib.request.urlopen(req, timeout=API_REQUEST_TIMEOUT)
            data = json.loads(resp.read())
            products = data.get("products", [])
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt < API_REQUEST_RETRIES:
                time.sleep(API_RETRY_DELAY * attempt)

    if last_error is not None:
        return []

    with QUERY_CACHE_LOCK:
        QUERY_CACHE[q] = products
    return products


def _score_product_match(product, product_name, article_candidates):
    """
    Оценить совпадение товара Onliner с исходным названием.
    Возвращает (total_score, article_score, name_score).
    """
    product_text = " ".join(
        str(product.get(k, "")) for k in ("full_name", "name", "key", "html_url")
    ).upper()
    product_compact = _normalize_compact(product_text)

    article_score = 0
    for article in article_candidates:
        article_compact = _normalize_compact(article)
        if not article_compact:
            continue
        if article.upper() in product_text:
            article_score = max(article_score, 120)
        elif article_compact in product_compact:
            article_score = max(article_score, 110)

    words = [w for w in re.findall(r"[A-Za-zА-Яа-я0-9]+", str(product_name).lower()) if len(w) > 2]
    name_score = 0
    p_name = (product.get("full_name") or product.get("name", "")).lower()
    p_key = str(product.get("key", "")).lower()
    for w in words:
        if w in p_name:
            name_score += 2
        elif w in p_key:
            name_score += 1

    total_score = article_score + name_score
    return total_score, article_score, name_score


def _search_onliner_id_api(product_name):
    """Найти OnlinerID через API Onliner."""
    try:
        article_candidates = extract_article_candidates(product_name)
        queries = []
        search_pool = article_candidates[:2]
        # Всегда добавляем полный name-запрос как fallback.
        search_pool.append(str(product_name))

        for query in search_pool:
            if query and query not in queries:
                queries.append(query)

        best_match = None
        best_total = -1
        best_article_score = 0
        best_name_score = 0

        for query in queries:
            try:
                products = _fetch_onliner_products(query)
            except Exception:
                continue
            if not products:
                continue

            for p in products:
                total, article_score, name_score = _score_product_match(
                    p, product_name, article_candidates
                )
                if total > best_total:
                    best_total = total
                    best_article_score = article_score
                    best_name_score = name_score
                    best_match = p
                    # Явное сильное совпадение по артикулу — можно не делать лишние запросы.
                    if article_score >= 120:
                        return str(best_match.get("id")), best_match.get("html_url")

        if not best_match:
            return None, None

        # Если артикул есть, принимаем только при подтверждённом совпадении артикула.
        if article_candidates and best_article_score < 100:
            words = [
                w for w in re.findall(r"[A-Za-zА-Яа-я0-9]+", str(product_name).lower())
                if len(w) > 2
            ]
            min_name_score = max(6, int(len(words) * 0.7))
            if best_name_score < min_name_score:
                return None, None

        # Если артикула нет, требуем уверенное совпадение по словам названия.
        if not article_candidates:
            words = [
                w for w in re.findall(r"[A-Za-zА-Яа-я0-9]+", str(product_name).lower())
                if len(w) > 2
            ]
            min_name_score = max(4, int(len(words) * 0.6))
            if best_name_score < min_name_score:
                return None, None

        return str(best_match.get("id")), best_match.get("html_url")
    except Exception:
        return None, None


def find_missing_onliner_ids(
    items,
    id_cache=None,
    progress_callback=None,
    max_workers=20,
    use_api_search=True,
):
    """Найти OnlinerID для товаров без него (многопоточно)."""
    if id_cache is None:
        id_cache = load_id_cache()
    
    to_find = {}
    already_found = 0
    id_fanout = build_id_fanout_map(id_cache)
    
    for item in items:
        name = item.get("name", "")
        if not name:
            continue
        # Используем артикул как ключ кэша
        cache_key = extract_article(name)
        if not cache_key:
            continue
        if cache_key in id_cache:
            cached = id_cache[cache_key]
            if is_trusted_cached_id(cache_key, cached, id_fanout=id_fanout):
                already_found += 1
                continue
        if cache_key not in to_find:
            to_find[cache_key] = name
    
    if not to_find:
        if progress_callback:
            progress_callback(0, 0, already_found)
        return id_cache, already_found
    
    found = 0
    found_from_sheet = 0
    found_from_api = 0
    not_found = 0
    total = len(to_find)

    unresolved = []
    sheet_total = len(to_find)
    for i, (cache_key, name) in enumerate(to_find.items(), start=1):
        oid, url = _lookup_id_from_catalog_sheet(name)
        if oid:
            id_cache[cache_key] = {"id": str(oid), "url": url}
            found += 1
            found_from_sheet += 1
        else:
            unresolved.append((cache_key, name))

        if (i % 50) == 0:
            save_id_cache(id_cache)

        if progress_callback and ((i % 20) == 0 or i == sheet_total):
            checked = found_from_sheet
            progress_callback(
                checked,
                total,
                found + already_found,
                {
                    "phase": "sheet",
                    "sheet_checked": i,
                    "sheet_total": sheet_total,
                    "sheet_found": found_from_sheet,
                    "api_checked": 0,
                    "api_total": len(unresolved),
                    "api_found": 0,
                    "not_found": 0,
                },
            )

    api_total = len(unresolved)

    def _find_one(args):
        cache_key, name = args
        oid, url = _search_onliner_id_api(name)
        return cache_key, oid, url

    if unresolved and use_api_search:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_find_one, args): args for args in unresolved}
            for i, future in enumerate(as_completed(futures), start=1):
                cache_key, oid, url = future.result()
                if oid:
                    id_cache[cache_key] = {"id": oid, "url": url}
                    found += 1
                    found_from_api += 1
                else:
                    id_cache[cache_key] = {"id": "", "url": ""}
                    not_found += 1

                if i % 50 == 0:
                    save_id_cache(id_cache)

                if progress_callback and ((i % 20) == 0 or i == api_total):
                    checked = found_from_sheet + i
                    progress_callback(
                        checked,
                        total,
                        found + already_found,
                        {
                            "phase": "api",
                            "sheet_checked": sheet_total,
                            "sheet_total": sheet_total,
                            "sheet_found": found_from_sheet,
                            "api_checked": i,
                            "api_total": api_total,
                            "api_found": found_from_api,
                            "not_found": not_found,
                        },
                    )
    elif progress_callback and not unresolved:
        progress_callback(
            found_from_sheet,
            total,
            found + already_found,
            {
                "phase": "done",
                "sheet_checked": sheet_total,
                "sheet_total": sheet_total,
                "sheet_found": found_from_sheet,
                "api_checked": 0,
                "api_total": 0,
                "api_found": 0,
                "not_found": 0,
            },
        )
    
    if unresolved and not use_api_search:
        not_found = len(unresolved)
        for cache_key, _ in unresolved:
            id_cache[cache_key] = {"id": "", "url": ""}
        if progress_callback:
            progress_callback(
                found_from_sheet,
                total,
                found + already_found,
                {
                    "phase": "done",
                    "sheet_checked": sheet_total,
                    "sheet_total": sheet_total,
                    "sheet_found": found_from_sheet,
                    "api_checked": 0,
                    "api_total": 0,
                    "api_found": 0,
                    "not_found": not_found,
                },
            )
    
    save_id_cache(id_cache)
    print(
        f"ID matching summary: sheet={found_from_sheet}, api={found_from_api}, "
        f"not_found={not_found}, cached={already_found}"
    )
    return id_cache, found + already_found

def warm_url_cache_from_id_cache(id_cache=None, url_cache=None):
    """
    Подогреть кэш ссылок значениями URL из ID-кэша.
    """
    if id_cache is None:
        id_cache = load_id_cache()
    if url_cache is None:
        url_cache = load_url_cache()

    updated = 0
    for val in id_cache.values():
        oid = str((val or {}).get("id", "")).strip()
        url = str((val or {}).get("url", "")).strip()
        if oid and url and not url_cache.get(oid):
            url_cache[oid] = url
            updated += 1

    if updated > 0:
        save_url_cache(url_cache)
    return url_cache, updated


TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


def _resolve_via_tavily(onliner_id, product_name):
    """Найти URL через Tavily поиск."""
    try:
        query = f"{product_name} site:onliner.by/catalog"
        url = "https://api.tavily.com/search"
        data = json.dumps({
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 5,
            "include_domains": ["onliner.by"]
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
        })
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        for item in result.get("results", []):
            href = item.get("url", "")
            if "catalog.onliner.by" in href and "/search/" not in href:
                return onliner_id, href
        return onliner_id, None
    except Exception as e:
        return onliner_id, None


def _resolve_one_id(onliner_id, product_name=None):
    """Резолвить один onliner_id в URL через API."""
    try:
        time.sleep(0.15)
        query = product_name if product_name else str(onliner_id)
        url = f"https://catalog.api.onliner.by/search/products?query={quote(query)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        products = data.get("products", [])

        if not products:
            return onliner_id, None

        # Приоритет 1: точное совпадение по ID (надёжнее текста)
        for p in products:
            if str(p.get("id")) == str(onliner_id):
                return onliner_id, p.get("html_url")

        # Приоритет 2: текстовый матчинг — нормализованный Jaccard по токенам >= 3 символов
        if product_name:
            best_match = None
            best_score = 0.0
            name_lower = product_name.lower()
            name_tokens = set(t for t in re.split(r"\W+", name_lower) if len(t) >= 3)
            for p in products:
                p_name = (p.get("full_name") or p.get("name", "")).lower()
                p_tokens = set(t for t in re.split(r"\W+", p_name) if len(t) >= 3)
                if not name_tokens or not p_tokens:
                    continue
                overlap = len(name_tokens & p_tokens) / max(len(name_tokens), len(p_tokens))
                if overlap > best_score:
                    best_score = overlap
                    best_match = p
            # Возвращаем только при достаточном сходстве — не кладём мусор в кэш
            if best_match and best_score >= 0.25:
                return onliner_id, best_match.get("html_url")

        return onliner_id, None
    except Exception:
        return onliner_id, None


def resolve_onliner_urls(onliner_ids, cache=None, max_workers=3, progress_callback=None, id_to_name=None):
    """
    Резолвить список onliner_id в реальные URL.
    id_to_name: словарь {onliner_id: product_name} для Tavily fallback
    """
    if cache is None:
        cache = load_url_cache()
    if id_to_name is None:
        id_to_name = {}

    to_resolve = [oid for oid in onliner_ids if str(oid) not in cache]

    if not to_resolve:
        return cache

    resolved = 0
    total = len(to_resolve)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_resolve_one_id, str(oid), id_to_name.get(str(oid))): oid 
            for oid in to_resolve
        }
        for future in as_completed(futures):
            oid, url = future.result()
            if url:
                cache[str(oid)] = url
            else:
                cache[str(oid)] = ""
            resolved += 1
            if progress_callback and resolved % 50 == 0:
                progress_callback(resolved, total)

    save_url_cache(cache)
    return cache


def get_onliner_link(onliner_id, name, cache=None):
    """Получить ссылку на onliner.by: из кэша."""
    if cache and str(onliner_id) in cache:
        url = cache[str(onliner_id)]
        if url:
            return url
    return ""


def detect_supplier(filename):
    """Определить поставщика по имени файла. Возвращает (supplier_name, config) или (None, None)."""
    fname = filename.lower()
    for sup_name, config in SUPPLIERS.items():
        pattern = config["file_pattern"].lower()
        # Превращаем glob-паттерн в простую проверку
        prefix = pattern.split("*")[0]
        if prefix and fname.startswith(prefix):
            return sup_name, config
    # Дополнительные проверки для файлов без чёткого паттерна
    if "tradex" in fname:
        return "Tradex", SUPPLIERS["Tradex"]
    if fname.startswith("price_bn"):
        return "TGPC", SUPPLIERS["TGPC"]
    if fname.startswith("price_") and "bn" not in fname:
        return "TGPC-USD", SUPPLIERS.get("TGPC-USD", SUPPLIERS["TGPC"])
    return None, None


# ============================================================
# ПАРСИНГ
# ============================================================

def find_file(pattern):
    """Найти файл по glob-паттерну в директории скрипта."""
    matches = sorted(glob.glob(str(SCRIPT_DIR / pattern)))
    if not matches:
        return None
    # Берём самый свежий файл (последний по имени/дате)
    return matches[-1]


def find_sheet(excel_file, sheet_pattern):
    """Найти лист по паттерну начала имени."""
    xls = pd.ExcelFile(excel_file)
    for name in xls.sheet_names:
        if name.startswith(sheet_pattern):
            return name
    return xls.sheet_names[0]


def parse_supplier_from_file(supplier_name, config, filepath):
    """Распарсить прайс одного поставщика из конкретного файла."""
    # Определяем лист
    if "sheet_pattern" in config:
        sheet = find_sheet(filepath, config["sheet_pattern"])
    else:
        sheet = config.get("sheet", 0)

    # Читаем данные без заголовков
    df = pd.read_excel(filepath, sheet_name=sheet, header=None, skiprows=config["header_row"])

    # Маппинг колонок
    col_map = config["columns"]
    available_cols = {idx: name for idx, name in col_map.items() if idx < len(df.columns)}
    df_mapped = df[list(available_cols.keys())].copy()
    df_mapped.columns = list(available_cols.values())

    # Убираем строку-заголовок если она попала в данные
    if "supplier_code" in df_mapped.columns:
        df_mapped = df_mapped[df_mapped["supplier_code"] != "Код"]

    # Фильтруем только строки с товарами (есть код и цена)
    if "supplier_code" in df_mapped.columns and "price_byn" in df_mapped.columns:
        df_mapped = df_mapped[
            df_mapped["supplier_code"].notna() & df_mapped["price_byn"].notna()
        ]

    # Применяем фильтр (например, "В наличии" для Tradex)
    if "filter" in config:
        for col, value in config["filter"].items():
            if col in df_mapped.columns:
                df_mapped = df_mapped[df_mapped[col] == value]
                df_mapped = df_mapped.drop(columns=[col])

    # Убираем вспомогательные колонки
    for col in ["status", "article"]:
        if col in df_mapped.columns:
            df_mapped = df_mapped.drop(columns=[col])

    # Приводим типы
    df_mapped["price_byn"] = pd.to_numeric(df_mapped["price_byn"], errors="coerce")
    df_mapped = df_mapped[df_mapped["price_byn"].notna() & (df_mapped["price_byn"] > 0)]

    if "quantity" in df_mapped.columns:
        df_mapped["quantity"] = pd.to_numeric(df_mapped["quantity"], errors="coerce")

    if "warranty" in df_mapped.columns:
        df_mapped["warranty"] = pd.to_numeric(df_mapped["warranty"], errors="coerce")

    # Очистка onliner_id
    if "onliner_id" in df_mapped.columns:
        df_mapped["onliner_id"] = (
            df_mapped["onliner_id"]
            .astype(str)
            .str.strip()
            .str.replace(r"\t", "", regex=True)
            .str.replace(r"\.0$", "", regex=True)
        )
        df_mapped.loc[
            df_mapped["onliner_id"].isin(["", "nan", "None", "NaN"]), "onliner_id"
        ] = np.nan

    # Очистка supplier_code
    df_mapped["supplier_code"] = (
        df_mapped["supplier_code"]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    # Добавляем имя поставщика
    df_mapped["supplier"] = supplier_name

    # Убираем дубликаты по коду поставщика (берём первое вхождение)
    df_mapped = df_mapped.drop_duplicates(subset=["supplier_code"], keep="first")

    return df_mapped


def parse_supplier(supplier_name, config):
    """Распарсить прайс одного поставщика (поиск файла по паттерну)."""
    filepath = find_file(config["file_pattern"])
    if not filepath:
        print(f"  [!] Файл не найден: {config['file_pattern']}")
        return pd.DataFrame()

    print(f"  Файл: {os.path.basename(filepath)}")
    df = parse_supplier_from_file(supplier_name, config, filepath)
    print(f"  Товаров: {len(df)}")
    return df


# ============================================================
# СОПОСТАВЛЕНИЕ И КОНСОЛИДАЦИЯ
# ============================================================

def consolidate(all_data, url_cache=None):
    """Сводит все данные в единый прайс."""
    # Разделяем: с OnlinerID и без
    has_id = all_data[all_data["onliner_id"].notna()].copy()
    no_id = all_data[all_data["onliner_id"].isna()].copy()

    print(f"\nС OnlinerID: {len(has_id)} позиций")
    print(f"Без OnlinerID: {len(no_id)} позиций")

    if has_id.empty:
        print("Нет товаров с OnlinerID для сопоставления!")
        return pd.DataFrame(), no_id

    # Загружаем кэш URL если не передан
    if url_cache is None:
        url_cache = load_url_cache()

    # Группируем по onliner_id
    supplier_names = sorted(all_data["supplier"].unique())

    rows = []
    for onliner_id, group in has_id.groupby("onliner_id"):
        # Находим лучшее название (из onliner_name или product_name)
        name = None
        for _, row in group.iterrows():
            if pd.notna(row.get("onliner_name")) and str(row["onliner_name"]).strip():
                name = str(row["onliner_name"]).strip()
                break
        if not name:
            name = str(group.iloc[0]["product_name"]).strip()

        # Цены по поставщикам
        prices = {}
        for _, row in group.iterrows():
            sup = row["supplier"]
            price = row["price_byn"]
            if sup not in prices or price < prices[sup]:
                prices[sup] = price

        # Минимальная цена и поставщик
        min_supplier = min(prices, key=prices.get)
        min_price = prices[min_supplier]

        # Гарантия (макс из доступных)
        warranty = group["warranty"].dropna().max() if "warranty" in group.columns else None

        # Ссылка — из кэша или fallback на поиск
        link = get_onliner_link(onliner_id, name, url_cache)

        row_data = {
            "Onliner ID": onliner_id,
            "Название": name,
            "Мин. цена (BYN)": min_price,
            "Лучший поставщик": min_supplier,
        }

        for sup in supplier_names:
            row_data[f"Цена {sup}"] = prices.get(sup, None)

        row_data["Гарантия (мес.)"] = warranty
        row_data["Ссылка onliner.by"] = link

        rows.append(row_data)

    result = pd.DataFrame(rows)
    result = result.sort_values("Название").reset_index(drop=True)

    return result, no_id


def parse_generic_excel(filepath, supplier_name):
    """Универсальный парсер Excel - пытается найти колонки автоматически."""
    df_raw = pd.read_excel(filepath, header=None)
    
    header_row = 0
    for i in range(min(20, len(df_raw))):
        row = df_raw.iloc[i].astype(str).str.lower()
        row_vals = ' '.join(str(v) for v in row.values)
        if 'код' in row_vals or 'наименование' in row_vals or 'цена' in row_vals:
            header_row = i
            break
    
    df = pd.read_excel(filepath, header=header_row)
    col_map = {}
    supplier_norm = str(supplier_name or "").strip().lower()
    has_it_distribution_header = False
    
    for col in df.columns:
        col_lower = str(col).lower().strip()
        col_norm = re.sub(r"\s+", " ", col_lower.replace("\n", " ")).strip()
        if "дистрибуц" in col_norm and "ооо" in col_norm:
            has_it_distribution_header = True
        if col_lower in ["код", "code", "артикул", "sku"]:
            col_map["supplier_code"] = col
        elif col_lower in ["наименование", "название", "товар", "product", "name", "товары"]:
            col_map["product_name"] = col
        elif col_lower in ["цена", "цена byn", "цена б.р.", "price", "цена, руб", "цена с ндс"]:
            col_map["price_byn"] = col
        elif col_lower in ["гарантия", "warranty"]:
            col_map["warranty"] = col
        elif (
            "ррц" in col_norm
            or "мрц" in col_norm
            or "rrc" in col_norm
            or "mrc" in col_norm
            or ("рекомендуем" in col_norm and "рознич" in col_norm and "цен" in col_norm)
            or ("минимальн" in col_norm and "рознич" in col_norm and "цен" in col_norm)
        ):
            col_map["rrc"] = col
        elif col_lower in ["onlinerid", "onliner id", "onliner_id", "id onliner"]:
            col_map["onliner_id"] = col
        elif col_lower in ["onliner", "название onliner"]:
            col_map["onliner_name"] = col
        elif col_lower in ["кол-во", "количество", "qty", "quantity"]:
            col_map["quantity"] = col
    
    if "price_byn" not in col_map:
        for col in df.columns:
            col_str = str(col).lower()
            if 'цена' in col_str and ('ндс' in col_str or 'руб' in col_str or 'byn' in col_str):
                col_map["price_byn"] = col
                break

    # Поставщик "АйТи Дистрибуция ООО": цена всегда в колонке C (индекс 2).
    # Явно фиксируем источник цены, чтобы не подхватывать похожие колонки (например, гарантию).
    if (
        "tradex" in supplier_norm
        or "айти дистрибуц" in supplier_norm
        or "it distribution" in supplier_norm
        or has_it_distribution_header
    ):
        if len(df.columns) >= 3:
            col_map["price_byn"] = df.columns[2]
    
    if "price_byn" not in col_map:
        for col in df.columns:
            if df[col].dtype in ['float64', 'int64']:
                if df[col].max() > 1 and df[col].max() < 100000:
                    col_map["price_byn"] = col
                    break
    
    if "product_name" not in col_map:
        for col in df.columns:
            if df[col].dtype == 'object':
                sample = df[col].dropna().head(10).astype(str)
                avg_len = sum(len(s) for s in sample) / max(len(sample), 1)
                if avg_len > 30:
                    col_map["product_name"] = col
                    break
    
    if "product_name" not in col_map:
        numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
        text_cols = [c for c in df.columns if c not in numeric_cols]
        for col in text_cols:
            sample = df[col].dropna().head(10).astype(str)
            if any(len(s) > 30 for s in sample):
                col_map["product_name"] = col
                break
    
    if "price_byn" not in col_map or "product_name" not in col_map:
        print(f"Не найдены колонки: {list(df.columns)}")
        return pd.DataFrame()
    
    result = pd.DataFrame()
    for key, col in col_map.items():
        result[key] = df[col]
    
    result["supplier"] = supplier_name
    result["price_byn"] = pd.to_numeric(result["price_byn"], errors="coerce")
    result = result[result["price_byn"].notna() & (result["price_byn"] > 0)]
    
    result = result[result["product_name"].notna()]
    result = result[~result["product_name"].astype(str).str.match(r'^[A-Za-zА-Яа-я\s]+$')]
    
    if "onliner_id" in result.columns:
        result["onliner_id"] = result["onliner_id"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        result.loc[result["onliner_id"].isin(["", "nan", "None", "NaN"]), "onliner_id"] = np.nan

    if "rrc" in result.columns:
        result["rrc"] = pd.to_numeric(result["rrc"], errors="coerce")
        result.loc[result["rrc"].isna(), "rrc"] = np.nan
    
    print(f"  Найдено колонок: {col_map}")
    print(f"  С OnlinerID: {result['onliner_id'].notna().sum() if 'onliner_id' in result.columns else 0}")
    
    return result


def extract_article(name):
    """Извлечь артикул из названия (в скобках в конце)."""
    candidates = extract_article_candidates(name)
    return candidates[0] if candidates else ""


def _pick_warranty(group):
    """Выбрать гарантию для сводной строки."""
    if "warranty" not in group.columns:
        return ""
    series = group["warranty"].dropna()
    if series.empty:
        return ""
    value = series.max()
    try:
        num = float(value)
        if num.is_integer():
            return int(num)
        return num
    except Exception:
        text = str(value).strip()
        return text if text else ""


def _pick_rrc(best_row):
    """Взять РРЦ/МРЦ из строки, если есть, иначе пусто."""
    for key in ("rrc", "mrc", "РРЦ", "МРЦ", "RRC", "MRC"):
        if key in best_row.index:
            value = best_row.get(key)
            if pd.notna(value) and str(value).strip() and str(value).strip().lower() != "nan":
                return value
    return ""


def _pick_order_term(group):
    """
    \u0412\u044b\u0431\u0440\u0430\u0442\u044c \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435 \u0441\u0440\u043e\u043a\u0430 \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0438 \u0432 \u0434\u043d\u044f\u0445.
    \u0415\u0441\u043b\u0438 \u0432 \u0434\u0430\u043d\u043d\u044b\u0445 \u043d\u0435\u0442 \u0441\u0440\u043e\u043a\u0430/\u0434\u0430\u0442\u044b \u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0438, \u043f\u043e \u0443\u043c\u043e\u043b\u0447\u0430\u043d\u0438\u044e: 2.
    """
    def _normalize_delivery_days(value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "2"
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return "2"
        match = re.search(r"(\d+)", text)
        if match:
            return match.group(1)
        return text

    for col in ("order_term", "delivery_days", "delivery_date", "days", "\u0434\u043d\u0435\u0439", "\u0434\u0430\u0442\u0430 \u043f\u043e\u0441\u0442\u0430\u0432\u043a\u0438"):
        if col in group.columns:
            series = group[col].dropna().astype(str).str.strip()
            series = series[series != ""]
            if not series.empty:
                return _normalize_delivery_days(series.iloc[0])
    return "2"



def _is_groupable_article(article):
    """True если артикул достаточно уникален для группировки товаров."""
    article = str(article or "").strip().upper()
    if len(article) < 8:
        return False
    if not any(ch.isalpha() for ch in article):
        return False
    if not any(ch.isdigit() for ch in article):
        return False
    generic_patterns = [
        r"^\d+XUSB\d",
        r"^\d+XPCI",
        r"^\d+XTYPE",
        r"^\d+XRJ",
        r"\d{3,4}X\d{3,4}$",
        r"^VESA\d",
        r"^SOC(?:KET)?-?\d+",
        r"^LGA[\d/AMX\-]+$",
        r"^802\.11",
        r"^SCHUKO",
        r"^IEC-C\d+",
        r"^\d+-\d+$",
    ]
    for pattern in generic_patterns:
        if re.fullmatch(pattern, article):
            return False
    return True


def consolidate_simple(all_data):
    """Консолидатор: группирует по OnlinerID и артикулу, но не теряет строки без артикула."""
    if "onliner_id" not in all_data.columns:
        all_data["onliner_id"] = np.nan

    all_data = all_data.copy()
    all_data["_article"] = all_data["product_name"].apply(extract_article)

    rows = []
    id_to_article = {}

    def _append_group_best_row(group, onliner_id=""):
        if group is None or group.empty:
            return
        best_row = group.loc[group["price_byn"].idxmin()]
        rows.append({
            "OnlinerID": onliner_id,
            "Название": str(best_row.get("product_name", "")).strip(),
            "Цена": best_row.get("price_byn"),
            "Поставщик": best_row.get("supplier", ""),
            "Гарантия": _pick_warranty(group),
            "\u0414\u043d\u0435\u0439 \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0438": _pick_order_term(group),
            "РРЦ": _pick_rrc(best_row),
        })

    has_id = all_data[all_data["onliner_id"].notna()]
    # Keep one best offer per (OnlinerID, supplier) so cross-supplier
    # price comparison remains visible in the main table.
    for (onliner_id, supplier_name), group in has_id.groupby(["onliner_id", "supplier"], dropna=False):
        if pd.isna(onliner_id) or str(onliner_id).strip() == "":
            continue
        best_row = group.loc[group["price_byn"].idxmin()]
        article = str(best_row.get("_article", "") or "").strip()
        if _is_groupable_article(article):
            id_to_article[str(onliner_id).strip()] = article
        _append_group_best_row(group, onliner_id=onliner_id)

    article_to_id = {v: k for k, v in id_to_article.items() if v}

    no_id = all_data[all_data["onliner_id"].isna()].copy()
    no_id["_article"] = no_id["_article"].fillna("").astype(str).str.strip()

    no_id_with_article = no_id[no_id["_article"].apply(_is_groupable_article)]
    no_id_without_article = no_id[~no_id["_article"].apply(_is_groupable_article)]

    for article, group in no_id_with_article.groupby("_article"):
        # Never auto-inherit OnlinerID across suppliers from article only.
        # This keeps supplier source IDs intact (notably IVEN) and prevents
        # synthetic duplicate IDs from being introduced by consolidation.
        _append_group_best_row(group, onliner_id="")

    if not no_id_without_article.empty:
        fallback_keys = []
        for idx, row in no_id_without_article.iterrows():
            supplier_code = str(row.get("supplier_code", "") or "").strip()
            if supplier_code and supplier_code.lower() != "nan":
                fallback_keys.append(f"code:{supplier_code}")
                continue

            product_name = str(row.get("product_name", "") or "").strip()
            if product_name:
                fallback_keys.append(f"name:{product_name}")
                continue

            fallback_keys.append(f"row:{idx}")

        no_id_without_article["_fallback_group_key"] = fallback_keys
        for _, group in no_id_without_article.groupby("_fallback_group_key", dropna=False):
            _append_group_best_row(group, onliner_id="")

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("Название").reset_index(drop=True)
    return result


def export_excel(consolidated, unmatched, all_data, output_path=None, suppliers_config=None):
    """Сохраняет результат в Excel с тремя листами."""
    if output_path is None:
        output_path = OUTPUT_FILE
    if suppliers_config is None:
        suppliers_config = SUPPLIERS
    supplier_names = sorted(all_data["supplier"].unique())

    with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
        # Лист 1: Сводный прайс
        if not consolidated.empty:
            consolidated.to_excel(writer, sheet_name="Сводный прайс", index=False)
            ws = writer.sheets["Сводный прайс"]
            # Ширина колонок
            ws.column_dimensions["A"].width = 12  # Onliner ID
            ws.column_dimensions["B"].width = 55  # Название
            ws.column_dimensions["C"].width = 15  # Мин. цена
            ws.column_dimensions["D"].width = 18  # Поставщик

        # Лист 2: Без сопоставления
        if not unmatched.empty:
            export_cols = ["supplier", "supplier_code", "product_name", "price_byn"]
            if "quantity" in unmatched.columns:
                export_cols.append("quantity")
            if "warranty" in unmatched.columns:
                export_cols.append("warranty")
            unmatched_export = unmatched[
                [c for c in export_cols if c in unmatched.columns]
            ].copy()
            unmatched_export.columns = [
                {"supplier": "Поставщик", "supplier_code": "Код", "product_name": "Наименование",
                 "price_byn": "Цена BYN", "quantity": "Кол-во", "warranty": "Гарантия"}.get(c, c)
                for c in unmatched_export.columns
            ]
            unmatched_export.to_excel(writer, sheet_name="Без сопоставления", index=False)

        # Лист 3: Статистика
        stats_rows = []
        for sup in supplier_names:
            sup_data = all_data[all_data["supplier"] == sup]
            matched = sup_data[sup_data["onliner_id"].notna()]
            stats_rows.append({
                "Поставщик": sup,
                "Описание": suppliers_config.get(sup, {}).get("description", ""),
                "Всего товаров": len(sup_data),
                "С OnlinerID": len(matched),
                "Без OnlinerID": len(sup_data) - len(matched),
                "% сопоставления": f"{len(matched)/len(sup_data)*100:.1f}%" if len(sup_data) > 0 else "0%",
            })

        stats_rows.append({
            "Поставщик": "ИТОГО",
            "Всего товаров": len(all_data),
            "С OnlinerID": len(all_data[all_data["onliner_id"].notna()]),
            "Без OnlinerID": len(all_data[all_data["onliner_id"].isna()]),
        })

        if not consolidated.empty:
            stats_rows.append({
                "Поставщик": "Уникальных позиций (сводный прайс)",
                "Всего товаров": len(consolidated),
            })

        stats_df = pd.DataFrame(stats_rows)
        stats_df.to_excel(writer, sheet_name="Статистика", index=False)
        ws = writer.sheets["Статистика"]
        ws.column_dimensions["A"].width = 35
        ws.column_dimensions["B"].width = 35


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Price Mixer — сведение прайсов поставщиков")
    print("=" * 60)

    all_frames = []

    for name, config in SUPPLIERS.items():
        print(f"\n[{name}] {config.get('description', '')}")
        df = parse_supplier(name, config)
        if not df.empty:
            # Гарантируем наличие всех колонок
            for col in ["supplier_code", "product_name", "price_byn", "quantity",
                         "warranty", "onliner_id", "onliner_name", "supplier"]:
                if col not in df.columns:
                    df[col] = np.nan
            all_frames.append(df)

    if not all_frames:
        print("\nНе найдено ни одного прайса!")
        return

    all_data = pd.concat(all_frames, ignore_index=True)
    print(f"\n{'=' * 60}")
    print(f"Всего загружено: {len(all_data)} товарных позиций")

    # Консолидация
    consolidated, unmatched = consolidate(all_data)

    if not consolidated.empty:
        print(f"Уникальных позиций в сводном прайсе: {len(consolidated)}")

    # Экспорт
    export_excel(consolidated, unmatched, all_data)
    print(f"\nРезультат сохранён: {OUTPUT_FILE}")
    print("Готово!")


if __name__ == "__main__":
    main()
