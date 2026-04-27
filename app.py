#!/usr/bin/env python3
"""
Price Mixer Web — веб-интерфейс для сведения прайсов поставщиков.

Запуск: python3 app.py
Открыть: http://localhost:5001
"""

import base64
import json
import math
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from config import cfg
from mixer import (
    build_id_fanout_map,
    consolidate_simple,
    extract_article,
    extract_article_candidates,
    is_trusted_cached_id,
    load_id_cache,
    load_url_cache,
    lookup_catalog_match_details,
    lookup_id_from_catalog_sheet,
    parse_generic_excel,
    resolve_onliner_urls,
    save_id_cache,
)
from price_mixer.api.routes import bp as api_bp

# Глобальный прогресс резолвинга
resolve_status = {"running": False, "resolved": 0, "total": 0, "cached": 0}
market_refresh_status = {
    "running": False,
    "total": 0,
    "done": 0,
    "success": 0,
    "errors": 0,
    "categories": {},
    "recent_errors": [],
    "started_at": 0,
    "finished_at": 0,
}
MARKET_REFRESH_LOCK = threading.RLock()
# Параллельные запросы B2B/catalog при «Обновить Цены Onliner» (I/O-bound).
MARKET_REFRESH_POOL_WORKERS = 28
source_fetch_statuses = {}
SOURCE_FETCH_LOCK = threading.RLock()
verify_all_ids_status = {
    "running": False,
    "total": 0,
    "done": 0,
    "matched": 0,
    "mismatched": 0,
    "errors": 0,
    "items": [],
    "report_items": [],
    "started_at": 0,
    "finished_at": 0,
    "message": "",
}
VERIFY_ALL_IDS_LOCK = threading.RLock()
validate_clean_ids_status = {
    "running": False,
    "total": 0,
    "done": 0,
    "confirmed": 0,
    "cleared": 0,
    "queued": 0,
    "errors": 0,
    "mode": "api",
    "mode_label": "Onliner API",
    "skipped_label": "Пропуск = API не ответил, ID не меняли.",
    "started_at": 0,
    "finished_at": 0,
    "message": "",
}
VALIDATE_CLEAN_IDS_LOCK = threading.RLock()
B2B_TOKEN_LOCK = threading.RLock()
B2B_TOKEN_CACHE = {"access_token": "", "expires_at": 0}
B2B_CATALOG_LOCK = threading.RLock()
B2B_CATALOG_CACHE = {
    "sections": {"ts": 0, "items": []},
    "manufacturers": {},
    "products": {},
    "articles": {},
}
autofill_tgpc_pc_status = {
    "running": False,
    "total": 0,
    "done": 0,
    "applied": 0,
    "skipped": 0,
    "percent": 0,
    "items": [],
    "started_at": 0,
    "finished_at": 0,
    "message": "",
}
AUTOFILL_TGPC_PC_LOCK = threading.RLock()
autofill_iven_status = {
    "running": False,
    "total": 0,
    "done": 0,
    "applied": 0,
    "skipped": 0,
    "percent": 0,
    "started_at": 0,
    "finished_at": 0,
    "message": "",
    "matches": [],   # [{name, matched_name, score, id, url, source}]
    "no_match": [],  # [{name}] — не нашли
    "report_mode": "iven",
    "report_title": "Отчёт подбора IVEN-бридж",
    "report_subtitle": "Сопоставление N-Tech товаров с базой Onliner ID",
}
AUTOFILL_IVEN_LOCK = threading.RLock()
AUTO_REFRESH_INTERVAL_SEC = 12 * 3600
AUTO_REFRESH_MAX_IDS = 1200
AUTO_REFRESH_POLL_SEC = 20
AUTO_REFRESH_ALLOWED_HOURS = (3, 6, 12)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.register_blueprint(api_bp)
CONSOLIDATED_IO_LOCK = threading.RLock()
BACKGROUND_STARTED = False
LAST_ACTIVE_SESSION_DIR = None
LAST_UPLOAD_CLEANUP_TS = 0

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
UPLOAD_KEEP_LAST_SESSIONS = 20
UPLOAD_KEEP_DAYS = 7
UPLOAD_KEEP_API_FETCH_HOURS = 12

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_AUTOSORT_MODEL = os.getenv("OPENAI_AUTOSORT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
OPENAI_AUTOSORT_TIMEOUT_SEC = 9
OPENAI_AUTOSORT_MAX_ITEMS = 320
OPENAI_AUTOSORT_MAX_WORKERS = 10
AI_CATEGORY_CACHE = {}
AI_CATEGORY_CACHE_LOCK = threading.Lock()


def _ensure_background_workers():
    global BACKGROUND_STARTED
    if BACKGROUND_STARTED:
        return
    BACKGROUND_STARTED = True
    threading.Thread(target=_auto_market_refresh_loop, daemon=True).start()


def _cleanup_old_uploads(exclude_dirs=None):
    exclude = {str(Path(p).resolve()) for p in (exclude_dirs or []) if p}
    now = time.time()
    cleanup_cfg = (load_app_settings().get("uploads_cleanup") or {})
    keep_last_sessions = int(cleanup_cfg.get("keep_last_sessions", UPLOAD_KEEP_LAST_SESSIONS) or UPLOAD_KEEP_LAST_SESSIONS)
    keep_days = int(cleanup_cfg.get("keep_days", UPLOAD_KEEP_DAYS) or UPLOAD_KEEP_DAYS)
    keep_api_fetch_hours = int(cleanup_cfg.get("keep_api_fetch_hours", UPLOAD_KEEP_API_FETCH_HOURS) or UPLOAD_KEEP_API_FETCH_HOURS)
    keep_session_sec = keep_days * 24 * 3600
    keep_api_sec = keep_api_fetch_hours * 3600
    try:
        dirs = [p for p in UPLOAD_DIR.iterdir() if p.is_dir()]
    except Exception:
        return {"removed": 0, "skipped": 0}

    session_dirs = []
    api_fetch_dirs = []
    other_dirs = []
    for path in dirs:
        resolved = str(path.resolve())
        if resolved in exclude:
            continue
        if path.name.startswith("_api_fetch_"):
            api_fetch_dirs.append(path)
        elif (path / "consolidated_price.xlsx").exists() or (path / "consolidated.json").exists():
            session_dirs.append(path)
        else:
            other_dirs.append(path)

    removed = 0
    skipped = 0

    session_dirs.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    for idx, path in enumerate(session_dirs):
        try:
            mtime = path.stat().st_mtime
        except Exception:
            skipped += 1
            continue
        age = now - mtime
        if idx < keep_last_sessions:
            continue
        if age < keep_session_sec:
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except Exception:
            skipped += 1

    for path in api_fetch_dirs + other_dirs:
        try:
            mtime = path.stat().st_mtime
        except Exception:
            skipped += 1
            continue
        age = now - mtime
        if age < keep_api_sec:
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except Exception:
            skipped += 1

    return {"removed": removed, "skipped": skipped}


def _maybe_cleanup_old_uploads(exclude_dirs=None, min_interval_sec=1800):
    global LAST_UPLOAD_CLEANUP_TS
    now = time.time()
    if now - float(LAST_UPLOAD_CLEANUP_TS or 0) < float(min_interval_sec or 0):
        return {"removed": 0, "skipped": 0, "throttled": True}
    LAST_UPLOAD_CLEANUP_TS = now
    result = _cleanup_old_uploads(exclude_dirs=exclude_dirs)
    result["throttled"] = False
    return result


@app.before_request
def _startup_background_workers():
    global LAST_ACTIVE_SESSION_DIR
    _ensure_background_workers()
    sdir = session.get("session_dir")
    if sdir:
        LAST_ACTIVE_SESSION_DIR = str(sdir)
    exclude = [LAST_ACTIVE_SESSION_DIR, session.get("session_dir")]
    _maybe_cleanup_old_uploads(exclude_dirs=exclude)

# ============================================================
# HTML ШАБЛОНЫ

# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def index():
    error = request.args.get("error")
    return render_template("upload.html", error=error)


@app.route("/result")
def result_page():
    sid = str(request.args.get("sid", "") or "").strip()
    app_settings = load_app_settings()
    session_dir = session.get("session_dir")
    if sid:
        candidate_dir = UPLOAD_DIR / sid
        try:
            candidate_dir.resolve().relative_to(UPLOAD_DIR.resolve())
        except ValueError:
            return redirect(url_for("index", error="Недопустимый идентификатор сессии"))
        candidate_file = candidate_dir / "consolidated_price.xlsx"
        if candidate_file.exists():
            session_dir = str(candidate_dir)
            _finalize_processed_session(sid, candidate_dir, candidate_file)
    if not session_dir:
        return redirect(url_for("index", error="Нет активного прайса"))
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return redirect(url_for("index", error="Файл результата не найден"))
    df = read_consolidated_df(session_dir)
    total_suppliers = len(set(str(v).strip() for v in df.get("Поставщик", pd.Series(dtype=str)).tolist() if str(v).strip()))
    without_id = _count_rows_without_onliner_id(df)
    duplicate_id_rows = _count_rows_with_duplicate_onliner_id(df)
    with_id = len(df) - without_id
    stats = {
        "total": len(df),
        "suppliers": total_suppliers,
        "consolidated": len(df),
        "matched": with_id,
        "with_id": with_id,
        "without_id": without_id,
        "duplicate_id_rows": duplicate_id_rows,
        "show_checks_block": _coerce_bool((((app_settings or {}).get("ui") or {}).get("show_checks_block", True)), default=True),
        "snapshot_diff": load_session_supplier_diff(session_dir),
    }
    return render_template("result.html", stats=stats)




@app.before_request
def require_basic_auth():
    """Require HTTP Basic Auth for all routes except health/version."""
    exempt_paths = {"/api/health", "/api/version"}
    if request.path in exempt_paths:
        return None
    auth = request.authorization
    if not auth or not (auth.username == cfg.admin_username and auth.password == cfg.admin_password):
        return Response(
            "Authentication required\n",
            401,
            {"WWW-Authenticate": 'Basic realm="Price Mixer"'},
        )
@app.after_request
def add_no_cache_headers(response):
    try:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    except Exception:
        pass
    return response


def get_article_from_name(name):
    """Извлечь артикул из названия."""
    if not name:
        return ""
    article = extract_article(name)
    if article:
        return article
    # No fallback to name fragments: it causes cache-key collisions
    # for similar long names (notably motherboards) and can propagate one ID.
    return ""


def _is_generic_cpu_cache_key(key):
    raw = str(key or "").strip()
    if not raw:
        return True
    low = raw.lower()
    compact = re.sub(r"[\s_]+", "", low)
    generic_patterns = [
        r"^socket[-\s]?[a-z0-9-]+$",
        r"^lga[-\s]?\d{3,5}$",
        r"^am\d+$",
        r"^fm\d+$",
        r"^tr\d+[a-z]*$",
        r"^s\d{3,5}$",
    ]
    for pattern in generic_patterns:
        if re.match(pattern, low, flags=re.IGNORECASE) or re.match(pattern, compact, flags=re.IGNORECASE):
            return True
    return False


def _is_generic_id_cache_key(key):
    raw = str(key or "").strip()
    if not raw:
        return True
    low = raw.lower()
    compact = re.sub(r"[^a-z0-9]+", "", low)
    generic_patterns = [
        r"^soc[-\s]?\d{3,5}[a-z]*$",
        r"^socket[-\s]?[a-z0-9-]{3,}$",
        r"^lga[-\s]?\d{3,5}[a-z]*$",
        r"^am\d+[a-z]*$",
        r"^fm\d+[a-z]*$",
        r"^tr\d+[a-z]*$",
    ]
    for pattern in generic_patterns:
        if re.match(pattern, low, flags=re.IGNORECASE) or re.match(pattern, compact, flags=re.IGNORECASE):
            return True
    return False


def _get_id_cache_key_for_name(name):
    article = str(get_article_from_name(name) or "").strip()
    if not article:
        return ""
    name_low = str(name or "").strip().lower()
    is_cpu_like = any(token in name_low for token in ["процессор", "intel", "amd", "ryzen", "xeon", "celeron", "pentium", "athlon", "core i"])
    if _is_generic_id_cache_key(article):
        return ""
    if is_cpu_like and _is_generic_cpu_cache_key(article):
        return ""
    return article


def _sanitize_id_cache(cache):
    if not isinstance(cache, dict):
        return {}, False
    cleaned = {}
    changed = False
    for key, value in cache.items():
        if _is_generic_cpu_cache_key(key) or _is_generic_id_cache_key(key):
            changed = True
            continue
        cleaned[key] = value
    return cleaned, changed


CATEGORY_PRIORITY = [
    "Процессор",
    "Кулер",
    "Охлаждение",
    "Материнская плата",
    "Оперативная память",
    "SSD",
    "Жесткий диск",
    "Видеокарта",
    "Блок питания",
    "Корпус",
    "Монитор",
]

CATEGORY_OVERRIDE_FILE = Path(__file__).parent / "category_overrides.json"
CATEGORY_MARKUPS_FILE = Path(__file__).parent / "category_markups.json"
CATEGORY_VISIBILITY_FILE = Path(__file__).parent / "category_visibility.json"
ONLINER_MARKET_CACHE_FILE = Path(__file__).parent / "onliner_market_cache.json"
ONLINER_PRODUCT_CACHE_FILE = Path(__file__).parent / "onliner_product_cache.json"
ONLINER_DB_FILE = Path(__file__).parent / "onliner_products.db"
_DB_WRITE_LOCK = threading.RLock()
MANUAL_ID_BINDINGS_FILE = Path(__file__).parent / "manual_id_bindings.json"
ID_CHANGE_JOURNAL_FILE = Path(__file__).parent / "id_change_journal.json"
REVIEW_QUEUE_FILE = Path(__file__).parent / "id_review_queue.json"
AUTO_REFRESH_SETTINGS_FILE = Path(__file__).parent / "auto_refresh_settings.json"
ONLINER_API_SETTINGS_FILE = Path(__file__).parent / "onliner_api_settings.json"
APP_SETTINGS_FILE = Path(__file__).parent / "app_settings.json"
SUPPLIER_SNAPSHOTS_FILE = Path(__file__).parent / "supplier_snapshots.json"
API_FETCH_HISTORY_FILE = Path(__file__).parent / "api_fetch_history.json"
ONLINER_MARKET_CACHE_TTL = 24 * 3600
ONLINER_PRODUCT_CACHE_TTL = 7 * 24 * 3600
ID_REPLACE_QUERY_CACHE_TTL = 3600
ID_REPLACE_QUERY_CACHE = {}
ID_REPLACE_QUERY_CACHE_LOCK = threading.RLock()
ID_REPLACE_QUERY_CACHE_VERSION = "v7"
ONLINER_PRODUCT_CACHE_LOCK = threading.RLock()
ONLINER_API_PROXY_STATE_LOCK = threading.RLock()
ONLINER_API_SETTINGS_LOCK = threading.RLock()
ONLINER_API_SETTINGS_CACHE = {"loaded_at": 0.0, "mtime": 0.0, "data": None}
ONLINER_API_SESSION_LOCAL = threading.local()
ONLINER_API_RETRY_STATUSES = {403, 408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}
ONLINER_API_DEFAULT_SETTINGS = {
    "proxy_pool": [],
    "allow_direct": True,
    "retry_attempts": 3,
    "backoff_sec": 0.6,
    "proxy_cooldown_sec": 180,
    "max_parallel_workers": 10,
}
ONLINER_API_PROXY_STATE = {}


def _category_sort_key(category_name):
    if category_name in CATEGORY_PRIORITY:
        return (0, CATEGORY_PRIORITY.index(category_name), category_name)
    return (1, 999, category_name.lower())


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _coerce_int(value, default, min_value=None, max_value=None):
    try:
        num = int(value)
    except Exception:
        num = int(default)
    if min_value is not None:
        num = max(int(min_value), num)
    if max_value is not None:
        num = min(int(max_value), num)
    return num


def _coerce_float(value, default, min_value=None, max_value=None):
    try:
        num = float(value)
    except Exception:
        num = float(default)
    if min_value is not None:
        num = max(float(min_value), num)
    if max_value is not None:
        num = min(float(max_value), num)
    return num


def _normalize_proxy_entry(entry):
    if isinstance(entry, str):
        proxy_url = str(entry).strip()
        if not proxy_url:
            return None
        return {
            "key": proxy_url,
            "label": proxy_url,
            "proxies": {"http": proxy_url, "https": proxy_url},
        }
    if not isinstance(entry, dict):
        return None

    http_proxy = str(entry.get("http") or entry.get("all") or "").strip()
    https_proxy = str(entry.get("https") or entry.get("all") or http_proxy).strip()
    if not http_proxy and not https_proxy:
        return None
    key = str(entry.get("key") or entry.get("label") or http_proxy or https_proxy).strip()
    label = str(entry.get("label") or key).strip() or key
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    if not proxies:
        return None
    return {"key": key, "label": label, "proxies": proxies}


def _normalize_proxy_pool(raw_pool):
    pool = []
    if isinstance(raw_pool, str):
        raw_pool = re.split(r"[\r\n,;]+", raw_pool)
    if not isinstance(raw_pool, list):
        return pool
    seen = set()
    for item in raw_pool:
        norm = _normalize_proxy_entry(item)
        if not norm:
            continue
        key = norm["key"].strip()
        if not key or key in seen:
            continue
        seen.add(key)
        pool.append(norm)
    return pool


def _read_onliner_api_settings():
    data = {}
    if ONLINER_API_SETTINGS_FILE.exists():
        try:
            with open(ONLINER_API_SETTINGS_FILE, encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                data = payload
        except Exception:
            data = {}

    env_proxy_list = os.getenv("ONLINER_PROXY_LIST", "").strip()
    env_single_proxy = os.getenv("ONLINER_PROXY", "").strip()
    raw_pool = data.get("proxy_pool", [])
    if env_proxy_list:
        raw_pool = env_proxy_list
    elif env_single_proxy:
        raw_pool = [env_single_proxy]

    allow_direct = data.get("allow_direct", True)
    env_allow_direct = os.getenv("ONLINER_ALLOW_DIRECT", "").strip()
    if env_allow_direct:
        allow_direct = _coerce_bool(env_allow_direct, default=True)

    retry_attempts = data.get("retry_attempts", ONLINER_API_DEFAULT_SETTINGS["retry_attempts"])
    if os.getenv("ONLINER_RETRY_ATTEMPTS", "").strip():
        retry_attempts = os.getenv("ONLINER_RETRY_ATTEMPTS")

    backoff_sec = data.get("backoff_sec", ONLINER_API_DEFAULT_SETTINGS["backoff_sec"])
    if os.getenv("ONLINER_BACKOFF_SEC", "").strip():
        backoff_sec = os.getenv("ONLINER_BACKOFF_SEC")

    proxy_cooldown_sec = data.get("proxy_cooldown_sec", ONLINER_API_DEFAULT_SETTINGS["proxy_cooldown_sec"])
    if os.getenv("ONLINER_PROXY_COOLDOWN_SEC", "").strip():
        proxy_cooldown_sec = os.getenv("ONLINER_PROXY_COOLDOWN_SEC")

    max_parallel_workers = data.get("max_parallel_workers", ONLINER_API_DEFAULT_SETTINGS["max_parallel_workers"])
    if os.getenv("ONLINER_MAX_PARALLEL_WORKERS", "").strip():
        max_parallel_workers = os.getenv("ONLINER_MAX_PARALLEL_WORKERS")

    return {
        "proxy_pool": _normalize_proxy_pool(raw_pool),
        "allow_direct": _coerce_bool(allow_direct, default=True),
        "retry_attempts": _coerce_int(retry_attempts, ONLINER_API_DEFAULT_SETTINGS["retry_attempts"], min_value=1, max_value=12),
        "backoff_sec": _coerce_float(backoff_sec, ONLINER_API_DEFAULT_SETTINGS["backoff_sec"], min_value=0.0, max_value=5.0),
        "proxy_cooldown_sec": _coerce_int(proxy_cooldown_sec, ONLINER_API_DEFAULT_SETTINGS["proxy_cooldown_sec"], min_value=10, max_value=3600),
        "max_parallel_workers": _coerce_int(max_parallel_workers, ONLINER_API_DEFAULT_SETTINGS["max_parallel_workers"], min_value=1, max_value=24),
    }


def load_onliner_api_settings(force_reload=False):
    with ONLINER_API_SETTINGS_LOCK:
        now = time.time()
        try:
            mtime = ONLINER_API_SETTINGS_FILE.stat().st_mtime if ONLINER_API_SETTINGS_FILE.exists() else 0.0
        except Exception:
            mtime = 0.0
        cached = ONLINER_API_SETTINGS_CACHE.get("data")
        if (
            (not force_reload)
            and isinstance(cached, dict)
            and ONLINER_API_SETTINGS_CACHE.get("mtime") == mtime
            and (now - float(ONLINER_API_SETTINGS_CACHE.get("loaded_at", 0.0) or 0.0) <= 5.0)
        ):
            return dict(cached)
        settings = _read_onliner_api_settings()
        ONLINER_API_SETTINGS_CACHE["loaded_at"] = now
        ONLINER_API_SETTINGS_CACHE["mtime"] = mtime
        ONLINER_API_SETTINGS_CACHE["data"] = dict(settings)
        return dict(settings)


def save_onliner_api_settings(settings):
    payload = _read_onliner_api_settings()
    if isinstance(settings, dict):
        payload.update(settings)
    payload = {
        "proxy_pool": _normalize_proxy_pool(payload.get("proxy_pool", [])),
        "allow_direct": _coerce_bool(payload.get("allow_direct", True), default=True),
        "retry_attempts": _coerce_int(payload.get("retry_attempts", ONLINER_API_DEFAULT_SETTINGS["retry_attempts"]), ONLINER_API_DEFAULT_SETTINGS["retry_attempts"], min_value=1, max_value=12),
        "backoff_sec": _coerce_float(payload.get("backoff_sec", ONLINER_API_DEFAULT_SETTINGS["backoff_sec"]), ONLINER_API_DEFAULT_SETTINGS["backoff_sec"], min_value=0.0, max_value=5.0),
        "proxy_cooldown_sec": _coerce_int(payload.get("proxy_cooldown_sec", ONLINER_API_DEFAULT_SETTINGS["proxy_cooldown_sec"]), ONLINER_API_DEFAULT_SETTINGS["proxy_cooldown_sec"], min_value=10, max_value=3600),
        "max_parallel_workers": _coerce_int(payload.get("max_parallel_workers", ONLINER_API_DEFAULT_SETTINGS["max_parallel_workers"]), ONLINER_API_DEFAULT_SETTINGS["max_parallel_workers"], min_value=1, max_value=24),
    }
    with open(ONLINER_API_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with ONLINER_API_SETTINGS_LOCK:
        ONLINER_API_SETTINGS_CACHE["loaded_at"] = time.time()
        ONLINER_API_SETTINGS_CACHE["mtime"] = ONLINER_API_SETTINGS_FILE.stat().st_mtime if ONLINER_API_SETTINGS_FILE.exists() else 0.0
        ONLINER_API_SETTINGS_CACHE["data"] = dict(payload)
    return dict(payload)


def get_onliner_api_max_workers(default=10):
    settings = load_onliner_api_settings()
    return _coerce_int(settings.get("max_parallel_workers", default), default, min_value=1, max_value=24)


def _get_onliner_session():
    session_obj = getattr(ONLINER_API_SESSION_LOCAL, "session", None)
    if session_obj is None:
        session_obj = requests.Session()
        session_obj.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32)
        session_obj.mount("http://", adapter)
        session_obj.mount("https://", adapter)
        ONLINER_API_SESSION_LOCAL.session = session_obj
    return session_obj


def _onliner_route_key(route):
    if not route:
        return "direct"
    return str(route.get("key") or route.get("label") or "proxy").strip() or "proxy"


def _get_onliner_routes(settings):
    routes = []
    if _coerce_bool(settings.get("allow_direct", True), default=True):
        routes.append(None)
    routes.extend(list(settings.get("proxy_pool") or []))

    now = time.time()
    with ONLINER_API_PROXY_STATE_LOCK:
        def _rank(route):
            key = _onliner_route_key(route)
            state = ONLINER_API_PROXY_STATE.get(key, {})
            blocked_until = float(state.get("blocked_until", 0.0) or 0.0)
            failures = int(state.get("failures", 0) or 0)
            available = 0 if blocked_until <= now else 1
            return (available, blocked_until, failures, key)

        return sorted(routes, key=_rank)


def _mark_onliner_route_success(route):
    key = _onliner_route_key(route)
    with ONLINER_API_PROXY_STATE_LOCK:
        state = ONLINER_API_PROXY_STATE.setdefault(key, {})
        state["blocked_until"] = 0.0
        state["last_error"] = ""
        state["last_status"] = 200
        state["successes"] = int(state.get("successes", 0) or 0) + 1
        state["failures"] = 0
        state["updated_at"] = time.time()


def _mark_onliner_route_failure(route, reason, cooldown_sec, status_code=0):
    key = _onliner_route_key(route)
    with ONLINER_API_PROXY_STATE_LOCK:
        state = ONLINER_API_PROXY_STATE.setdefault(key, {})
        state["blocked_until"] = time.time() + max(0, int(cooldown_sec or 0))
        state["last_error"] = str(reason or "").strip()
        state["last_status"] = int(status_code or 0)
        state["failures"] = int(state.get("failures", 0) or 0) + 1
        state["updated_at"] = time.time()


def onliner_api_get(url, timeout=8, headers=None):
    settings = load_onliner_api_settings()
    routes = _get_onliner_routes(settings)
    if not routes:
        routes = [None]

    max_attempts = max(1, min(len(routes), _coerce_int(settings.get("retry_attempts", 3), 3, min_value=1, max_value=12)))
    cooldown_sec = _coerce_int(settings.get("proxy_cooldown_sec", 180), 180, min_value=10, max_value=3600)
    backoff_sec = _coerce_float(settings.get("backoff_sec", 0.6), 0.6, min_value=0.0, max_value=5.0)
    merged_headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if isinstance(headers, dict):
        merged_headers.update(headers)

    last_response = None
    last_error = None
    session_obj = _get_onliner_session()
    for attempt_index, route in enumerate(routes[:max_attempts]):
        try:
            response = session_obj.get(
                url,
                timeout=timeout,
                headers=merged_headers,
                proxies=(route or {}).get("proxies") if route else None,
            )
            if response.ok:
                _mark_onliner_route_success(route)
                return response
            last_response = response
            if int(response.status_code or 0) in ONLINER_API_RETRY_STATUSES and attempt_index + 1 < max_attempts:
                _mark_onliner_route_failure(route, f"http_{response.status_code}", cooldown_sec, status_code=response.status_code)
                if backoff_sec > 0:
                    time.sleep(backoff_sec * (attempt_index + 1))
                continue
            return response
        except Exception as exc:
            last_error = exc
            _mark_onliner_route_failure(route, exc.__class__.__name__, cooldown_sec)
            if attempt_index + 1 < max_attempts and backoff_sec > 0:
                time.sleep(backoff_sec * (attempt_index + 1))

    if last_response is not None:
        return last_response
    raise last_error if last_error is not None else RuntimeError("onliner_api_get_failed")


def load_category_overrides():
    from price_mixer.db import get_db
    try:
        data = get_db().get_category_overrides()
        if isinstance(data, dict):
            cleaned = {k: v for k, v in data.items() if not str(k).startswith("art:")}
            suspicious = []
            for k, v in cleaned.items():
                kk = str(k or "").lower()
                vv = str(v or "").strip()
                if vv == "Блок питания":
                    if re.search(r"\bкорпус\b|\bcase\b|\bкулер\b|cooler|охлажден|сжо|водян|fan", kk):
                        suspicious.append(k)
            for k in suspicious:
                cleaned.pop(k, None)
            if len(cleaned) != len(data):
                try:
                    save_category_overrides(cleaned)
                except Exception:
                    pass
            return cleaned
    except Exception:
        pass
    return {}


def save_category_overrides(overrides):
    from price_mixer.db import get_db
    try:
        get_db().clear_category_overrides()
        for category, items in overrides.items():
            get_db().set_category_overrides(category, items)
    except Exception:
        pass


def load_category_markups():
    if not CATEGORY_MARKUPS_FILE.exists():
        return {}
    try:
        with open(CATEGORY_MARKUPS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_category_markups(markups):
    with open(CATEGORY_MARKUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(markups, f, ensure_ascii=False, indent=2)


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


def _normalize_auto_refresh_settings(data=None):
    data = data or {}
    if not isinstance(data, dict):
        data = {}
    enabled = bool(data.get("enabled", False))
    interval = int(data.get("interval_hours", 12) or 12)
    if interval not in AUTO_REFRESH_ALLOWED_HOURS:
        interval = 12
    out = {
        "enabled": enabled,
        "interval_hours": interval,
        "last_run_ts": int(data.get("last_run_ts", 0) or 0),
        "last_started_ts": int(data.get("last_started_ts", 0) or 0),
        "last_status": str(data.get("last_status", "idle") or "idle"),
        "last_count": int(data.get("last_count", 0) or 0),
        "last_message": str(data.get("last_message", "") or ""),
    }
    return out


def load_auto_refresh_settings():
    if not AUTO_REFRESH_SETTINGS_FILE.exists():
        return _normalize_auto_refresh_settings()
    try:
        with open(AUTO_REFRESH_SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return _normalize_auto_refresh_settings(data)
    except Exception:
        return _normalize_auto_refresh_settings()


def save_auto_refresh_settings(settings):
    payload = _normalize_auto_refresh_settings(settings)
    with open(AUTO_REFRESH_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


APP_SETTINGS_DEFAULTS = {
    "export": {
        "include_without_id": True,
        "price_name": "consolidated_price",
        "keep_lowest_price_per_onliner_id": False,
        "exclude_duplicate_id_suppliers": [],
        "only_pc_suppliers": [],
        "only_pc_price_name": "N-tech_TGPC_Beznal",
        "google_sheets_spreadsheet_url_or_id": "",
        "google_sheets_tab": "Прайс N-Tech",
        "google_sheets_service_account_json": "",
    },
    "onliner_db_import": {
        "google_sheet_id": "",
        "google_sheet_name": "All_Catalog",
    },
    "ui": {
        "show_checks_block": True,
    },
    "cache_api": {
        "allow_direct": True,
        "retry_attempts": 3,
        "backoff_sec": 0.6,
        "proxy_cooldown_sec": 180,
        "max_parallel_workers": 10,
    },
    "onliner_b2b": {
        "enabled": False,
        "base_url": "https://b2bapi.onliner.by",
        "price_api_base_url": "https://price.api.onliner.by",
        "client_id": "",
        "client_secret": "",
        "token_url": "https://b2bapi.onliner.by/oauth/token",
        "verify_ssl": True,
        "timeout_sec": 20,
    },
    "suppliers": {
        "filename_rules": [
            {"pattern": "tradex", "supplier": "Tradex"},
            {"pattern": "1030z", "supplier": "BN-1030Z"},
            {"pattern": "1030", "supplier": "BN-1030"},
            {"pattern": "1374", "supplier": "BN-1374"},
            {"pattern": "price_bn", "supplier": "TGPC"},
        ],
    },
    "api_sources": {
        "iven": {
            "enabled": False,
            "label": "IVEN",
            "supplier": "IVEN",
            "mode": "direct_file",
            "file_url": "",
            "verify_ssl": False,
        },
        "tradex": {
            "enabled": False,
            "label": "Tradex",
            "supplier": "Tradex",
            "mode": "direct_file",
            "file_url": "",
            "verify_ssl": False,
        },
        "ntech": {
            "enabled": False,
            "label": "N-Tech",
            "supplier": "N-Tech",
            "mode": "ntech_json",
            "auth_url": "",
            "price_url": "",
            "username": "",
            "password": "",
            "verify_ssl": False,
        },
    },
    "uploads_cleanup": {
        "keep_last_sessions": 20,
        "keep_days": 7,
        "keep_api_fetch_hours": 12,
    },
    "no_id_search": {
        "max_candidates": 80,
        "max_queries": 4,
        "prefer_paren_model": True,
        "prefer_article_tokens": True,
        "include_brand_token": True,
        "require_category_hint": False,
        "category_rules_text": json.dumps({
            "Процессор": {"query_hint": "cpu processor", "must_contain": ["ryzen", "intel", "xeon"], "ignore_words": ["cooler"]},
            "Видеокарта": {"query_hint": "videocard gpu", "must_contain": ["rtx", "gtx", "radeon"], "ignore_words": ["holder"]},
            "Оперативная память": {"query_hint": "dram ddr memory", "must_contain": ["ddr", "dimm", "sodimm"], "ignore_words": ["ssd"]},
            "SSD": {"query_hint": "ssd nvme", "must_contain": ["ssd", "nvme", "m.2"], "ignore_words": ["dram"]},
            "Жесткий диск": {"query_hint": "hdd hard drive", "must_contain": ["hdd", "sata", "7200"], "ignore_words": ["ssd"]},
        }, ensure_ascii=False, indent=2),
    },
    "verify_id": {
        "match_threshold": 0.74,
        "trust_manual_confirmed": True,
        "force_refresh_api": True,
        "api_no_name_status": "review",
        "require_article_or_model_priority": False,
    },
}


def _deep_merge_dict(base, extra):
    out = dict(base or {})
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(out.get(key), value)
        else:
            out[key] = value
    return out


def _normalize_filename_rules(rules):
    out = []
    if not isinstance(rules, list):
        return list(APP_SETTINGS_DEFAULTS["suppliers"]["filename_rules"])
    for item in rules:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern", "")).strip()
        supplier = str(item.get("supplier", "")).strip()
        if not pattern or not supplier:
            continue
        out.append({"pattern": pattern, "supplier": supplier})
    return out or list(APP_SETTINGS_DEFAULTS["suppliers"]["filename_rules"])


def _normalize_api_sources(sources):
    defaults = APP_SETTINGS_DEFAULTS["api_sources"]
    out = {}
    raw = sources if isinstance(sources, dict) else {}
    for key, default_cfg in defaults.items():
        cfg = raw.get(key, {}) if isinstance(raw.get(key), dict) else {}
        mode = str(cfg.get("mode", default_cfg.get("mode", "direct_file"))).strip() or default_cfg.get("mode", "direct_file")
        item = {
            "enabled": _coerce_bool(cfg.get("enabled", default_cfg.get("enabled", False)), default=bool(default_cfg.get("enabled", False))),
            "label": str(cfg.get("label", default_cfg.get("label", key.upper()))).strip()[:40] or str(default_cfg.get("label", key.upper())),
            "supplier": str(cfg.get("supplier", default_cfg.get("supplier", key.upper()))).strip()[:80] or str(default_cfg.get("supplier", key.upper())),
            "mode": mode,
            "verify_ssl": _coerce_bool(cfg.get("verify_ssl", default_cfg.get("verify_ssl", False)), default=bool(default_cfg.get("verify_ssl", False))),
        }
        if mode == "ntech_json":
            item.update({
                "auth_url": str(cfg.get("auth_url", default_cfg.get("auth_url", ""))).strip(),
                "price_url": str(cfg.get("price_url", default_cfg.get("price_url", ""))).strip(),
                "username": str(cfg.get("username", default_cfg.get("username", ""))).strip(),
                "password": str(cfg.get("password", default_cfg.get("password", ""))),
            })
        else:
            item.update({
                "file_url": str(cfg.get("file_url", default_cfg.get("file_url", ""))).strip(),
            })
        out[key] = item
    return out


def _normalize_supplier_name_list(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\r\n,;]+", str(value or ""))
    out = []
    seen = set()
    for item in raw_items:
        name = str(item or "").strip()
        low = name.lower()
        if not name or low in seen:
            continue
        seen.add(low)
        out.append(name[:80])
    return out


def _normalize_app_settings(data=None):
    merged = _deep_merge_dict(APP_SETTINGS_DEFAULTS, data if isinstance(data, dict) else {})
    export = merged.get("export", {})
    onliner_db_import = merged.get("onliner_db_import", {})
    ui = merged.get("ui", {})
    cache_api = merged.get("cache_api", {})
    onliner_b2b = merged.get("onliner_b2b", {})
    uploads_cleanup = merged.get("uploads_cleanup", {})
    no_id_search = merged.get("no_id_search", {})
    verify_id = merged.get("verify_id", {})
    suppliers = merged.get("suppliers", {})
    api_sources = merged.get("api_sources", {})
    return {
        "export": {
            "include_without_id": _coerce_bool(export.get("include_without_id", True), default=True),
            "price_name": re.sub(r"[^A-Za-zА-Яа-я0-9._ -]+", "", str(export.get("price_name", "consolidated_price")).strip())[:80] or "consolidated_price",
            "keep_lowest_price_per_onliner_id": _coerce_bool(export.get("keep_lowest_price_per_onliner_id", False), default=False),
            "exclude_duplicate_id_suppliers": _normalize_supplier_name_list(export.get("exclude_duplicate_id_suppliers", [])),
            "only_pc_suppliers": _normalize_supplier_name_list(export.get("only_pc_suppliers", [])),
            "only_pc_price_name": re.sub(r"[^A-Za-zА-Яа-я0-9._ -]+", "", str(export.get("only_pc_price_name", "N-tech_TGPC_Beznal")).strip())[:80] or "N-tech_TGPC_Beznal",
            "google_sheets_spreadsheet_url_or_id": str(export.get("google_sheets_spreadsheet_url_or_id", "") or "").strip()[:500],
            "google_sheets_tab": str(export.get("google_sheets_tab", "Прайс N-Tech") or "Прайс N-Tech").strip()[:99] or "Прайс N-Tech",
            "google_sheets_service_account_json": str(export.get("google_sheets_service_account_json", "") or "").strip()[:500],
        },
        "onliner_db_import": {
            "google_sheet_id": str(onliner_db_import.get("google_sheet_id", "") or "").strip()[:240],
            "google_sheet_name": str(onliner_db_import.get("google_sheet_name", "All_Catalog") or "All_Catalog").strip()[:120] or "All_Catalog",
        },
        "ui": {
            "show_checks_block": _coerce_bool(ui.get("show_checks_block", True), default=True),
        },
        "cache_api": {
            "allow_direct": _coerce_bool(cache_api.get("allow_direct", True), default=True),
            "retry_attempts": _coerce_int(cache_api.get("retry_attempts", 3), 3, min_value=1, max_value=12),
            "backoff_sec": _coerce_float(cache_api.get("backoff_sec", 0.6), 0.6, min_value=0.0, max_value=5.0),
            "proxy_cooldown_sec": _coerce_int(cache_api.get("proxy_cooldown_sec", 180), 180, min_value=10, max_value=3600),
            "max_parallel_workers": _coerce_int(cache_api.get("max_parallel_workers", 10), 10, min_value=1, max_value=24),
        },
        "onliner_b2b": {
            "enabled": _coerce_bool(onliner_b2b.get("enabled", False), default=False),
            "base_url": str(onliner_b2b.get("base_url", "https://b2bapi.onliner.by") or "https://b2bapi.onliner.by").strip()[:200],
            "price_api_base_url": str(onliner_b2b.get("price_api_base_url") or "https://price.api.onliner.by").strip()[:200],
            "client_id": str(onliner_b2b.get("client_id", "") or "").strip()[:200],
            "client_secret": str(onliner_b2b.get("client_secret", "") or "").strip()[:400],
            "token_url": str(onliner_b2b.get("token_url", "https://b2bapi.onliner.by/oauth/token") or "https://b2bapi.onliner.by/oauth/token").strip()[:240],
            "verify_ssl": _coerce_bool(onliner_b2b.get("verify_ssl", True), default=True),
            "timeout_sec": _coerce_int(onliner_b2b.get("timeout_sec", 20), 20, min_value=5, max_value=120),
        },
        "suppliers": {
            "filename_rules": _normalize_filename_rules(suppliers.get("filename_rules", [])),
        },
        "api_sources": _normalize_api_sources(api_sources),
        "uploads_cleanup": {
            "keep_last_sessions": _coerce_int(uploads_cleanup.get("keep_last_sessions", 20), 20, min_value=3, max_value=200),
            "keep_days": _coerce_int(uploads_cleanup.get("keep_days", 7), 7, min_value=1, max_value=90),
            "keep_api_fetch_hours": _coerce_int(uploads_cleanup.get("keep_api_fetch_hours", 12), 12, min_value=1, max_value=168),
        },
        "no_id_search": {
            "max_candidates": _coerce_int(no_id_search.get("max_candidates", 80), 80, min_value=10, max_value=150),
            "max_queries": _coerce_int(no_id_search.get("max_queries", 4), 4, min_value=1, max_value=8),
            "prefer_paren_model": _coerce_bool(no_id_search.get("prefer_paren_model", True), default=True),
            "prefer_article_tokens": _coerce_bool(no_id_search.get("prefer_article_tokens", True), default=True),
            "include_brand_token": _coerce_bool(no_id_search.get("include_brand_token", True), default=True),
            "require_category_hint": _coerce_bool(no_id_search.get("require_category_hint", False), default=False),
            "category_rules_text": str(no_id_search.get("category_rules_text", APP_SETTINGS_DEFAULTS["no_id_search"]["category_rules_text"]) or APP_SETTINGS_DEFAULTS["no_id_search"]["category_rules_text"]).strip(),
        },
        "verify_id": {
            "match_threshold": _coerce_float(verify_id.get("match_threshold", 0.74), 0.74, min_value=0.1, max_value=0.99),
            "trust_manual_confirmed": _coerce_bool(verify_id.get("trust_manual_confirmed", True), default=True),
            "force_refresh_api": _coerce_bool(verify_id.get("force_refresh_api", True), default=True),
            "api_no_name_status": "mismatch" if str(verify_id.get("api_no_name_status", "review")).strip().lower() == "mismatch" else "review",
            "require_article_or_model_priority": _coerce_bool(verify_id.get("require_article_or_model_priority", False), default=False),
        },
        "uploads_cleanup": {
            "keep_last_sessions": _coerce_int(uploads_cleanup.get("keep_last_sessions", 20), 20, min_value=3, max_value=200),
            "keep_days": _coerce_int(uploads_cleanup.get("keep_days", 7), 7, min_value=1, max_value=90),
            "keep_api_fetch_hours": _coerce_int(uploads_cleanup.get("keep_api_fetch_hours", 12), 12, min_value=1, max_value=168),
        },
    }


def load_app_settings():
    if not APP_SETTINGS_FILE.exists():
        return _normalize_app_settings()
    try:
        with open(APP_SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data = _normalize_app_settings(data)
    # Overlay secrets from environment (.env) so they never live in JSON
    try:
        from config import cfg as _env_cfg
        # Onliner B2B
        b2b = data.setdefault("onliner_b2b", {})
        if not str(b2b.get("client_id") or "").strip():
            b2b["client_id"] = _env_cfg.onliner_b2b_client_id
        if not str(b2b.get("client_secret") or "").strip():
            b2b["client_secret"] = _env_cfg.onliner_b2b_client_secret
        # Google Sheets
        export = data.setdefault("export", {})
        if not str(export.get("google_sheets_spreadsheet_url_or_id") or "").strip():
            export["google_sheets_spreadsheet_url_or_id"] = _env_cfg.google_sheets_spreadsheet_id
        if not str(export.get("google_sheets_service_account_json") or "").strip():
            export["google_sheets_service_account_json"] = _env_cfg.google_sheets_sa_json
        if not str(export.get("google_sheets_tab") or "").strip():
            export["google_sheets_tab"] = _env_cfg.google_sheets_tab
        # Onliner DB import
        db_import = data.setdefault("onliner_db_import", {})
        if not str(db_import.get("google_sheet_id") or "").strip():
            db_import["google_sheet_id"] = _env_cfg.google_sheets_spreadsheet_id
        if not str(db_import.get("google_sheet_name") or "").strip():
            db_import["google_sheet_name"] = _env_cfg.onliner_db_sheet_name
        # API sources
        sources = data.setdefault("api_sources", {})
        # IVEN
        iven = sources.setdefault("iven", {})
        if not str(iven.get("file_url") or "").strip():
            iven["file_url"] = _env_cfg.iven_file_url
        # Tradex
        tradex = sources.setdefault("tradex", {})
        if not str(tradex.get("file_url") or "").strip():
            tradex["file_url"] = _env_cfg.tradex_file_url
        # N-Tech
        ntech = sources.setdefault("ntech", {})
        if not str(ntech.get("username") or "").strip():
            ntech["username"] = _env_cfg.ntech_username
        if not str(ntech.get("password") or "").strip():
            ntech["password"] = _env_cfg.ntech_password
    except Exception:
        pass
    return data


def save_app_settings(settings):
    payload = _normalize_app_settings(settings)
    invalidate_onliner_b2b_token()
    # Strip secrets before writing to JSON (they live in .env only)
    b2b = payload.get("onliner_b2b")
    if isinstance(b2b, dict):
        b2b["client_id"] = ""
        b2b["client_secret"] = ""
    export = payload.get("export")
    if isinstance(export, dict):
        export["google_sheets_spreadsheet_url_or_id"] = ""
        export["google_sheets_service_account_json"] = ""
        export["google_sheets_tab"] = ""
    db_import = payload.get("onliner_db_import")
    if isinstance(db_import, dict):
        db_import["google_sheet_id"] = ""
        db_import["google_sheet_name"] = ""
    sources = payload.get("api_sources")
    if isinstance(sources, dict):
        for key in ("iven", "tradex"):
            src = sources.get(key)
            if isinstance(src, dict):
                src["file_url"] = ""
        ntech = sources.get("ntech")
        if isinstance(ntech, dict):
            ntech["username"] = ""
            ntech["password"] = ""
    with open(APP_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    save_onliner_api_settings(payload.get("cache_api", {}))
    return payload


def get_onliner_b2b_settings():
    settings = load_app_settings()
    cfg = (settings.get("onliner_b2b") or {})
    return {
        "enabled": _coerce_bool(cfg.get("enabled", False), default=False),
        "base_url": str(cfg.get("base_url", "https://b2bapi.onliner.by") or "https://b2bapi.onliner.by").strip(),
        "price_api_base_url": str(cfg.get("price_api_base_url") or "https://price.api.onliner.by").strip(),
        "client_id": str(cfg.get("client_id", "") or "").strip(),
        "client_secret": str(cfg.get("client_secret", "") or "").strip(),
        "token_url": str(cfg.get("token_url", "https://b2bapi.onliner.by/oauth/token") or "https://b2bapi.onliner.by/oauth/token").strip(),
        "verify_ssl": _coerce_bool(cfg.get("verify_ssl", True), default=True),
        "timeout_sec": _coerce_int(cfg.get("timeout_sec", 20), 20, min_value=5, max_value=120),
    }


def invalidate_onliner_b2b_token():
    with B2B_TOKEN_LOCK:
        B2B_TOKEN_CACHE["access_token"] = ""
        B2B_TOKEN_CACHE["expires_at"] = 0


def onliner_b2b_get_token(force_refresh=False):
    cfg = get_onliner_b2b_settings()
    if not cfg.get("enabled"):
        raise RuntimeError("Onliner B2B API выключен в настройках.")
    client_id = str(cfg.get("client_id", "") or "").strip()
    client_secret = str(cfg.get("client_secret", "") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Не заполнены Client ID / Client Secret для Onliner B2B API.")

    now = int(time.time())
    with B2B_TOKEN_LOCK:
        cached_token = str(B2B_TOKEN_CACHE.get("access_token", "") or "").strip()
        cached_expires_at = int(B2B_TOKEN_CACHE.get("expires_at", 0) or 0)
        if (not force_refresh) and cached_token and cached_expires_at - now > 30:
            return {
                "access_token": cached_token,
                "expires_at": cached_expires_at,
                "expires_in": max(0, cached_expires_at - now),
                "token_type": "Bearer",
                "source": "cache",
            }

    pair = f"{client_id}:{client_secret}"
    basic = base64.b64encode(pair.encode("utf-8")).decode("ascii")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {basic}",
    }
    resp = requests.post(
        str(cfg.get("token_url") or "https://b2bapi.onliner.by/oauth/token"),
        headers=headers,
        data={"grant_type": "client_credentials"},
        verify=bool(cfg.get("verify_ssl", True)),
        timeout=int(cfg.get("timeout_sec", 20) or 20),
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    access_token = str(payload.get("access_token", "") or "").strip()
    expires_in = _coerce_int(payload.get("expires_in", 300), 300, min_value=60, max_value=86400)
    token_type = str(payload.get("token_type", "Bearer") or "Bearer").strip() or "Bearer"
    if not access_token:
        raise RuntimeError("Onliner B2B API не вернул access_token.")
    expires_at = int(time.time()) + int(expires_in)
    with B2B_TOKEN_LOCK:
        B2B_TOKEN_CACHE["access_token"] = access_token
        B2B_TOKEN_CACHE["expires_at"] = expires_at
    return {
        "access_token": access_token,
        "expires_at": expires_at,
        "expires_in": expires_in,
        "token_type": token_type,
        "source": "oauth",
    }


def onliner_b2b_request(method, path, params=None, json_body=None, force_token_refresh=False):
    cfg = get_onliner_b2b_settings()
    token_info = onliner_b2b_get_token(force_refresh=force_token_refresh)
    base_url = str(cfg.get("base_url", "https://b2bapi.onliner.by") or "https://b2bapi.onliner.by").rstrip("/")
    rel_path = "/" + str(path or "").lstrip("/")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token_info['access_token']}",
    }
    resp = requests.request(
        method=str(method or "GET").upper(),
        url=base_url + rel_path,
        headers=headers,
        params=params,
        json=json_body,
        verify=bool(cfg.get("verify_ssl", True)),
        timeout=int(cfg.get("timeout_sec", 20) or 20),
    )
    return resp


def onliner_b2b_price_request(method, path, params=None, json_body=None, force_token_refresh=False):
    """HTTP к API прайс-листов (экспорт позиций / цены конкурентов), хост по умолчанию price.api.onliner.by."""
    cfg = get_onliner_b2b_settings()
    token_info = onliner_b2b_get_token(force_refresh=force_token_refresh)
    base_url = str(cfg.get("price_api_base_url", "https://price.api.onliner.by") or "https://price.api.onliner.by").rstrip("/")
    rel_path = "/" + str(path or "").lstrip("/")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token_info['access_token']}",
    }
    return requests.request(
        method=str(method or "GET").upper(),
        url=base_url + rel_path,
        headers=headers,
        params=params,
        json=json_body,
        verify=bool(cfg.get("verify_ssl", True)),
        timeout=int(cfg.get("timeout_sec", 20) or 20),
    )


def _normalize_b2b_dict_items(payload):
    if isinstance(payload, list):
        out = []
        for idx, item in enumerate(payload):
            if isinstance(item, dict):
                entry = dict(item)
                if "id" not in entry and idx is not None:
                    entry["id"] = str(idx)
                out.append(entry)
        return out
    if not isinstance(payload, dict):
        return []
    out = []
    numeric_like_keys = []
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip()
        if re.fullmatch(r"\d+", key or ""):
            numeric_like_keys.append(key)
        if isinstance(raw_value, dict):
            entry = dict(raw_value)
            entry.setdefault("id", key)
            out.append(entry)
        else:
            out.append({"id": key, "name": str(raw_value or "").strip()})
    if numeric_like_keys and len(numeric_like_keys) == len(payload):
        return out
    for nested_key in ("items", "data", "results", "sections", "manufacturers", "products"):
        nested = payload.get(nested_key)
        if isinstance(nested, (list, dict)):
            items = _normalize_b2b_dict_items(nested)
            if items:
                return items
    return out


def _b2b_cache_get(bucket, key=None, ttl=3600):
    now = int(time.time())
    with B2B_CATALOG_LOCK:
        holder = B2B_CATALOG_CACHE.get(bucket)
        if key is None:
            if isinstance(holder, dict) and now - int(holder.get("ts", 0) or 0) <= ttl:
                return holder.get("items")
            return None
        if isinstance(holder, dict):
            item = holder.get(str(key))
            if isinstance(item, dict) and now - int(item.get("ts", 0) or 0) <= ttl:
                return item.get("items")
    return None


def _b2b_cache_set(bucket, items, key=None):
    payload = {"ts": int(time.time()), "items": items if isinstance(items, list) else []}
    with B2B_CATALOG_LOCK:
        if key is None:
            B2B_CATALOG_CACHE[bucket] = payload
        else:
            if not isinstance(B2B_CATALOG_CACHE.get(bucket), dict):
                B2B_CATALOG_CACHE[bucket] = {}
            B2B_CATALOG_CACHE[bucket][str(key)] = payload


def onliner_b2b_get_sections(force_refresh=False):
    cached = None if force_refresh else _b2b_cache_get("sections", ttl=12 * 3600)
    if isinstance(cached, list):
        return cached
    resp = onliner_b2b_request("GET", "/sections", force_token_refresh=force_refresh)
    resp.raise_for_status()
    items = _normalize_b2b_dict_items(resp.json() if resp.content else {})
    _b2b_cache_set("sections", items)
    return items


def onliner_b2b_get_manufacturers(section_id, force_refresh=False):
    sid = str(section_id or "").strip()
    if not sid:
        return []
    cache_key = sid
    cached = None if force_refresh else _b2b_cache_get("manufacturers", key=cache_key, ttl=12 * 3600)
    if isinstance(cached, list):
        return cached
    resp = onliner_b2b_request("GET", f"/sections/{sid}/manufacturers", force_token_refresh=force_refresh)
    resp.raise_for_status()
    items = _normalize_b2b_dict_items(resp.json() if resp.content else {})
    _b2b_cache_set("manufacturers", items, key=cache_key)
    return items


def onliner_b2b_get_products(section_id, manufacturer_id, title="", force_refresh=False):
    sid = str(section_id or "").strip()
    mid = str(manufacturer_id or "").strip()
    title = str(title or "").strip()
    if not sid or not mid:
        return []
    cache_key = f"{sid}|{mid}|{title.lower()}"
    cached = None if force_refresh else _b2b_cache_get("products", key=cache_key, ttl=6 * 3600)
    if isinstance(cached, list):
        return cached
    params = {"title": title} if title else None
    resp = onliner_b2b_request("GET", f"/sections/{sid}/manufacturers/{mid}/products", params=params, force_token_refresh=force_refresh)
    resp.raise_for_status()
    items = _normalize_b2b_dict_items(resp.json() if resp.content else {})
    _b2b_cache_set("products", items, key=cache_key)
    return items


def onliner_b2b_get_articles(section_id, manufacturer_id, product_id, force_refresh=False):
    sid = str(section_id or "").strip()
    mid = str(manufacturer_id or "").strip()
    pid = normalize_onliner_id(product_id)
    if not sid or not mid or not pid:
        return []
    cache_key = f"{sid}|{mid}|{pid}"
    cached = None if force_refresh else _b2b_cache_get("articles", key=cache_key, ttl=24 * 3600)
    if isinstance(cached, list):
        return cached
    resp = onliner_b2b_request("GET", f"/sections/{sid}/manufacturers/{mid}/products/{pid}/articles", force_token_refresh=force_refresh)
    resp.raise_for_status()
    raw_items = resp.json() if resp.content else []
    items = []
    for item in (raw_items if isinstance(raw_items, list) else []):
        if isinstance(item, dict):
            art = str(item.get("article", "") or "").strip()
        else:
            art = str(item or "").strip()
        if art:
            items.append(art)
    _b2b_cache_set("articles", items, key=cache_key)
    return items


def onliner_b2b_resolve_catalog_path_for_product(target_oid, product_name="", category_name="", force_refresh=False):
    """По Onliner ID и названию находит sectionId и manufacturerId в B2B-каталоге (кешируется)."""
    cfg = get_onliner_b2b_settings()
    if not cfg.get("enabled"):
        return None, None
    oid = normalize_onliner_id(target_oid)
    if not oid:
        return None, None
    cache_key = str(oid)
    if not force_refresh:
        cached = _b2b_cache_get("product_path", key=cache_key, ttl=7 * 24 * 3600)
        if isinstance(cached, list) and len(cached) >= 2 and cached[0] and cached[1]:
            return str(cached[0]), str(cached[1])

    name = str(product_name or "").strip()
    if not name:
        dbp = db_get_product_by_id(oid)
        if isinstance(dbp, dict):
            name = str(dbp.get("name", "") or "").strip()
    if not name:
        return None, None

    try:
        sections = onliner_b2b_get_sections()
    except Exception:
        return None, None

    cat_hint = str(category_name or "").strip()
    section_tokens = _b2b_section_tokens(cat_hint, name)
    candidate_sections = []
    for section in sections:
        sec_id = str(section.get("id", "") or "").strip()
        sec_name = str(section.get("name", "") or "").strip()
        if not sec_id or not sec_name:
            continue
        low_name = sec_name.lower()
        score = 0
        for token in section_tokens:
            if token and token in low_name:
                score = max(score, len(token))
        if score > 0:
            candidate_sections.append((score, sec_id, sec_name))
    candidate_sections.sort(key=lambda x: x[0], reverse=True)
    candidate_sections = candidate_sections[:6] if candidate_sections else []
    if not candidate_sections and sections:
        candidate_sections = [
            (
                0,
                str(sections[i].get("id", "") or "").strip(),
                str(sections[i].get("name", "") or ""),
            )
            for i in range(min(8, len(sections)))
            if str(sections[i].get("id", "") or "").strip()
        ]

    brand = _preferred_brand_token(name)
    queries = []
    seen_queries = set()

    def _add_query(value):
        q = str(value or "").strip()
        if not q:
            return
        key = q.lower()
        if key in seen_queries:
            return
        seen_queries.add(key)
        queries.append(q)

    article = str(extract_article(name) or "").strip()
    if article:
        _add_query(article)
    for q in _priority_model_queries(name)[:2]:
        _add_query(q)
    _add_query(" ".join(_name_tokens(name)[:6]))
    _add_query(name[:90])
    queries = queries[:4]

    for _score, sec_id, _sec_name in candidate_sections:
        try:
            manufacturers = onliner_b2b_get_manufacturers(sec_id)
        except Exception:
            continue
        if brand:
            matching_manufacturers = [
                m for m in manufacturers
                if brand.lower() in str(m.get("name", "") or "").lower()
            ]
        else:
            matching_manufacturers = list(manufacturers[:6])
        if not matching_manufacturers:
            matching_manufacturers = list(manufacturers[:8])
        for manufacturer in matching_manufacturers[:10]:
            mid = str(manufacturer.get("id", "") or "").strip()
            if not mid:
                continue
            # Быстрый путь: один запрос полного списка товаров производителя (кеш sid|mid|),
            # вместо нескольких запросов с title — так в разы быстрее при массовом обновлении.
            try:
                products_full = onliner_b2b_get_products(sec_id, mid, title="")
            except Exception:
                products_full = []
            _scan_cap = 12000
            for i, product in enumerate(products_full):
                if i >= _scan_cap:
                    break
                if not isinstance(product, dict):
                    continue
                pid = normalize_onliner_id(product.get("id", ""))
                if pid == oid:
                    _b2b_cache_set("product_path", [sec_id, mid], key=cache_key)
                    return str(sec_id), str(mid)
            for query in queries:
                try:
                    products = onliner_b2b_get_products(sec_id, mid, title=query)
                except Exception:
                    continue
                for product in products[:160]:
                    if not isinstance(product, dict):
                        continue
                    pid = normalize_onliner_id(product.get("id", ""))
                    if pid == oid:
                        _b2b_cache_set("product_path", [sec_id, mid], key=cache_key)
                        return str(sec_id), str(mid)
    return None, None


def onliner_b2b_fetch_product_positions_export(section_id, manufacturer_id, product_id, force_token_refresh=False):
    """GET …/products/{productId}/positions — позиции (цены конкурентов) в формате прайс-листа."""
    sid = str(section_id or "").strip()
    mid = str(manufacturer_id or "").strip()
    pid = normalize_onliner_id(product_id)
    if not sid or not mid or not pid:
        return []
    rel = f"/sections/{sid}/manufacturers/{mid}/products/{pid}/positions"
    resp = onliner_b2b_price_request("GET", rel, force_token_refresh=force_token_refresh)
    resp.raise_for_status()
    payload = resp.json() if resp.content else []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        pos = payload.get("positions")
        if isinstance(pos, list):
            return [x for x in pos if isinstance(x, dict)]
    return _normalize_b2b_dict_items(payload)


def _parse_b2b_price_string(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        v = float(raw)
        return v if v > 0 else None
    if isinstance(raw, dict):
        for k in ("amount", "value", "BYN", "byn", "converted"):
            nested = raw.get(k)
            if isinstance(nested, dict):
                pv = _parse_b2b_price_string(nested.get("amount") or nested.get("value"))
                if pv is not None and pv > 0:
                    return pv
            else:
                pv = _parse_b2b_price_string(nested)
                if pv is not None and pv > 0:
                    return pv
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace(",", ".")
    return _safe_float(s)


def _b2b_row_price_value(row):
    """Цена из строки экспорта позиций (разные варианты полей JSON/XML)."""
    if not isinstance(row, dict):
        return None
    for key in ("pricePromo", "price_promo", "promoPrice"):
        pv = _parse_b2b_price_string(row.get(key))
        if pv is not None and pv > 0:
            return float(pv)
    for key in ("price", "Price", "cost", "amount"):
        pv = _parse_b2b_price_string(row.get(key))
        if pv is not None and pv > 0:
            return float(pv)
    return None


def _market_stats_from_b2b_position_rows(rows):
    if not isinstance(rows, list):
        rows = []
    if not rows:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": "b2b: нет позиций в ответе",
        }
    prices = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pv = _b2b_row_price_value(row)
        if pv is not None and pv > 0:
            prices.append(float(pv))
    if not prices:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": "b2b: позиции есть, но не удалось прочитать цену (поля price / pricePromo)",
        }
    offers_count = len(prices)
    min_price = float(min(prices))
    max_price = float(max(prices))
    avg_price = round(float(sum(prices)) / len(prices), 2)
    min_competitors = sum(1 for p in prices if p <= min_price * 1.02)
    avg_competitors = sum(1 for p in prices if abs(p - avg_price) <= max(1.0, avg_price * 0.05))
    return {
        "min": round(min_price, 2),
        "avg": avg_price,
        "max": round(max_price, 2),
        "offers": offers_count,
        "min_competitors": int(min_competitors),
        "avg_competitors": int(avg_competitors),
        "_error": False,
        "_error_reason": "",
    }


def _fetch_onliner_market_stats_b2b(onliner_id, product_name="", category_name=""):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True, "_error_reason": "пустой onliner id",
        }
    cfg = get_onliner_b2b_settings()
    if not cfg.get("enabled"):
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True, "_error_reason": "b2b выключен в настройках",
        }
    if not str(cfg.get("client_id", "") or "").strip() or not str(cfg.get("client_secret", "") or "").strip():
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True, "_error_reason": "b2b: не заданы client_id / client_secret",
        }
    try:
        sid, mid = onliner_b2b_resolve_catalog_path_for_product(
            oid, product_name=product_name, category_name=category_name,
        )
    except Exception as e:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": f"b2b resolve: {str(e)[:120]}",
        }
    if not sid or not mid:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": "b2b: не найден раздел/производитель для товара (нужно название в прайсе или в локальной базе)",
        }
    try:
        rows = onliner_b2b_fetch_product_positions_export(sid, mid, oid)
    except Exception as e:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": f"b2b positions: {str(e)[:160]}",
        }
    return _market_stats_from_b2b_position_rows(rows)


def _b2b_section_tokens(category_name, product_name=""):
    tokens = []
    inferred = normalize_catalog_category_name(category_name or infer_category(product_name or ""))
    alias_map = {
        "Процессор": ["процессор", "cpu"],
        "Кулер": ["кулер", "cooler"],
        "Охлаждение": ["охлаждение", "водяное охлаждение"],
        "Материнская плата": ["материнская плата"],
        "Оперативная память": ["оперативная память", "память ddr", "dram"],
        "SSD": ["ssd"],
        "Жесткий диск": ["жесткий диск", "hdd"],
        "Видеокарта": ["видеокарта"],
        "Блок питания": ["блок питания", "psu"],
        "Корпус": ["корпус"],
        "Монитор": ["монитор"],
        "Ноутбук": ["ноутбук"],
        "Системный блок": ["системный блок", "компьютер"],
        "Клавиатура": ["клавиатура"],
        "Мышь": ["мышь"],
        "Наушники": ["наушники", "гарнитура"],
        "Акустика": ["акустика", "колонки"],
        "Сеть": ["роутер", "сеть", "wifi"],
        "Накопители USB": ["usb накопитель", "флешка"],
        "Кабели и переходники": ["кабель", "переходник", "адаптер"],
        "Аксессуары": ["аксессуары"],
    }
    if inferred:
        tokens.extend(alias_map.get(inferred, [inferred.lower()]))
    raw_cat = str(category_name or "").strip().lower()
    if raw_cat and raw_cat not in tokens:
        tokens.append(raw_cat)
    out = []
    seen = set()
    for token in tokens:
        key = str(token or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def onliner_b2b_search_candidates(local_name, category_name="", limit=30):
    cfg = get_onliner_b2b_settings()
    if not cfg.get("enabled"):
        return []
    name = str(local_name or "").strip()
    if not name:
        return []
    try:
        sections = onliner_b2b_get_sections()
    except Exception:
        return []

    section_tokens = _b2b_section_tokens(category_name, name)
    candidate_sections = []
    for section in sections:
        sec_id = str(section.get("id", "") or "").strip()
        sec_name = str(section.get("name", "") or "").strip()
        if not sec_id or not sec_name:
            continue
        low_name = sec_name.lower()
        score = 0
        for token in section_tokens:
            if token and token in low_name:
                score = max(score, len(token))
        if score > 0:
            candidate_sections.append((score, sec_id, sec_name))
    candidate_sections.sort(key=lambda x: x[0], reverse=True)
    candidate_sections = candidate_sections[:3] if candidate_sections else []
    if not candidate_sections and sections:
        candidate_sections = [(0, str(sections[0].get("id", "")).strip(), str(sections[0].get("name", "")).strip())]

    brand = _preferred_brand_token(name)
    queries = []
    seen_queries = set()

    def _add_query(value):
        q = str(value or "").strip()
        if not q:
            return
        key = q.lower()
        if key in seen_queries:
            return
        seen_queries.add(key)
        queries.append(q)

    article = str(extract_article(name) or "").strip()
    if article:
        _add_query(article)
    for q in _priority_model_queries(name)[:2]:
        _add_query(q)
    _add_query(" ".join(_name_tokens(name)[:6]))
    _add_query(name[:90])
    queries = queries[:3]

    local_articles = _article_like_tokens(name)
    candidates = {}

    for _, sec_id, _sec_name in candidate_sections:
        try:
            manufacturers = onliner_b2b_get_manufacturers(sec_id)
        except Exception:
            continue
        if brand:
            matching_manufacturers = [
                m for m in manufacturers
                if brand.lower() in str(m.get("name", "") or "").lower()
            ]
        else:
            matching_manufacturers = list(manufacturers[:4])
        if not matching_manufacturers:
            matching_manufacturers = list(manufacturers[:4])

        for manufacturer in matching_manufacturers[:4]:
            mid = str(manufacturer.get("id", "") or "").strip()
            if not mid:
                continue
            for query in queries:
                try:
                    products = onliner_b2b_get_products(sec_id, mid, title=query)
                except Exception:
                    continue
                for product in products[:20]:
                    pid = normalize_onliner_id(product.get("id", ""))
                    pname = str(product.get("name", "") or "").strip()
                    if not pid or not pname:
                        continue
                    if pid in candidates:
                        continue
                    allowed, _reason = _strict_candidate_allowed(name, pname)
                    if not allowed:
                        continue
                    cmp = calc_name_match(name, pname)
                    score = float(cmp.get("score", 0.0) or 0.0)
                    if cmp.get("match"):
                        score = max(score, 0.76)
                    purl = ""
                    cached_product = db_get_product_by_id(pid)
                    if isinstance(cached_product, dict):
                        purl = str(cached_product.get("url", "") or "").strip()
                    article_hits = []
                    if local_articles and score >= 0.45:
                        try:
                            article_hits = onliner_b2b_get_articles(sec_id, mid, pid)
                        except Exception:
                            article_hits = []
                    remote_articles = {_normalize_compact_name(x) for x in article_hits if str(x or "").strip()}
                    if local_articles and remote_articles:
                        if local_articles.intersection(remote_articles):
                            score = max(score, 0.98)
                        else:
                            score *= 0.55
                    if score < 0.34:
                        continue
                    candidates[pid] = {
                        "id": pid,
                        "name": pname,
                        "url": purl,
                        "score": round(float(score), 3),
                        "source": "b2b",
                        "reason": str(cmp.get("reason", "") or ""),
                    }
                    db_upsert_product(pid, pname, purl, source="b2b")
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    items = list(candidates.values())
    items.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
    return items[:limit]


def load_supplier_snapshots():
    from price_mixer.db import get_db
    try:
        return get_db().get_supplier_snapshots()
    except Exception:
        pass
    return {}


def save_supplier_snapshots(data):
    from price_mixer.db import get_db
    try:
        suppliers = data.get("suppliers", {})
        for supplier, sessions in suppliers.items():
            for session_id, snapshot in sessions.items():
                get_db().set_supplier_snapshot(supplier, session_id, snapshot)
    except Exception:
        pass


def load_api_fetch_history():
    if not API_FETCH_HISTORY_FILE.exists():
        return []
    try:
        with open(API_FETCH_HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_api_fetch_history(rows):
    payload = rows if isinstance(rows, list) else []
    with open(API_FETCH_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(payload[-300:], f, ensure_ascii=False, indent=2)


def append_api_fetch_history(entry):
    if not isinstance(entry, dict):
        return
    rows = load_api_fetch_history()
    rows.append(entry)
    rows.sort(key=lambda x: int((x or {}).get("finished_at", 0) or (x or {}).get("started_at", 0) or 0), reverse=True)
    save_api_fetch_history(rows)


def get_api_fetch_history(limit=20):
    rows = load_api_fetch_history()
    rows.sort(key=lambda x: int((x or {}).get("finished_at", 0) or (x or {}).get("started_at", 0) or 0), reverse=True)
    return rows[:max(1, int(limit or 20))]


def _snapshot_price(value):
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return None
    return round(float(num), 2)


def _snapshot_item_key(row):
    oid = normalize_onliner_id(row.get("OnlinerID", ""))
    if oid:
        return f"oid:{oid}"
    name_key = _normalize_name_key(row.get("Название", ""))
    if name_key:
        return f"name:{name_key}"
    return ""


def build_supplier_snapshot(df, supplier_name):
    items = {}
    for _, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip()
        if supplier_name and supplier and supplier != supplier_name:
            continue
        key = _snapshot_item_key(row)
        if not key:
            continue
        items[key] = {
            "name": str(row.get("Название", "")).strip(),
            "price": _snapshot_price(row.get("Цена", "")),
            "onliner_id": normalize_onliner_id(row.get("OnlinerID", "")),
            "category": str(row_category(row)).strip(),
            "has_id": bool(normalize_onliner_id(row.get("OnlinerID", ""))),
        }
    return {
        "updated_at": int(time.time()),
        "items": items,
    }


def compare_supplier_snapshot(previous_snapshot, current_snapshot):
    prev_items = previous_snapshot.get("items") if isinstance(previous_snapshot, dict) else {}
    curr_items = current_snapshot.get("items") if isinstance(current_snapshot, dict) else {}
    if not isinstance(prev_items, dict):
        prev_items = {}
    if not isinstance(curr_items, dict):
        curr_items = {}

    def _coerce_snapshot_item(item):
        if isinstance(item, dict):
            return item
        if isinstance(item, str):
            text = item.strip()
            return {
                "name": text,
                "price": None,
                "onliner_id": "",
                "category": "",
            }
        return {
            "name": "",
            "price": None,
            "onliner_id": "",
            "category": "",
        }

    prev_keys = set(prev_items.keys())
    curr_keys = set(curr_items.keys())
    new_keys = sorted(curr_keys - prev_keys)
    removed_keys = sorted(prev_keys - curr_keys)
    shared_keys = sorted(curr_keys & prev_keys)

    price_changed = []
    for key in shared_keys:
        old_item = _coerce_snapshot_item(prev_items.get(key))
        new_item = _coerce_snapshot_item(curr_items.get(key))
        old_price = old_item.get("price")
        new_price = new_item.get("price")
        if old_price is None or new_price is None:
            continue
        try:
            if abs(float(new_price) - float(old_price)) >= 0.01:
                price_changed.append({
                    "name": str(new_item.get("name") or old_item.get("name") or "").strip(),
                    "old_price": float(old_price),
                    "new_price": float(new_price),
                    "onliner_id": str(new_item.get("onliner_id") or old_item.get("onliner_id") or "").strip(),
                })
        except Exception:
            continue

    new_items = []
    new_without_id = []
    for key in new_keys:
        item = _coerce_snapshot_item(curr_items.get(key))
        payload = {
            "name": str(item.get("name") or "").strip(),
            "price": item.get("price"),
            "onliner_id": str(item.get("onliner_id") or "").strip(),
            "category": str(item.get("category") or "").strip(),
        }
        new_items.append(payload)
        if not payload["onliner_id"]:
            new_without_id.append(payload)

    removed_items = []
    for key in removed_keys:
        item = _coerce_snapshot_item(prev_items.get(key))
        removed_items.append({
            "name": str(item.get("name") or "").strip(),
            "price": item.get("price"),
            "onliner_id": str(item.get("onliner_id") or "").strip(),
            "category": str(item.get("category") or "").strip(),
        })

    return {
        "available": True,
        "previous_updated_at": int(previous_snapshot.get("updated_at", 0) or 0) if isinstance(previous_snapshot, dict) else 0,
        "current_updated_at": int(current_snapshot.get("updated_at", 0) or 0) if isinstance(current_snapshot, dict) else 0,
        "new_count": len(new_items),
        "removed_count": len(removed_items),
        "price_changed_count": len(price_changed),
        "new_without_id_count": len(new_without_id),
        "samples": {
            "new_items": new_items[:10],
            "removed_items": removed_items[:10],
            "price_changed": price_changed[:10],
            "new_without_id": new_without_id[:10],
        },
        "filters": {
            "new_names": [str(item.get("name") or "").strip() for item in new_items if str(item.get("name") or "").strip()],
            "new_without_id_names": [str(item.get("name") or "").strip() for item in new_without_id if str(item.get("name") or "").strip()],
        },
    }


def save_session_supplier_diff(session_dir, diff_data):
    if not session_dir:
        return
    try:
        with open(Path(session_dir) / "supplier_diff.json", "w", encoding="utf-8") as f:
            json.dump(diff_data or {}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Не удалось сохранить supplier diff: {e}")


def load_session_supplier_diff(session_dir):
    if not session_dir:
        return {}
    path = Path(session_dir) / "supplier_diff.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_api_source_status_key():
    key = str(session.get("api_fetch_key", "") or "").strip()
    if not key:
        key = str(uuid.uuid4())[:12]
        session["api_fetch_key"] = key
    return key


def _get_source_runtime(source_key, client_key=None):
    client_key = str(client_key or "").strip() or _get_api_source_status_key()
    with SOURCE_FETCH_LOCK:
        client_state = source_fetch_statuses.setdefault(client_key, {})
        return client_state.setdefault(source_key, {
            "running": False,
            "progress": 0,
            "downloaded": 0,
            "total_bytes": 0,
            "status": "idle",
            "message": "",
            "ready": False,
            "source_key": source_key,
            "label": source_key.upper(),
            "supplier": "",
            "file_path": "",
            "file_name": "",
            "started_at": 0,
            "finished_at": 0,
        })


def _update_source_runtime(source_key, client_key=None, **kwargs):
    with SOURCE_FETCH_LOCK:
        state = _get_source_runtime(source_key, client_key=client_key)
        state.update(kwargs)
        return dict(state)


def _serialize_source_runtime(state):
    data = dict(state or {})
    for key in ("started_at", "finished_at", "progress", "downloaded", "total_bytes"):
        if key in data:
            try:
                data[key] = int(data[key])
            except Exception:
                pass
    return data


def _iter_api_sources_for_ui(settings=None):
    settings = settings or load_app_settings()
    sources = ((settings or {}).get("api_sources") or {})
    items = []
    for key, cfg in sources.items():
        if not isinstance(cfg, dict):
            continue
        item = {
            "key": key,
            "label": str(cfg.get("label", key.upper()) or key.upper()),
            "supplier": str(cfg.get("supplier", key.upper()) or key.upper()),
            "enabled": bool(cfg.get("enabled")),
            "configured": False,
            "mode": str(cfg.get("mode", "direct_file") or "direct_file"),
        }
        if item["mode"] == "ntech_json":
            item["configured"] = bool(str(cfg.get("auth_url", "")).strip() and str(cfg.get("price_url", "")).strip() and str(cfg.get("username", "")).strip() and str(cfg.get("password", "")))
        else:
            item["configured"] = bool(str(cfg.get("file_url", "")).strip())
        items.append(item)
    return items


def _source_temp_dir(client_key=None):
    client_key = str(client_key or "").strip() or _get_api_source_status_key()
    path = UPLOAD_DIR / f"_api_fetch_{client_key}"
    path.mkdir(exist_ok=True)
    return path


def _default_source_headers(source_key):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream,*/*",
    }
    return headers


def _resolve_curl_cmd():
    """Return available curl executable for current OS."""
    cmd = shutil.which("curl") or shutil.which("curl.exe")
    if cmd:
        return cmd
    raise RuntimeError("Системный curl не найден. Установите curl и перезапустите приложение.")


def _head_content_length_via_curl(url, verify_ssl, headers=None):
    headers = headers or {}
    cmd = [_resolve_curl_cmd(), "-I", "-L", "--silent", "--show-error"]
    if not verify_ssl:
        cmd.append("-k")
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            return 0
        match = re.search(r"(?im)^Content-Length:\s*(\d+)\s*$", result.stdout or "")
        return int(match.group(1)) if match else 0
    except Exception:
        return 0


def _curl_download_to_path(url, target_path, verify_ssl, source_key, client_key=None, headers=None):
    headers = headers or {}
    is_iven = str(source_key).strip().lower() == "iven"
    total = _head_content_length_via_curl(url, verify_ssl, headers=headers)
    download_message = "IVEN отвечает медленно, это нормально. Идет скачивание через системный клиент." if is_iven else "Скачиваю прайс через системный клиент..."
    _update_source_runtime(source_key, client_key=client_key, total_bytes=total, status="downloading", message=download_message, progress=5)
    cmd = [_resolve_curl_cmd(), "-L", "--silent", "--show-error", "--output", str(target_path)]
    if not verify_ssl:
        cmd.append("-k")
    if is_iven:
        cmd.append("--http1.1")
        if total > 0:
            cmd.extend(["-r", f"0-{total - 1}"])
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    cmd.append(url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    completed_early = False
    last_size = -1
    stable_count = 0
    try:
        while proc.poll() is None:
            size = target_path.stat().st_size if target_path.exists() else 0
            if total > 0:
                progress = min(95, int((size / total) * 100))
            else:
                progress = min(95, max(5, int(size / 65536))) if size else 5
            _update_source_runtime(source_key, client_key=client_key, downloaded=size, progress=progress)
            if is_iven:
                if size == last_size and size > 0:
                    stable_count += 1
                else:
                    stable_count = 0
                last_size = size
                if stable_count >= 6:
                    try:
                        if zipfile.is_zipfile(target_path):
                            completed_early = True
                            proc.terminate()
                            break
                    except Exception:
                        pass
            time.sleep(0.35)
        stdout, stderr = proc.communicate(timeout=10)
    except Exception:
        proc.kill()
        raise
    if proc.returncode != 0 and not completed_early:
        err = (stderr or b"").decode("utf-8", errors="ignore").strip()
        raise RuntimeError(err or f"curl exited with code {proc.returncode}")
    size = target_path.stat().st_size if target_path.exists() else 0
    _update_source_runtime(source_key, client_key=client_key, downloaded=size, total_bytes=total or size, progress=100)


def _stream_download_to_path(url, target_path, verify_ssl, source_key, client_key=None, headers=None):
    headers = headers or {}
    downloaded = 0
    with requests.get(url, stream=True, verify=verify_ssl, timeout=120, headers=headers) as resp:
        resp.raise_for_status()
        total = 0
        try:
            total = int(resp.headers.get("Content-Length", "0") or 0)
        except Exception:
            total = 0
        _update_source_runtime(source_key, client_key=client_key, total_bytes=total, status="downloading", message="Скачиваю прайс...")
        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=262144):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                progress = int((downloaded / total) * 100) if total > 0 else min(95, max(5, int(downloaded / 65536)))
                _update_source_runtime(source_key, client_key=client_key, downloaded=downloaded, progress=progress)
    _update_source_runtime(source_key, client_key=client_key, downloaded=downloaded, total_bytes=downloaded or _get_source_runtime(source_key, client_key=client_key).get("total_bytes", 0))


def _ntech_reserve_url_from_price_url(price_url):
    raw = str(price_url or "").strip()
    if not raw:
        return ""
    if raw.endswith("/price"):
        return raw[:-len("/price")] + "/list"
    return raw.rstrip("/") + "/list"


def _ntech_api_json(method, url, token, verify_ssl=False, json_body=None, timeout=120):
    headers = {"Authorization": f"Bearer {token}"}
    method = str(method or "get").strip().lower() or "get"
    if method == "post":
        resp = requests.post(url, headers=headers, json=json_body, verify=verify_ssl, timeout=timeout)
    else:
        resp = requests.get(url, headers=headers, verify=verify_ssl, timeout=timeout)
    if resp.status_code == 401:
        raise PermissionError("unauthorized")
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


def _load_ntech_orders(token, reserve_url, verify_ssl=False):
    if not str(reserve_url or "").strip():
        return {"orders": [], "warning": None}
    try:
        payload = _ntech_api_json("get", reserve_url, token, verify_ssl=verify_ssl, timeout=120)
    except requests.HTTPError as e:
        response = getattr(e, "response", None)
        if response is not None and response.status_code == 404:
            return {"orders": [], "warning": "API резервов N-Tech временно недоступно (HTTP 404). Продолжаю без резервов."}
        raise
    orders = payload.get("orders") or []
    return {"orders": orders if isinstance(orders, list) else [], "warning": None}


def _build_ntech_dataframe(payload, reserve_orders=None):
    products = []
    if isinstance(payload, dict):
        products = payload.get("products") or []
    rows = []
    last_category = ""
    for item in products:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or item.get("group") or "").strip()
        if category and category != last_category:
            rows.append({
                "код": "",
                "": category,
                "Наименование": "",
                "Гарантия": "",
                "Рекомендуемая\n розничная\n цена": "",
                "Цена без НДС": "",
                "Цена с НДС": "",
            })
            last_category = category
        rows.append({
            "код": item.get("id", ""),
            "": "",
            "Наименование": item.get("name", ""),
            "Гарантия": item.get("warranty", ""),
            "Рекомендуемая\n розничная\n цена": item.get("recommended_price") or item.get("retail_price") or "",
            "Цена без НДС": item.get("price", ""),
            "Цена с НДС": item.get("price_with_vat", ""),
        })
    return pd.DataFrame(rows)


def _fetch_api_source_worker(source_key, client_key):
    settings = load_app_settings()
    cfg = (((settings or {}).get("api_sources") or {}).get(source_key) or {})
    label = str(cfg.get("label", source_key.upper()) or source_key.upper())
    supplier = str(cfg.get("supplier", label) or label)
    mode = str(cfg.get("mode", "direct_file") or "direct_file")
    verify_ssl = bool(cfg.get("verify_ssl"))
    temp_dir = _source_temp_dir(client_key=client_key)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_key).strip("_") or source_key
    target_path = temp_dir / f"{safe_name}.xlsx"
    _update_source_runtime(
        source_key,
        client_key=client_key,
        running=True,
        progress=0,
        downloaded=0,
        total_bytes=0,
        ready=False,
        status="starting",
        message="IVEN отвечает медленно, это нормально. Подготовка может занять до 2 минут." if str(source_key).strip().lower() == "iven" else "Подготавливаю выгрузку...",
        label=label,
        supplier=supplier,
        file_path="",
        file_name=target_path.name,
        started_at=time.time(),
        finished_at=0,
    )
    started_at = int(time.time())
    try:
        if mode == "ntech_json":
            auth_url = str(cfg.get("auth_url", "")).strip()
            price_url = str(cfg.get("price_url", "")).strip()
            username = str(cfg.get("username", "")).strip()
            password = str(cfg.get("password", ""))
            if not (auth_url and price_url and username and password):
                raise ValueError("Источник не настроен")
            _update_source_runtime(source_key, client_key=client_key, progress=10, status="auth", message="Авторизация...")
            auth_resp = requests.post(auth_url, json={"username": username, "password": password}, verify=verify_ssl, timeout=60)
            auth_resp.raise_for_status()
            token = (auth_resp.json() or {}).get("token")
            if not token:
                raise ValueError("Токен не получен")
            _update_source_runtime(source_key, client_key=client_key, progress=45, status="fetching", message="Получаю прайс N-Tech...")
            price_resp = None
            last_err = None
            # 1) POST — legacy API JSON (/orders/v1/price)
            # 2) GET — compatible with cabinet-like direct file endpoints (xlsx/csv/attachment)
            for method in ("post", "get"):
                try:
                    req_fn = requests.post if method == "post" else requests.get
                    resp = req_fn(
                        price_url,
                        headers={"Authorization": f"Bearer {token}"},
                        verify=verify_ssl,
                        timeout=120,
                    )
                    if resp.status_code == 401:
                        _update_source_runtime(source_key, client_key=client_key, progress=20, status="auth", message="Обновляю токен...")
                        auth_resp = requests.post(auth_url, json={"username": username, "password": password}, verify=verify_ssl, timeout=60)
                        auth_resp.raise_for_status()
                        token = (auth_resp.json() or {}).get("token")
                        if not token:
                            raise ValueError("Токен не получен")
                        _update_source_runtime(source_key, client_key=client_key, progress=45, status="fetching", message="Повторно получаю прайс...")
                        resp = req_fn(
                            price_url,
                            headers={"Authorization": f"Bearer {token}"},
                            verify=verify_ssl,
                            timeout=120,
                        )
                    resp.raise_for_status()
                    price_resp = resp
                    break
                except Exception as e:
                    last_err = e
            if price_resp is None:
                raise last_err or RuntimeError("Не удалось получить прайс N-Tech")

            content_type = str(price_resp.headers.get("Content-Type", "") or "").lower()
            content_disp = str(price_resp.headers.get("Content-Disposition", "") or "").lower()
            body = price_resp.content or b""
            looks_like_file = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in content_type
                or "application/vnd.ms-excel" in content_type
                or "text/csv" in content_type
                or "application/octet-stream" in content_type
                or "attachment" in content_disp
                or body.startswith(b"PK\x03\x04")
            )
            if looks_like_file:
                _update_source_runtime(source_key, client_key=client_key, progress=75, status="building", message="Сохраняю файл прайса N-Tech...")
                with open(target_path, "wb") as f:
                    f.write(body)
            else:
                payload = price_resp.json() or {}
                _update_source_runtime(source_key, client_key=client_key, progress=75, status="building", message="Собираю Excel...")
                df = _build_ntech_dataframe(payload)
                df.to_excel(target_path, index=False, sheet_name="Прайс N-Tech")
        else:
            file_url = str(cfg.get("file_url", "")).strip()
            if not file_url:
                raise ValueError("Источник не настроен")
            headers = _default_source_headers(source_key)
            if str(source_key).strip().lower() == "iven":
                _curl_download_to_path(file_url, target_path, verify_ssl, source_key, client_key=client_key, headers=headers)
            else:
                try:
                    _stream_download_to_path(file_url, target_path, verify_ssl, source_key, client_key=client_key, headers=headers)
                except requests.exceptions.RequestException:
                    _curl_download_to_path(file_url, target_path, verify_ssl, source_key, client_key=client_key, headers=headers)
        _update_source_runtime(
            source_key,
            client_key=client_key,
            running=False,
            progress=100,
            status="ready",
            message="Прайс получен. Можно обрабатывать.",
            ready=True,
            file_path=str(target_path),
            file_name=target_path.name,
            finished_at=time.time(),
        )
        final_state = _get_source_runtime(source_key, client_key=client_key)
        file_size = target_path.stat().st_size if target_path.exists() else int(final_state.get("downloaded", 0) or 0)
        finished_at = int(final_state.get("finished_at", time.time()) or time.time())
        append_api_fetch_history({
            "source_key": source_key,
            "label": label,
            "supplier": supplier,
            "event_type": "fetch",
            "status": "ok",
            "message": "Прайс получен",
            "file_name": target_path.name,
            "file_size": int(file_size or 0),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": max(0, finished_at - started_at),
        })
    except Exception as e:
        error_message = str(e)[:240] or "Ошибка выгрузки"
        _update_source_runtime(
            source_key,
            client_key=client_key,
            running=False,
            ready=False,
            status="error",
            message=error_message,
            finished_at=time.time(),
        )
        finished_at = int(time.time())
        file_size = target_path.stat().st_size if target_path.exists() else 0
        append_api_fetch_history({
            "source_key": source_key,
            "label": label,
            "supplier": supplier,
            "event_type": "fetch",
            "status": "error",
            "message": error_message,
            "file_name": target_path.name,
            "file_size": int(file_size or 0),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": max(0, finished_at - started_at),
        })


def get_no_id_category_rules(settings=None):
    settings = settings or load_app_settings()
    raw = str((((settings or {}).get("no_id_search") or {}).get("category_rules_text", "")) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def load_onliner_market_cache():
    if not ONLINER_MARKET_CACHE_FILE.exists():
        return {}
    try:
        with open(ONLINER_MARKET_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_onliner_market_cache(cache):
    with open(ONLINER_MARKET_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def load_onliner_product_cache():
    if not ONLINER_PRODUCT_CACHE_FILE.exists():
        return {}
    try:
        with open(ONLINER_PRODUCT_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_onliner_product_cache(cache):
    with open(ONLINER_PRODUCT_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ============================================================
# ONLINER PRODUCTS DATABASE  (SQLite — единый источник истины)
# Файл: onliner_products.db (рядом с app.py)
#
# onliner_catalog  → onliner_id, name, url, source, updated_at
# name_index       → name_key (нормализованный), onliner_id, raw_name
#
# Пополняется автоматически при каждой загрузке прайса.
# Используется для автоподбора ID без Onliner API.
# ============================================================

def _db_connect():
    """Открывает соединение с SQLite БД с WAL-режимом для безопасного многопоточного доступа."""
    conn = sqlite3.connect(str(ONLINER_DB_FILE), check_same_thread=False, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db_connection():
    """sqlite3 Connection as context manager does not close the handle, so close explicitly."""
    conn = _db_connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_onliner_db():
    """Создаёт таблицы БД если они ещё не существуют. Вызывается один раз при старте."""
    try:
        with _db_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS onliner_catalog (
                    onliner_id  TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    url         TEXT DEFAULT '',
                    source      TEXT DEFAULT '',
                    updated_at  INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS name_index (
                    name_key    TEXT PRIMARY KEY,
                    onliner_id  TEXT NOT NULL,
                    raw_name    TEXT NOT NULL,
                    source      TEXT DEFAULT '',
                    updated_at  INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_ni_oid
                    ON name_index(onliner_id);
                CREATE INDEX IF NOT EXISTS idx_ni_rawname
                    ON name_index(raw_name);
            """)
        print(f"[db] SQLite БД инициализирована: {ONLINER_DB_FILE}", flush=True)
    except Exception as e:
        print(f"[db] Ошибка инициализации БД: {e}", flush=True)


def db_populate_from_df(df, source_label, skip_suppliers=None):
    """Пополняет БД из DataFrame (колонки: Название, OnlinerID, Ссылка, Поставщик).
    Вызывать после каждой загрузки прайса IVEN / BN / Tradex.
    skip_suppliers — список поставщиков-целей, которые не используются как источник (N-Tech, TGPC).
    Возвращает (добавлено_продуктов, добавлено_имён).
    """
    if df is None or df.empty:
        return 0, 0
    skip_upper = {str(s).upper() for s in (skip_suppliers or [])}
    supplier_col = "Поставщик" if "Поставщик" in df.columns else None
    now = int(time.time())

    products = {}   # onliner_id → (name, url)
    names    = {}   # name_key  → (onliner_id, raw_name)

    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        if supplier_col:
            sup = str(row.get(supplier_col, "")).strip().upper()
            if sup in skip_upper:
                continue
        url = str(row.get("Ссылка", "")).strip()
        name_key = _normalize_name_key(name)
        if oid not in products:
            products[oid] = (name, url)
        if name_key and name_key not in names:
            names[name_key] = (oid, name)

    if not products:
        return 0, 0

    try:
        with _DB_WRITE_LOCK:
            with _db_connection() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO onliner_catalog"
                    "(onliner_id, name, url, source, updated_at) VALUES(?,?,?,?,?)",
                    [(oid, nm, url, source_label, now) for oid, (nm, url) in products.items()],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO name_index"
                    "(name_key, onliner_id, raw_name, source, updated_at) VALUES(?,?,?,?,?)",
                    [(k, oid, raw, source_label, now) for k, (oid, raw) in names.items()],
                )
        print(f"[db] Пополнено из «{source_label}»: {len(products)} товаров, {len(names)} имён", flush=True)
        return len(products), len(names)
    except Exception as e:
        print(f"[db] Ошибка записи в БД: {e}", flush=True)
        return 0, 0


def db_upsert_product(onliner_id, name, url, source="manual"):
    """Добавляет/обновляет один товар в БД (например, после подтверждения вручную)."""
    oid = normalize_onliner_id(onliner_id)
    name = str(name or "").strip()
    if not oid or not name:
        return
    name_key = _normalize_name_key(name)
    now = int(time.time())
    try:
        with _DB_WRITE_LOCK:
            with _db_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO onliner_catalog"
                    "(onliner_id, name, url, source, updated_at) VALUES(?,?,?,?,?)",
                    (oid, name, url or "", source, now),
                )
                if name_key:
                    conn.execute(
                        "INSERT OR REPLACE INTO name_index"
                        "(name_key, onliner_id, raw_name, source, updated_at) VALUES(?,?,?,?,?)",
                        (name_key, oid, name, source, now),
                    )
    except Exception as e:
        print(f"[db] db_upsert_product error: {e}", flush=True)


def db_get_product_by_id(onliner_id):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return None
    try:
        with _db_connection() as conn:
            row = conn.execute(
                "SELECT onliner_id, name, url, source, updated_at "
                "FROM onliner_catalog WHERE onliner_id = ? LIMIT 1",
                (oid,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": normalize_onliner_id(row["onliner_id"]),
            "name": str(row["name"] or "").strip(),
            "url": str(row["url"] or "").strip(),
            "source": str(row["source"] or "").strip(),
            "updated_at": int(row["updated_at"] or 0),
        }
    except Exception as e:
        print(f"[db] db_get_product_by_id error: {e}", flush=True)
        return None


def db_find_exact_id_for_name(product_name):
    name = str(product_name or "").strip()
    if not name:
        return None
    name_key = _normalize_name_key(name)
    if not name_key:
        return None
    try:
        with _db_connection() as conn:
            row = conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "LEFT JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE ni.name_key = ? LIMIT 1",
                (name_key,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": normalize_onliner_id(row["onliner_id"]),
            "name": str(row["raw_name"] or "").strip(),
            "url": str(row["url"] or "").strip(),
            "score": 1.0,
            "source": "db_exact",
        }
    except Exception as e:
        print(f"[db] db_find_exact_id_for_name error: {e}", flush=True)
        return None


def db_find_id_for_name(product_name, threshold=0.75, allow_b2b=True):
    """Ищет лучший OnlinerID для товара по локальной БД.
    1. Точное совпадение по нормализованному ключу.
    2. Фильтрация по article-токенам (SQL LIKE) → calc_name_match по кандидатам.
    Возвращает dict {id, name, url, score, source} или None.
    """
    name = str(product_name or "").strip()
    if not name:
        return None
    name_key = _normalize_name_key(name)

    try:
        with _db_connection() as conn:
            # 1. Точное совпадение по нормализованному ключу
            if name_key:
                row = conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE ni.name_key = ? LIMIT 1",
                    (name_key,),
                ).fetchone()
                if row:
                    return {"id": row[0], "name": row[1], "url": row[2],
                            "score": 1.0, "source": "db_exact"}

            # 2. Build search candidates using RAW tokens (preserving hyphens for LIKE)
            raw_tokens = _raw_search_tokens(name)          # e.g. ["GK-240L", "45240"]
            model_tokens = list(_model_hint_tokens(name))  # normalized, as fallback

            candidates = {}  # onliner_id → (raw_name, url)

            def _add_candidates(rows):
                for r in rows:
                    if r[0] not in candidates:
                        candidates[r[0]] = (r[1], r[2])

            for tok in raw_tokens:
                if len(tok) < 4:
                    continue
                _add_candidates(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE ni.raw_name LIKE ? LIMIT 80",
                    (f"%{tok}%",),
                ).fetchall())
                # Also try without trailing alpha suffix for broader match (GK-240L -> GK-240)
                m_num = re.match(r'^([A-Za-z]{1,4}[-]?\d{3,5})', tok)
                if m_num and m_num.group(1) != tok:
                    _add_candidates(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE ni.raw_name LIKE ? LIMIT 40",
                        (f"%{m_num.group(1)}%",),
                    ).fetchall())

            # Fallback: model hint tokens if raw_tokens found nothing
            if len(candidates) < 3:
                for tok in model_tokens[:3]:
                    if len(tok) < 4:
                        continue
                    _add_candidates(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE ni.raw_name LIKE ? LIMIT 60",
                        (f"%{tok}%",),
                    ).fetchall())

            # 3. Фолбэк: поиск по бренду + опционально по нескольким числовым токенам
            if len(candidates) < 5:
                brand = _preferred_brand_token(name)
                if brand and len(brand) >= 3:
                    _add_candidates(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE ni.raw_name LIKE ? LIMIT 150",
                        (f"%{brand}%",),
                    ).fetchall())

            # 4. Фолбэк по числовому токену (например, 5700 из "RX 5700 XT") + бренд
            if len(candidates) < 5:
                nums = re.findall(r"\b(\d{3,5})\b", name)
                brand = _preferred_brand_token(name)
                for num in nums[:2]:
                    if brand:
                        rows = conn.execute(
                            "SELECT ni.onliner_id, ni.raw_name, oc.url "
                            "FROM name_index ni "
                            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                            "WHERE ni.raw_name LIKE ? AND ni.raw_name LIKE ? LIMIT 80",
                            (f"%{brand}%", f"%{num}%"),
                        ).fetchall()
                        _add_candidates(rows)

        if not candidates:
            return None

        best_score = 0.0
        best = None
        for oid, (cand_name, cand_url) in candidates.items():
            allowed, _reason = _strict_candidate_allowed(name, cand_name)
            if not allowed:
                continue
            cmp = calc_name_match(name, cand_name)
            sc = float(cmp.get("score", 0.0) or 0.0)
            if sc > best_score:
                best_score = sc
                best = {"id": oid, "name": cand_name, "url": cand_url}

        if best_score >= threshold and best:
            return {**best, "score": round(best_score, 3), "source": "db_fuzzy"}

        if allow_b2b:
            for cand in onliner_b2b_search_candidates(name, category_name=infer_category(name), limit=8):
                sc = float(cand.get("score", 0.0) or 0.0)
                if sc >= float(threshold):
                    return {
                        "id": normalize_onliner_id(cand.get("id", "")),
                        "name": str(cand.get("name", "") or "").strip(),
                        "url": str(cand.get("url", "") or "").strip(),
                        "score": round(sc, 3),
                        "source": "b2b_fuzzy",
                    }
        return None

    except Exception as e:
        print(f"[db] db_find_id_for_name error: {e}", flush=True)
        return None


def db_find_top_candidates(product_name, top_n=5, min_score=0.40, allow_b2b=True):
    """Return top N candidates from DB for manual selection.
    Filtered by same brand and category when possible.
    Used when auto-match score is below threshold."""
    name = str(product_name or "").strip()
    if not name:
        return []
    try:
        with _db_connection() as conn:
            brand = _preferred_brand_token(name)
            candidates = {}

            def _add(rows):
                for r in rows:
                    if r[0] not in candidates:
                        candidates[r[0]] = (r[1], r[2])

            # Search by brand (most targeted)
            if brand and len(brand) >= 3:
                _add(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE ni.raw_name LIKE ? LIMIT 200",
                    (f"%{brand}%",),
                ).fetchall())

            # Also try raw tokens
            for tok in _raw_search_tokens(name)[:3]:
                if len(tok) >= 4:
                    _add(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE ni.raw_name LIKE ? LIMIT 100",
                        (f"%{tok}%",),
                    ).fetchall())

        if not candidates:
            return []

        scored = []
        for oid, (cand_name, cand_url) in candidates.items():
            allowed, _reason = _strict_candidate_allowed(name, cand_name)
            if not allowed:
                continue
            cmp = calc_name_match(name, cand_name)
            sc = float(cmp.get("score", 0.0) or 0.0)
            if sc >= min_score:
                scored.append({"id": oid, "name": cand_name, "url": cand_url,
                               "score": round(sc, 3)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        top_scored = scored[:top_n]
        seen_ids = {normalize_onliner_id(x.get("id", "")) for x in top_scored}
        if allow_b2b and len(top_scored) < top_n:
            for cand in onliner_b2b_search_candidates(name, category_name=infer_category(name), limit=top_n * 2):
                cid = normalize_onliner_id(cand.get("id", ""))
                sc = float(cand.get("score", 0.0) or 0.0)
                if not cid or cid in seen_ids or sc < min_score:
                    continue
                top_scored.append({
                    "id": cid,
                    "name": str(cand.get("name", "") or "").strip(),
                    "url": str(cand.get("url", "") or "").strip(),
                    "score": round(sc, 3),
                    "source": "b2b_fuzzy",
                })
                seen_ids.add(cid)
                if len(top_scored) >= top_n:
                    break
        top_scored.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
        return top_scored[:top_n]

    except Exception as e:
        print(f"[db] db_find_top_candidates error: {e}", flush=True)
        return []


def db_search_tgpc_pc_candidates(local_name, limit=12):
    """Кандидаты для TGPC ПЭВМ только из локальной SQLite (без Onliner catalog API и B2B)."""
    name = str(local_name or "").strip()
    if not name or not _is_tgpc_pc_name(name):
        return []
    limit = max(5, min(int(limit or 12), 80))

    pool = {}
    exact = db_find_exact_id_for_name(name)
    if isinstance(exact, dict):
        eid = normalize_onliner_id(exact.get("id", ""))
        if eid:
            pool[eid] = (
                str(exact.get("name", "") or "").strip(),
                str(exact.get("url", "") or "").strip(),
            )

    try:
        with _db_connection() as conn:
            for q in _tgpc_pc_code_queries(name):
                qstrip = str(q or "").strip()
                if len(qstrip) < 2:
                    continue
                rows = conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE ni.raw_name LIKE ? LIMIT 180",
                    (f"%{qstrip}%",),
                ).fetchall()
                for r in rows:
                    oid = normalize_onliner_id(r["onliner_id"] if isinstance(r, sqlite3.Row) else r[0])
                    raw = str((r["raw_name"] if isinstance(r, sqlite3.Row) else r[1]) or "").strip()
                    url = str((r["url"] if isinstance(r, sqlite3.Row) else r[2]) or "").strip()
                    if oid and raw:
                        pool[oid] = (raw, url)

            code = _extract_tgpc_pc_code(name)
            if code and len(code) >= 4:
                rows = conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE ni.raw_name LIKE ? LIMIT 220",
                    (f"%{code}%",),
                ).fetchall()
                for r in rows:
                    oid = normalize_onliner_id(r["onliner_id"] if isinstance(r, sqlite3.Row) else r[0])
                    raw = str((r["raw_name"] if isinstance(r, sqlite3.Row) else r[1]) or "").strip()
                    url = str((r["url"] if isinstance(r, sqlite3.Row) else r[2]) or "").strip()
                    if oid and raw:
                        pool[oid] = (raw, url)
    except Exception as e:
        print(f"[db] db_search_tgpc_pc_candidates error: {e}", flush=True)
        return []

    local_tgpc_code = _extract_tgpc_pc_code(name)
    items = []
    seen = set()
    for oid, (cname, curl) in pool.items():
        if not oid or not cname or oid in seen:
            continue
        clower = cname.lower()
        curl_l = str(curl or "").strip().lower()
        candidate_is_tgpc = "tgpc" in clower
        candidate_is_pc_url = bool(curl_l and any(h in curl_l for h in ("/desktop/", "/computer/", "/tgpc/")))
        if not candidate_is_tgpc and not candidate_is_pc_url:
            continue

        cmp = calc_name_match(name, cname)
        score = float(cmp.get("score", 0.0) or 0.0)
        if local_tgpc_code:
            cand_code = _extract_tgpc_pc_code(cname)
            if cand_code and cand_code != local_tgpc_code:
                score = min(score, 0.12)
            elif not cand_code and local_tgpc_code not in (cname + str(curl or "")):
                score = min(score, 0.68)
        if not candidate_is_tgpc:
            score *= 0.70
        if curl_l and not any(h in curl_l for h in ("/desktop/", "/computer/", "/tgpc/")):
            score *= 0.80

        if score < 0.34:
            continue
        seen.add(oid)
        items.append({
            "id": oid,
            "name": cname,
            "url": str(curl or "").strip(),
            "score": round(score, 3),
            "source": "db_tgpc_pc",
            "reason": str(cmp.get("reason", "") or ""),
        })

    items.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
    return items[:limit]


def db_stats():
    """Статистика БД: количество товаров, имён, по источникам."""
    try:
        with _db_connection() as conn:
            total_products = conn.execute("SELECT COUNT(*) FROM onliner_catalog").fetchone()[0]
            total_names    = conn.execute("SELECT COUNT(*) FROM name_index").fetchone()[0]
            by_source = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT source, COUNT(*) FROM onliner_catalog GROUP BY source ORDER BY COUNT(*) DESC"
                ).fetchall()
            }
        return {"total_products": total_products, "total_names": total_names, "by_source": by_source}
    except Exception:
        return {"total_products": 0, "total_names": 0, "by_source": {}}


# ── Onliner catalog bulk import ───────────────────────────────────────────
_catalog_import_status = {
    "running": False, "total": 0, "done": 0, "inserted": 0,
    "skipped": 0, "message": "", "percent": 0, "finished_at": None,
}
_CATALOG_IMPORT_LOCK = threading.RLock()
ONLINER_DB_GSHEET_CACHE_DIR = Path(__file__).parent / "uploads" / "_onliner_db_cache"
ONLINER_DB_GSHEET_CACHE_TTL_SEC = 12 * 60 * 60


def _catalog_import_worker(filepath: str, file_ext: str, cleanup_file: bool = True):
    """Background worker: parse CSV/XLSX and bulk-insert into SQLite."""
    global _catalog_import_status
    with _CATALOG_IMPORT_LOCK:
        _catalog_import_status.update({
            "running": True, "total": 0, "done": 0, "inserted": 0,
            "skipped": 0, "message": "Читаю файл...", "percent": 0, "finished_at": None,
        })

    try:
        # ── Read file ────────────────────────────────────────────────────
        if file_ext in (".xlsx", ".xls"):
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ([str(c.value or "") for c in row] for row in ws.iter_rows())
        else:
            import csv
            f_obj = open(filepath, encoding="utf-8-sig", newline="")
            rows_iter = ([str(c) for c in row] for row in csv.reader(f_obj))

        # Skip header row (first row)
        rows = list(rows_iter)
        if rows:
            rows = rows[1:]  # skip header

        total = len(rows)
        with _CATALOG_IMPORT_LOCK:
            _catalog_import_status["total"] = total
            _catalog_import_status["message"] = f"Импортирую {total:,} строк..."

        # ── Bulk insert in batches ───────────────────────────────────────
        BATCH = 2000
        inserted = 0
        skipped = 0
        now_ts = int(time.time())

        for batch_start in range(0, total, BATCH):
            batch = rows[batch_start: batch_start + BATCH]
            prod_rows = []   # (onliner_id, name, url, source, ts)
            name_rows = []   # (name_key, onliner_id, raw_name)

            for row in batch:
                # Pad row to at least 8 columns
                while len(row) < 8:
                    row.append("")
                category  = row[0].strip()
                model_short = row[2].strip()   # C: короткая модель
                oid_raw   = row[4].strip()     # E: onliner_id
                full_name = row[7].strip()     # H: полное название по Onliner

                oid = normalize_onliner_id(oid_raw)
                if not oid:
                    skipped += 1
                    continue

                # Primary name = full Onliner name (H), fallback = category + short model
                name = full_name if full_name else (f"{category} {model_short}".strip())
                if not name:
                    skipped += 1
                    continue

                url = ""  # URL not needed for matching
                prod_rows.append((oid, name, url, "onliner_catalog", now_ts))

                # Index: full name
                nk = _normalize_name_key(name)
                if nk:
                    name_rows.append((nk, oid, name))

                # Index: short model (alternate name variant)
                if model_short and model_short.lower() not in name.lower():
                    alt_name = f"{category} {model_short}".strip() if category else model_short
                    nk2 = _normalize_name_key(alt_name)
                    if nk2 and nk2 != nk:
                        name_rows.append((nk2, oid, alt_name))

            try:
                with _DB_WRITE_LOCK:
                    with _db_connection() as conn:
                        conn.executemany(
                            "INSERT OR REPLACE INTO onliner_catalog "
                            "(onliner_id, name, url, source, updated_at) VALUES (?,?,?,?,?)",
                            prod_rows,
                        )
                        conn.executemany(
                            "INSERT OR REPLACE INTO name_index "
                            "(name_key, onliner_id, raw_name) VALUES (?,?,?)",
                            name_rows,
                        )
                        conn.commit()
                inserted += len(prod_rows)
            except Exception as e:
                print(f"[db_import] batch error: {e}", flush=True)

            done = batch_start + len(batch)
            pct = round(done / total * 100) if total else 100
            with _CATALOG_IMPORT_LOCK:
                _catalog_import_status.update({
                    "done": done, "inserted": inserted, "skipped": skipped,
                    "percent": pct,
                    "message": f"Импортировано {inserted:,} из {total:,} ({pct}%)",
                })

        with _CATALOG_IMPORT_LOCK:
            _catalog_import_status.update({
                "running": False, "done": total, "inserted": inserted,
                "skipped": skipped, "percent": 100,
                "message": f"Готово! Добавлено {inserted:,} товаров, пропущено {skipped:,}.",
                "finished_at": int(time.time()),
            })
        print(f"[db_import] Done. inserted={inserted}, skipped={skipped}", flush=True)

    except Exception as e:
        with _CATALOG_IMPORT_LOCK:
            _catalog_import_status.update({
                "running": False, "message": f"Ошибка: {e}", "finished_at": int(time.time()),
            })
        print(f"[db_import] Error: {e}", flush=True)
    finally:
        if cleanup_file:
            try:
                import os
                os.remove(filepath)
            except Exception:
                pass


def load_manual_id_bindings():
    from price_mixer.db import get_db
    try:
        return get_db().get_manual_bindings()
    except Exception:
        pass
    return {}


def save_manual_id_bindings(bindings):
    from price_mixer.db import get_db
    try:
        for name_key, info in bindings.items():
            get_db().set_manual_binding(name_key, info.get("id", ""), info.get("url", ""))
    except Exception:
        pass


def load_review_queue():
    if not REVIEW_QUEUE_FILE.exists():
        return {}
    try:
        with open(REVIEW_QUEUE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_review_queue(queue):
    with open(REVIEW_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def load_id_change_journal():
    if not ID_CHANGE_JOURNAL_FILE.exists():
        return []
    try:
        with open(ID_CHANGE_JOURNAL_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data[-5000:]
    except Exception:
        pass
    return []


def save_id_change_journal(rows):
    data = rows if isinstance(rows, list) else []
    with open(ID_CHANGE_JOURNAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data[-5000:], f, ensure_ascii=False, indent=2)


def append_id_change_journal(entry):
    from price_mixer.db import get_db
    try:
        get_db().append_id_journal(
            entry.get("ts", int(time.time())),
            entry.get("action", ""),
            entry.get("source", ""),
            entry.get("changes", []),
        )
    except Exception:
        pass


def is_manually_confirmed_id(name, onliner_id):
    oid = normalize_onliner_id(onliner_id)
    name_key = _normalize_name_key(name)
    if not oid or not name_key:
        return False
    bindings = load_manual_id_bindings()
    rec = bindings.get(name_key)
    if not isinstance(rec, dict):
        return False
    return normalize_onliner_id(rec.get("id", "")) == oid


def _safe_float(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def _extract_position_prices(payload):
    prices = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "position_price" and isinstance(v, dict):
                amount = _safe_float(v.get("amount"))
                if amount is not None and amount > 0:
                    prices.append(amount)
            else:
                prices.extend(_extract_position_prices(v))
    elif isinstance(payload, list):
        for x in payload:
            prices.extend(_extract_position_prices(x))
    return prices


def _fetch_onliner_product_payload(onliner_id):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return None, "пустой onliner id"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    product = None
    direct_error = ""
    search_error = ""
    try:
        rp = onliner_api_get(
            f"https://catalog.api.onliner.by/products/{oid}",
            timeout=12,
            headers=headers,
        )
        if rp.ok:
            payload = rp.json() or {}
            payload_id = normalize_onliner_id(payload.get("id", ""))
            if payload_id == oid:
                product = payload
            else:
                direct_error = f"products/{oid}: mismatched id {payload_id or 'empty'}"
        else:
            direct_error = f"products/{oid}: http {rp.status_code}"
    except Exception:
        direct_error = f"products/{oid}: timeout/connection"

    if not product:
        search_url = f"https://catalog.api.onliner.by/search/products?query={oid}"
        try:
            r = onliner_api_get(search_url, timeout=12, headers=headers)
            if r.ok:
                products = (r.json() or {}).get("products", [])
                for p in products:
                    if str(p.get("id", "")).strip() == oid:
                        product = p
                        break
                if product is None:
                    search_error = "search: товар не найден"
            else:
                search_error = f"search: http {r.status_code}"
        except Exception:
            search_error = "search: timeout/connection"

    if product:
        return product, ""
    reason = "; ".join([x for x in [direct_error, search_error] if x]) or "товар не найден"
    return None, reason


def _extract_offer_rows(payload):
    payload = payload or {}
    rows = []

    shops_map = payload.get("shops") or {}
    if not isinstance(shops_map, dict):
        shops_map = {}

    def _shop_from_map(shop_id):
        sid = str(shop_id or "").strip()
        if not sid:
            return {}
        if sid in shops_map and isinstance(shops_map[sid], dict):
            return shops_map[sid]
        if sid.isdigit() and int(sid) in shops_map and isinstance(shops_map[int(sid)], dict):
            return shops_map[int(sid)]
        return {}

    def _extract_price(node):
        if isinstance(node.get("position_price"), dict):
            price = _safe_float((((node.get("position_price") or {}).get("converted") or {}).get("BYN") or {}).get("amount"))
            if price is None:
                price = _safe_float((node.get("position_price") or {}).get("amount"))
            if price is not None:
                return price
        if isinstance(node.get("price"), dict):
            price = _safe_float((((node.get("price") or {}).get("converted") or {}).get("BYN") or {}).get("amount"))
            if price is None:
                price = _safe_float((node.get("price") or {}).get("amount"))
            if price is not None:
                return price
        if "price" in node:
            return _safe_float(node.get("price"))
        return None

    def _seller_info(node):
        seller_name = ""
        seller_id = str(node.get("seller_id") or node.get("shop_id") or node.get("vendor_id") or "").strip()
        seller_url = str(node.get("shop_url") or node.get("seller_url") or "").strip()

        for key in ("shop", "seller", "vendor", "merchant", "store"):
            val = node.get(key)
            if isinstance(val, dict):
                seller_name = str(val.get("title") or val.get("name") or val.get("full_name") or seller_name).strip()
                seller_id = str(val.get("id") or val.get("key") or seller_id).strip()
                seller_url = str(val.get("html_url") or val.get("url") or seller_url).strip()
                if seller_name or seller_id or seller_url:
                    break

        mapped = _shop_from_map(seller_id)
        if mapped:
            if not seller_name:
                seller_name = str(mapped.get("title") or mapped.get("name") or "").strip()
            if not seller_url:
                seller_url = str(mapped.get("html_url") or mapped.get("url") or "").strip()
            if not seller_id:
                seller_id = str(mapped.get("id") or "").strip()

        if not seller_name:
            seller_name = str(node.get("seller_name") or node.get("shop_name") or node.get("vendor_name") or "").strip()

        return seller_name, seller_id, seller_url

    positions = payload.get("positions") or {}
    if isinstance(positions, dict):
        iter_lists = [v for v in positions.values() if isinstance(v, list)]
    elif isinstance(positions, list):
        iter_lists = [positions]
    else:
        iter_lists = []

    for items in iter_lists:
        for node in items:
            if not isinstance(node, dict):
                continue
            price = _extract_price(node)
            if price is None:
                continue
            seller_name, seller_id, seller_url = _seller_info(node)
            rows.append({
                "seller_name": seller_name or "—",
                "seller_id": seller_id,
                "seller_url": seller_url,
                "price": round(float(price), 2),
                "url": str(node.get("product_url") or node.get("html_url") or node.get("url") or seller_url or "").strip(),
                "warranty": str(node.get("warranty") or "").strip(),
                "stock": str((node.get("stock_status") or {}).get("text") or "").strip(),
                "updated_at": str(node.get("date_update") or "").strip(),
            })

    if not rows:
        def _walk(node):
            if isinstance(node, dict):
                price = _extract_price(node)
                if price is not None:
                    seller_name, seller_id, seller_url = _seller_info(node)
                    rows.append({
                        "seller_name": seller_name or "—",
                        "seller_id": seller_id,
                        "seller_url": seller_url,
                        "price": round(float(price), 2),
                        "url": str(node.get("product_url") or node.get("html_url") or node.get("url") or seller_url or "").strip(),
                        "warranty": str(node.get("warranty") or "").strip(),
                        "stock": str((node.get("stock_status") or {}).get("text") or "").strip(),
                        "updated_at": str(node.get("date_update") or "").strip(),
                    })
                for v in node.values():
                    _walk(v)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)
        _walk(payload)

    dedup = []
    seen = set()
    for row in rows:
        key = (row.get("seller_id", ""), row.get("seller_name", ""), row.get("price", ""), row.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(row)
    return dedup


def _fetch_onliner_market_stats_catalog_api(onliner_id):
    """Публичный catalog.api.onliner.by (fallback, если B2B выключен)."""
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0, "_error": True, "_error_reason": "пустой onliner id"}
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    product, product_error = _fetch_onliner_product_payload(oid)
    if not product:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": product_error or "товар не найден",
        }

    prices_obj = product.get("prices") or {}
    min_price = _safe_float((((prices_obj.get("price_min") or {}).get("converted") or {}).get("BYN") or {}).get("amount"))
    if min_price is None:
        min_price = _safe_float((prices_obj.get("price_min") or {}).get("amount"))
    offers_count = int((prices_obj.get("offers") or {}).get("count") or 0)
    avg_price = None
    max_price = None
    min_competitors = 0
    avg_competitors = 0

    # Step 2: compute average from all current positions.
    positions_url = str(prices_obj.get("url", "")).strip()
    if positions_url:
        try:
            rp = onliner_api_get(positions_url, timeout=12, headers=headers)
            if rp.ok:
                position_prices = _extract_position_prices(rp.json())
                if position_prices:
                    avg_price = round(float(sum(position_prices)) / len(position_prices), 2)
                    max_price = round(float(max(position_prices)), 2)
                    min_price = round(float(min(position_prices)), 2)
                    min_competitors = sum(1 for p in position_prices if p <= min_price * 1.02)
                    avg_competitors = sum(1 for p in position_prices if abs(p - avg_price) <= max(1.0, avg_price * 0.05))
                    if not offers_count:
                        offers_count = len(position_prices)
                else:
                    positions_error = "positions: пустой список цен"
            else:
                positions_error = f"positions: http {rp.status_code}"
        except Exception:
            positions_error = "positions: timeout/connection"

    # Показываем рыночные цены уже при 1+ конкуренте.
    # Если API не отдал offers.count, но min цена есть — считаем как минимум 1 предложение.
    if offers_count <= 0 and min_price is not None:
        offers_count = 1

    if offers_count < 1:
        min_price = None
        avg_price = None
        max_price = None
        min_competitors = 0
        avg_competitors = 0
    elif min_price is not None:
        if avg_price is None:
            avg_price = min_price
        if max_price is None:
            max_price = min_price

    return {
        "min": None if min_price is None else round(float(min_price), 2),
        "avg": None if avg_price is None else round(float(avg_price), 2),
        "max": None if max_price is None else round(float(max_price), 2),
        "offers": offers_count,
        "min_competitors": int(min_competitors),
        "avg_competitors": int(avg_competitors),
        "_error": False,
        "_error_reason": "" if offers_count >= 1 else str(locals().get("positions_error", "") or ""),
    }


def fetch_onliner_market_stats(onliner_id, product_name="", category_name=""):
    """Рыночные цены: сначала публичный catalog API (быстрее при массовом обновлении); при пустых данных — B2B price.api."""
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0, "_error": True, "_error_reason": "пустой onliner id"}
    cat_stats = _fetch_onliner_market_stats_catalog_api(oid)
    if market_stats_has_values(cat_stats):
        return cat_stats
    cfg = get_onliner_b2b_settings()
    if (
        cfg.get("enabled")
        and str(cfg.get("client_id", "") or "").strip()
        and str(cfg.get("client_secret", "") or "").strip()
    ):
        b2b_stats = _fetch_onliner_market_stats_b2b(oid, product_name=product_name, category_name=category_name)
        if market_stats_has_values(b2b_stats):
            return b2b_stats
    return cat_stats


def get_onliner_market_stats_cached(onliner_id, cache=None):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "offers": 0}
    if cache is None:
        cache = load_onliner_market_cache()
    now = int(time.time())
    with ONLINER_PRODUCT_CACHE_LOCK:
        cached = cache.get(oid)
    if isinstance(cached, dict) and (now - int(cached.get("updated_at", 0)) <= ONLINER_MARKET_CACHE_TTL):
        return {
            "min": _safe_float(cached.get("min")),
            "avg": _safe_float(cached.get("avg")),
            "max": _safe_float(cached.get("max")),
            "offers": int(cached.get("offers", 0) or 0),
            "min_competitors": int(cached.get("min_competitors", 0) or 0),
            "avg_competitors": int(cached.get("avg_competitors", 0) or 0),
        }
    hint_name = ""
    hint_cat = ""
    dbp = db_get_product_by_id(oid)
    if isinstance(dbp, dict):
        hint_name = str(dbp.get("name", "") or "").strip()
    if hint_name:
        hint_cat = infer_category(hint_name)
    stats = fetch_onliner_market_stats(oid, product_name=hint_name, category_name=hint_cat)
    cache[oid] = {"updated_at": now, **stats}
    return stats


def get_onliner_market_stats_from_cache_only(onliner_id, cache=None, allow_stale=True):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
    if cache is None:
        cache = load_onliner_market_cache()
    cached = cache.get(oid)
    if not isinstance(cached, dict):
        return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
    if not allow_stale:
        now = int(time.time())
        if now - int(cached.get("updated_at", 0)) > ONLINER_MARKET_CACHE_TTL:
            return {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0}
    return {
        "min": _safe_float(cached.get("min")),
        "avg": _safe_float(cached.get("avg")),
        "max": _safe_float(cached.get("max")),
        "offers": int(cached.get("offers", 0) or 0),
        "min_competitors": int(cached.get("min_competitors", 0) or 0),
        "avg_competitors": int(cached.get("avg_competitors", 0) or 0),
    }


def market_stats_has_values(stats):
    if not isinstance(stats, dict):
        return False
    if _safe_float(stats.get("min")) is not None:
        return True
    if _safe_float(stats.get("avg")) is not None:
        return True
    if _safe_float(stats.get("max")) is not None:
        return True
    if int(stats.get("offers", 0) or 0) > 0:
        return True
    return False


def get_onliner_market_stats_bulk(onliner_ids, max_workers=22, id_hints=None):
    ids = [normalize_onliner_id(x) for x in onliner_ids]
    ids = [x for x in ids if x]
    if not ids:
        return {}
    cache = load_onliner_market_cache()
    result = {}
    pending = []
    now = int(time.time())
    for oid in ids:
        cached = cache.get(oid)
        if isinstance(cached, dict) and (now - int(cached.get("updated_at", 0)) <= ONLINER_MARKET_CACHE_TTL):
            result[oid] = {
                "min": _safe_float(cached.get("min")),
                "avg": _safe_float(cached.get("avg")),
                "max": _safe_float(cached.get("max")),
                "offers": int(cached.get("offers", 0) or 0),
                "min_competitors": int(cached.get("min_competitors", 0) or 0),
                "avg_competitors": int(cached.get("avg_competitors", 0) or 0),
            }
        else:
            pending.append(oid)

    def _fetch_one_market(oid):
        hint = (id_hints or {}).get(oid) if id_hints else None
        if isinstance(hint, dict):
            return fetch_onliner_market_stats(
                oid,
                product_name=str(hint.get("name", "") or ""),
                category_name=str(hint.get("category", "") or ""),
            )
        return fetch_onliner_market_stats(oid)

    if pending:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_to_oid = {ex.submit(_fetch_one_market, oid): oid for oid in pending}
            for fut in as_completed(fut_to_oid):
                oid = fut_to_oid[fut]
                try:
                    stats = fut.result()
                except Exception:
                    stats = {
                        "min": None, "avg": None, "max": None, "offers": 0,
                        "min_competitors": 0, "avg_competitors": 0, "_error": True,
                    }
                result[oid] = stats
                cache[oid] = {"updated_at": now, **stats}
        save_onliner_market_cache(cache)
    return result


def fetch_onliner_product_info(onliner_id, cache=None, force_refresh=False,
                               use_cache_on_error=True, product_name_hint=None):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"name": "", "url": "", "source": "empty"}
    if cache is None:
        cache = load_onliner_product_cache()
    now = int(time.time())
    cached = cache.get(oid)
    if (not force_refresh) and isinstance(cached, dict) and now - int(cached.get("updated_at", 0)) <= ONLINER_PRODUCT_CACHE_TTL:
        return {
            "name": str(cached.get("name", "")).strip(),
            "url": str(cached.get("url", "")).strip(),
            "source": "cache",
        }

    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    def _cache_and_return(name, url, source):
        with ONLINER_PRODUCT_CACHE_LOCK:
            cache[oid] = {"updated_at": now, "name": name, "url": url}
        return {"name": name, "url": url, "source": source}

    db_product = db_get_product_by_id(oid)
    if isinstance(db_product, dict) and str(db_product.get("name", "")).strip():
        return _cache_and_return(
            str(db_product.get("name", "")).strip(),
            str(db_product.get("url", "")).strip(),
            "db",
        )

    def _search_by_id_fallback():
        """Search by numeric ID — works when /products/{oid} returns 404."""
        try:
            rs = onliner_api_get(
                f"https://catalog.api.onliner.by/search/products?query={oid}",
                timeout=12,
                headers=headers,
            )
            if not rs.ok:
                return None
            products = (rs.json() or {}).get("products") or []
            # Exact numeric ID match
            for p in products:
                if str(p.get("id", "")).strip() == oid:
                    return {
                        "name": str(p.get("full_name") or p.get("name") or "").strip(),
                        "url": str(p.get("html_url") or "").strip(),
                    }
            return None
        except Exception:
            return None

    def _search_by_name_fallback(name_hint):
        """Search by product name — fallback when ID search fails."""
        if not name_hint:
            return None
        try:
            from urllib.parse import quote as _quote
            rs = onliner_api_get(
                f"https://catalog.api.onliner.by/search/products?query={_quote(name_hint[:80])}",
                timeout=12,
                headers=headers,
            )
            if not rs.ok:
                return None
            products = (rs.json() or {}).get("products") or []
            # Exact numeric ID match in name search results
            for p in products:
                if str(p.get("id", "")).strip() == oid:
                    return {
                        "name": str(p.get("full_name") or p.get("name") or "").strip(),
                        "url": str(p.get("html_url") or "").strip(),
                    }
            return None
        except Exception:
            return None

    try:
        # Primary path: direct product endpoint.
        # Onliner /products/{id} accepts URL key-slugs (e.g. "95834") OR numeric IDs.
        # The JSON response has "id" (internal numeric) and "key" (URL slug).
        # We accept the result if EITHER field matches our queried oid.
        r = onliner_api_get(
            f"https://catalog.api.onliner.by/products/{oid}",
            timeout=8,
            headers=headers,
        )
        if r.ok:
            d = r.json() or {}
            payload_numeric_id = normalize_onliner_id(d.get("id", ""))
            payload_key = str(d.get("key", "")).strip()
            id_match = (payload_numeric_id == oid) or (payload_key == oid)
            name = str(d.get("full_name") or d.get("name") or "").strip()
            url = str(d.get("html_url") or "").strip()
            if id_match and name:
                return _cache_and_return(name, url, "api")
            # If direct endpoint returned OK but ID does not match,
            # it means the oid is a numeric ID that the endpoint treated as a key and
            # returned a different product — fall through to search.

        # Fallback: search by numeric ID
        fb = _search_by_id_fallback()
        if fb and fb.get("name"):
            return _cache_and_return(fb["name"], fb.get("url", ""), "search_by_id")

        # Second fallback: search by product name (helps when ID search times out)
        fb2 = _search_by_name_fallback(product_name_hint)
        if fb2 and fb2.get("name"):
            return _cache_and_return(fb2["name"], fb2.get("url", ""), "search_by_name")

        if use_cache_on_error and isinstance(cached, dict):
            return {
                "name": str(cached.get("name", "")).strip(),
                "url": str(cached.get("url", "")).strip(),
                "source": "cache_fallback_http_error",
            }
        return {"name": "", "url": "", "source": "http_error"}

    except Exception:
        fb = _search_by_id_fallback()
        if fb and fb.get("name"):
            return _cache_and_return(fb["name"], fb.get("url", ""), "search_by_id_after_error")
        fb2 = _search_by_name_fallback(product_name_hint)
        if fb2 and fb2.get("name"):
            return _cache_and_return(fb2["name"], fb2.get("url", ""), "search_by_name_after_error")
        if use_cache_on_error and isinstance(cached, dict):
            return {
                "name": str(cached.get("name", "")).strip(),
                "url": str(cached.get("url", "")).strip(),
                "source": "cache_fallback_error",
            }
        return {"name": "", "url": "", "source": "error"}


def search_onliner_product_by_name(local_name):
    """
    Fallback-поиск товара в Onliner API по названию локального товара.
    Возвращает лучший кандидат по score.
    """
    name = str(local_name or "").strip()
    if not name:
        return {"id": "", "name": "", "url": "", "score": 0.0, "source": "empty_query"}
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    candidates = []
    art = str(extract_article(name) or "").strip()
    if art:
        candidates.append(art)
    tokens = _name_tokens(name)
    if tokens:
        candidates.append(" ".join(tokens[:6]))
    candidates.append(name[:120])

    seen = set()
    queries = []
    for q in candidates:
        q = str(q).strip()
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        queries.append(q)

    best = {"id": "", "name": "", "url": "", "score": 0.0, "source": "not_found"}
    for q in queries[:3]:
        try:
            rs = onliner_api_get(
                f"https://catalog.api.onliner.by/search/products?query={quote(q)}",
                timeout=12,
                headers=headers,
            )
            if not rs.ok:
                continue
            data = rs.json() or {}
            products = data.get("products") or []
            for p in products[:15]:
                pid = normalize_onliner_id(p.get("id", ""))
                pname = str(p.get("full_name") or p.get("name") or "").strip()
                purl = str(p.get("html_url") or "").strip()
                if not pid or not pname:
                    continue
                cmp = calc_name_match(name, pname)
                score = float(cmp.get("score", 0.0) or 0.0)
                if cmp.get("match"):
                    score = max(score, 0.75)
                if score > float(best.get("score", 0.0)):
                    best = {"id": pid, "name": pname, "url": purl, "score": score, "source": "search_name"}
        except Exception:
            continue
        if float(best.get("score", 0.0)) >= 0.78:
            break
    return best


def search_onliner_product_by_name_deep(local_name, category_name=""):
    """
    Более агрессивный поиск кандидата:
    - пробует обычный быстрый поиск,
    - затем расширенный поиск по нескольким запросам,
    - затем перепроверяет лучшие кандидаты по карточке товара.
    """
    name = str(local_name or "").strip()
    if not name:
        return {"id": "", "name": "", "url": "", "score": 0.0, "source": "empty_query"}

    best = search_onliner_product_by_name(name)
    best_score = float(best.get("score", 0.0) or 0.0)

    candidates = search_onliner_candidates(
        name,
        category_name=category_name,
        query="",
        limit=10,
        max_queries=3,
        timeout_sec=5,
    )
    if not candidates:
        return best

    cache = load_onliner_product_cache()
    touched = False
    for cand in candidates[:4]:
        cid = normalize_onliner_id(cand.get("id", ""))
        if not cid:
            continue
        info = fetch_onliner_product_info(cid, cache=cache, force_refresh=False, use_cache_on_error=True)
        if info.get("source") == "api":
            touched = True
        pname = str(info.get("name", "") or cand.get("name", "")).strip()
        purl = str(info.get("url", "") or cand.get("url", "")).strip()
        if not pname:
            continue
        cmp = calc_name_match(name, pname)
        score = float(cmp.get("score", 0.0) or 0.0)
        if cmp.get("match"):
            score = max(score, 0.80)
        # бонус за совпадение артикульных токенов
        try:
            art_local = _article_like_tokens(name)
            art_remote = _article_like_tokens(pname)
            if art_local and art_remote and art_local.intersection(art_remote):
                score = max(score, 0.86)
        except Exception:
            pass
        if score > best_score:
            best_score = score
            best = {
                "id": cid,
                "name": pname,
                "url": purl,
                "score": score,
                "source": "search_name_deep",
            }
        if best_score >= 0.86:
            break

    if touched:
        try:
            save_onliner_product_cache(cache)
        except Exception:
            pass
    return best


def _category_path_hints(category_name):
    c = str(category_name or "").strip().lower()
    if c == "процессор":
        return ["/cpu/"]
    if c == "видеокарта":
        return ["/videocard/"]
    if c == "оперативная память":
        return ["/dram/"]
    if c == "материнская плата":
        return ["/motherboard/"]
    if c == "ssd":
        return ["/ssd/"]
    if c == "жесткий диск":
        return ["/hdd/"]
    if c == "блок питания":
        return ["/powersupply/", "/psu/"]
    if c == "корпус":
        return ["/case/"]
    if c == "кулер":
        return ["/cooler/"]
    if c == "монитор":
        return ["/display/"]
    if c == "системный блок":
        return ["/desktop/", "/computer/", "/tgpc/"]
    return []


def _preferred_brand_token(text):
    """Return the first significant word that is NOT a category label and has no digits."""
    raw = str(text or "")
    skip = {
        "hdd", "ssd", "sata", "sataii", "sataiii", "usb", "typea", "typec", "ddr3", "ddr4", "ddr5",
        "pc", "pcie", "nvme", "bulk", "tb", "gb", "mb", "mhz", "rpm", "mm", "cl", "pc25600",
        # Form-factor / descriptor words often following category names
        "atx", "matx", "eatx", "itx", "microatx", "miniitx", "midiтower", "minitower",
        # Russian prepositions/fillers common in product names
        "без", "для", "под", "про", "как", "из", "по", "на", "со", "за",
        # Common descriptor words
        "desktop", "mini", "midi", "tower", "slim", "ultra",
        # Russian category abbreviations that may follow form-factor
        "бп", "ибп", "мфу", "узу", "сзу",
        # "Без БП" = "without PSU" — skip both words
        "корпус", "кейс",
        # Russian adjective qualifiers that prefix the product category
        "игровая", "игровой", "игровое", "беспроводная", "беспроводной",
        "проводная", "проводной", "механическая", "механический",
        "мембранная", "мембранный", "оптическая", "оптический",
        "лазерная", "лазерный", "ультратонкая", "ультратонкий",
        "портативная", "портативный", "внешний", "внешняя",
        "встроенный", "встроенная", "цветной", "цветная",
        "черно-белый", "черно-белая", "монохромный", "монохромная",
        # Russian category nouns (when they appear as first token after adjective)
        "мышь", "мышка", "клавиатура", "гарнитура", "наушники", "монитор",
        "принтер", "сканер", "колонки", "колонка", "акустика", "камера",
        "ноутбук", "планшет", "смартфон", "телефон", "роутер", "коммутатор",
        "адаптер", "переходник", "кабель", "шнур", "разветвитель",
        "вентилятор", "кулер", "охладитель", "стабилизатор",
    }
    # How many words to skip if name starts with a known multi-word category
    words_to_skip = 0
    stripped = raw.strip().lower()
    for n in (3, 2, 1):
        prefix_words = re.split(r"[\s,.(]+", stripped)[:n]
        prefix = " ".join(prefix_words)
        if prefix in _CATEGORY_LOOKUP:
            words_to_skip = n
            break

    idx = 0
    for token in re.findall(r"[A-Za-zА-Яа-я][A-Za-zА-Яа-я0-9.+_-]{1,}", raw):
        norm = _normalize_compact_name(token)
        if not norm or norm in skip:
            idx += 1
            continue
        if any(ch.isdigit() for ch in norm):
            idx += 1
            continue
        if idx < words_to_skip:
            idx += 1
            continue
        return token
    return ""


def _normalized_brand_token(text):
    return _normalize_compact_name(_preferred_brand_token(text))


def _normalized_category_name(text):
    category = str(normalize_catalog_category_name(infer_category(text)) or "").strip()
    if category == "Без категории":
        return ""
    return category


def _strict_candidate_allowed(local_name, candidate_name):
    local = str(local_name or "").strip()
    candidate = str(candidate_name or "").strip()
    if not local or not candidate:
        return False, "empty"

    local_category = _normalized_category_name(local)
    candidate_category = _normalized_category_name(candidate)
    if local_category and candidate_category and local_category != candidate_category:
        return False, "category"

    local_brand = _normalized_brand_token(local)
    candidate_brand = _normalized_brand_token(candidate)
    if local_brand:
        if not candidate_brand:
            return False, "brand_missing"
        if local_brand != candidate_brand:
            return False, "brand"

    return True, "ok"


def _priority_model_queries(text):
    raw = str(text or "").strip()
    if not raw:
        return []

    seen = set()
    out = []
    brand = _preferred_brand_token(raw)

    def _add(query):
        q = str(query or "").strip()
        key = q.lower()
        if not q or key in seen:
            return
        seen.add(key)
        out.append(q)

    def _push_token(token):
        token = str(token or "").strip()
        norm = _normalize_compact_name(token)
        token_lower = token.lower()
        if len(norm) < 5:
            return
        if not any(ch.isdigit() for ch in norm):
            return
        if not any(ch.isalpha() for ch in norm):
            return
        if re.match(r"^\d{2,4}x\d{2,4}$", token_lower):
            return
        _add(token)
        if brand and norm != _normalize_compact_name(brand):
            _add(f"{brand} {token}")

    for chunk in _paren_chunks(raw):
        for token in extract_article_candidates(chunk):
            _push_token(token)
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{4,}", chunk):
            _push_token(token)

    for token in extract_article_candidates(raw):
        _push_token(token)

    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{4,}", raw):
        _push_token(token)

    return out


def _tgpc_pc_code_queries(text):
    raw = str(text or "").strip()
    if not raw:
        return []

    queries = []
    seen = set()

    def _add(value):
        q = str(value or "").strip()
        key = q.lower()
        if not q or key in seen:
            return
        seen.add(key)
        queries.append(q)

    # TGPC ПЭВМ: "ПЭВМ TGPC Action 5 81872 A-X Ryzen 5 ..."
    # Приоритетный ключ для Onliner: "81872 A-X"
    m = re.search(r"\b(\d{4,6})\s+([A-ZА-Я]-X)\b", raw, flags=re.IGNORECASE)
    if m:
        code = m.group(1).strip()
        suffix = m.group(2).upper().replace("А", "A")
        _add(f"{code} {suffix}")
        _add(f"{code}{suffix.replace('-', '')}")

    # Иногда формат бывает слитный: 81872A-X
    m2 = re.search(r"\b(\d{4,6})([A-ZА-Я]-X)\b", raw, flags=re.IGNORECASE)
    if m2:
        code = m2.group(1).strip()
        suffix = m2.group(2).upper().replace("А", "A")
        _add(f"{code} {suffix}")
        _add(f"{code}{suffix.replace('-', '')}")

    return queries


def _is_tgpc_pc_name(text):
    raw = str(text or "").strip().lower()
    if "tgpc" not in raw:
        return False
    if _tgpc_pc_code_queries(raw):
        return True
    return any(token in raw for token in ["action", "mesh", "osprey", "xtreme", "valise", "gaming"])


def _cpu_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return "", ""
    low = raw.lower()
    brand = ""
    if "intel" in low or "xeon" in low or "pentium" in low or "celeron" in low:
        brand = "intel"
    elif "amd" in low or "ryzen" in low or "athlon" in low:
        brand = "amd"

    patterns = [
        # Intel Core classic: i5-12400F
        r"\b(i[3579]-\d{4,5}[a-z]{0,3})\b",
        # Intel Core Ultra: Core Ultra 5 225 / 225F / 285K
        r"\b(core\s*ultra\s*[3579]\s*\d{3,4}[a-z]{0,3})\b",
        # AMD Ryzen / Ryzen PRO / X3D etc: Ryzen 5 7600X3D, Ryzen 5 PRO 5655G
        r"\b(ryzen\s*[3579]\s*(?:pro\s*)?\d{3,5}[a-z0-9]{0,4})\b",
        # Pentium / Celeron (incl. "Pentium Gold G6405")
        r"\b(pentium\s+(?:gold\s+)?[a-z]?\d{3,5}[a-z]{0,2})\b",
        r"\b(celeron\s+[a-z]?\d{3,5}[a-z]{0,2})\b",
        # Athlon / Athlon Pro 300GE
        r"\b(athlon\s*(?:pro\s*)?[a-z]?\d{3,5}[a-z]{0,3})\b",
        # Xeon E-2378G / W-xxxx / E5-xxxx variants
        r"\b(xeon\s+[a-z]{0,2}-?\d{3,5}[a-z]{0,3}(?:\s*v?\d)?)\b",
        # EPYC families: EPYC 7282
        r"\b(epyc\s+\d{3,4}[a-z]{0,2})\b",
    ]
    model = ""
    # EPYC strings often contain "Series ... Model 7282" — prefer explicit model token.
    m_epyc_model = re.search(r"\bmodel\s+(\d{3,4}[a-z]{0,2})\b", low, flags=re.IGNORECASE)
    if m_epyc_model and m_epyc_model.group(1) and ("epyc" in low):
        model = _normalize_compact_name("epyc " + m_epyc_model.group(1))
    for pattern in patterns:
        if model:
            break
        m = re.search(pattern, low, flags=re.IGNORECASE)
        if m and m.group(1):
            model = _normalize_compact_name(m.group(1))
            break
    if model.startswith("pentiumgold"):
        model = "pentium" + model[len("pentiumgold"):]
    return brand, model


def _cpu_article_code(text):
    raw = str(text or "").strip()
    if not raw:
        return ""
    for m in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{5,40})\)", raw):
        token = str(m.group(1) or "").strip()
        norm = _normalize_compact_name(token)
        if len(norm) < 8:
            continue
        if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
            continue
        if re.match(r"^\d{2,4}$", norm):
            continue
        # skip pure package markers
        if norm in {"oem", "box", "tray", "multipack"}:
            continue
        return norm
    return ""


def _cpu_package_type(text):
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    if re.search(r"(?:^|[^a-z0-9])(box|boxed)(?=$|[^a-z0-9])", raw, flags=re.IGNORECASE):
        return "box"
    if re.search(r"(?:^|[^a-z0-9])(oem|tray)(?=$|[^a-z0-9])", raw, flags=re.IGNORECASE):
        return "oem"
    return ""


def _looks_like_cpu_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.match(r"^\s*процессор\b", low, flags=re.IGNORECASE):
        return True
    cpu_markers = [
        r"(?:^|[^a-z0-9])intel(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])amd(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])ryzen(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])epyc(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])xeon(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])pentium(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])celeron(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])athlon(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])core\s*ultra(?=$|[^a-z0-9])",
        r"socket[-\s]?\d{3,5}",
    ]
    if any(re.search(p, low, flags=re.IGNORECASE) for p in cpu_markers):
        # avoid false positives from whole PCs
        if re.search(r"\bпэвм\b|\bсистемный блок\b|\bкомпьютер\b", low, flags=re.IGNORECASE):
            return False
        return True
    return False


def _find_cpu_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local_brand, local_model = _cpu_brand_model_key(name)
    if not local_brand or not local_model:
        return []
    local_package = _cpu_package_type(name)
    local_code = _cpu_article_code(name)
    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            if local_model:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 120",
                    (f"%{local_model}%",),
                ).fetchall())
            if local_code and len(rows) < 80:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 120",
                    (f"%{local_code}%",),
                ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.93, "source": "cpu_db_seed"})
    except Exception:
        pass
    pool.extend(db_find_top_candidates(name, top_n=16, min_score=0.10, allow_b2b=False))
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Процессор":
            continue
        cand_brand, cand_model = _cpu_brand_model_key(cname)
        if cand_brand != local_brand or cand_model != local_model:
            continue
        cand_package = _cpu_package_type(cname)
        package_delta = 0.0
        if local_package == "oem":
            if cand_package == "oem":
                package_delta = 0.03
            elif cand_package == "box":
                package_delta = -0.12
            else:
                package_delta = 0.01
        elif local_package == "box":
            if cand_package == "box":
                package_delta = 0.03
            elif cand_package == "oem":
                package_delta = -0.12
            else:
                package_delta = 0.01
        else:
            if cand_package:
                package_delta = 0.005
        base_score = max(float(cand.get("score", 0.0) or 0.0), 0.94)
        final_score = round(min(0.999, max(0.0, base_score + package_delta)), 3)
        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": final_score,
            "source": str(cand.get("source", "cpu_db")).strip() or "cpu_db",
            "package": cand_package,
        })
    items.sort(key=lambda item: (
        0 if local_package and item.get("package") == local_package else 1,
        0 if local_package == "oem" and item.get("package") == "" else 1,
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]


def _board_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {
            "brand": "",
            "model": "",
            "model_text": "",
            "chipset": "",
            "socket": "",
            "ddr": "",
            "wifi": None,
            "features": set(),
        }
    cleaned = re.sub(r"^\s*MB\s+", "", raw, flags=re.IGNORECASE).strip()
    low = cleaned.lower()
    brand = ""
    brand_patterns = [
        ("asrock", r"\basrock\b"),
        ("gigabyte", r"\bgigabyte\b"),
        ("asus", r"\basus\b"),
        ("msi", r"\bmsi\b"),
        ("biostar", r"\bbiostar\b"),
        ("colorful", r"\bcolorful\b"),
        ("maxsun", r"\bmaxsun\b"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    socket = ""
    m_socket = re.search(r"\b(?:soc|socket)[-\s]?([a-z0-9-]+)\b", low, flags=re.IGNORECASE)
    if m_socket and m_socket.group(1):
        socket = re.sub(r"[^a-z0-9]+", "", m_socket.group(1).lower())

    chipset = ""
    m_chip = re.search(r"\(([a-z0-9-]{2,12})\)", low, flags=re.IGNORECASE)
    if m_chip and m_chip.group(1):
        chip_candidate = re.sub(r"[^a-z0-9]+", "", m_chip.group(1).lower())
        if re.match(r"^[a-z]\d{2,4}[a-z0-9]*$", chip_candidate):
            chipset = chip_candidate

    ddr = ""
    m_ddr = re.search(r"\bddr\s*([345])\b", low, flags=re.IGNORECASE)
    if m_ddr and m_ddr.group(1):
        ddr = f"ddr{m_ddr.group(1)}"

    model = ""
    model_text = ""
    if brand:
        model_text = re.split(r"\b(?:soc|socket)[-\s]?[a-z0-9-]+\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
        model_text = re.sub(rf"^\s*{re.escape(brand)}\s+", "", model_text, flags=re.IGNORECASE).strip()
        model_text = re.sub(r"\([^)]+\)\s*$", "", model_text).strip()
        model_text = re.sub(r"\s+", " ", model_text)
        model = re.sub(r"[^a-z0-9]+", "", model_text.lower())

    model_feature_source = model_text.lower()
    wifi = bool(
        re.search(r"(?:^|[^a-z0-9])wi[\s-]?fi(?=$|[^a-z0-9])", model_feature_source, flags=re.IGNORECASE)
        or re.search(r"(?:^|[^a-z0-9])ax(?=$|[^a-z0-9])", model_feature_source, flags=re.IGNORECASE)
    )

    feature_patterns = [
        ("d4", r"(?:^|[^a-z0-9])d4(?=$|[^a-z0-9])"),
        ("ax", r"(?:^|[^a-z0-9])ax(?=$|[^a-z0-9])"),
        ("wifi", r"wi[\s-]?fi"),
        ("eagle", r"(?:^|[^a-z0-9])eagle(?=$|[^a-z0-9])"),
        ("aorus", r"(?:^|[^a-z0-9])aorus(?=$|[^a-z0-9])"),
        ("gamingx", r"gaming\s*x"),
        ("steellegend", r"steel\s*legend"),
        ("prors", r"pro\s*rs"),
        ("lightning", r"(?:^|[^a-z0-9])lightning(?=$|[^a-z0-9])"),
        ("livemixer", r"live\s*mixer"),
        ("ds3h", r"(?:^|[^a-z0-9])ds3h(?=$|[^a-z0-9])"),
        ("d3hp", r"(?:^|[^a-z0-9])d3hp(?=$|[^a-z0-9])"),
        ("hdv", r"(?:^|[^a-z0-9])hdv(?=$|[^a-z0-9])"),
        ("elite", r"(?:^|[^a-z0-9])elite(?=$|[^a-z0-9])"),
        ("ud", r"(?:^|[^a-z0-9])ud(?=$|[^a-z0-9])"),
        ("riptide", r"(?:^|[^a-z0-9])riptide(?=$|[^a-z0-9])"),
        ("tomahawk", r"(?:^|[^a-z0-9])tomahawk(?=$|[^a-z0-9])"),
        ("mortar", r"(?:^|[^a-z0-9])mortar(?=$|[^a-z0-9])"),
        ("strix", r"(?:^|[^a-z0-9])strix(?=$|[^a-z0-9])"),
        ("prime", r"(?:^|[^a-z0-9])prime(?=$|[^a-z0-9])"),
    ]
    features = set()
    feature_source = model_feature_source
    for feature_key, pattern in feature_patterns:
        if re.search(pattern, feature_source, flags=re.IGNORECASE):
            features.add(feature_key)

    return {
        "brand": brand,
        "model": model,
        "model_text": model_text.upper(),
        "chipset": chipset,
        "socket": socket,
        "ddr": ddr,
        "wifi": wifi,
        "features": features,
    }


def _find_board_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _board_brand_model_key(name)
    local_brand = local.get("brand", "")
    local_model = local.get("model", "")
    if not local_brand or not local_model:
        return []

    pool = db_find_top_candidates(name, top_n=15, min_score=0.10, allow_b2b=False)
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Материнская плата":
            continue
        cand_board = _board_brand_model_key(cname)
        if cand_board.get("brand") != local_brand:
            continue
        cand_model = cand_board.get("model", "")
        model_exact = cand_model == local_model
        model_close = bool(cand_model and local_model and (cand_model in local_model or local_model in cand_model))
        if not model_exact and not model_close:
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.90)
        if model_exact:
            score += 0.06
        elif model_close:
            score += 0.03
        if local.get("chipset") and cand_board.get("chipset") == local.get("chipset"):
            score += 0.03
        elif local.get("chipset") and cand_board.get("chipset") and cand_board.get("chipset") != local.get("chipset"):
            score -= 0.08
        if local.get("socket") and cand_board.get("socket") == local.get("socket"):
            score += 0.02
        elif local.get("socket") and cand_board.get("socket") and cand_board.get("socket") != local.get("socket"):
            score -= 0.08
        if local.get("ddr") and cand_board.get("ddr") == local.get("ddr"):
            score += 0.03
        elif local.get("ddr") and cand_board.get("ddr") and cand_board.get("ddr") != local.get("ddr"):
            score -= 0.12
        local_wifi = bool(local.get("wifi"))
        cand_wifi = bool(cand_board.get("wifi"))
        if local_wifi != cand_wifi:
            continue
        if local_wifi and cand_wifi:
            score += 0.03

        local_features = set(local.get("features") or set())
        cand_features = set(cand_board.get("features") or set())
        if local_features or cand_features:
            shared_features = local_features & cand_features
            missing_features = local_features - cand_features
            extra_features = cand_features - local_features
            score += min(0.04, 0.012 * len(shared_features))
            score -= min(0.14, 0.035 * len(missing_features))
            score -= min(0.06, 0.015 * len(extra_features - {"wifi"}))

        # If the local board explicitly has a specific suffix/family token, don't trust "close" model too much.
        if model_close and not model_exact and local_features:
            strong_family = {"d4", "ax", "aorus", "eagle", "steellegend", "prors", "lightning", "livemixer", "ds3h", "d3hp", "hdv", "elite", "ud", "riptide", "tomahawk", "mortar", "strix", "prime", "gamingx"}
            if (local_features & strong_family) - cand_features:
                score -= 0.10

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "mb_db")).strip() or "mb_db",
            "chipset": cand_board.get("chipset", ""),
            "socket": cand_board.get("socket", ""),
            "ddr": cand_board.get("ddr", ""),
            "wifi": cand_board.get("wifi"),
            "features": sorted(cand_features),
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    local_sku = str(local.get("sku", "") or "").strip()
    if local_sku:
        exact_items = [item for item in items if str(item.get("sku", "") or "").strip() == local_sku]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _monitor_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {
            "brand": "",
            "model": "",
            "model_text": "",
            "code": "",
            "size": "",
            "resolution": "",
            "hz": "",
            "white": False,
        }
    cleaned = raw.replace("″", '"').replace("“", '"').replace("”", '"').strip()
    low = cleaned.lower()
    size = ""
    m_size = re.match(r'^\s*(\d{2}(?:\.\d)?)\s*"', cleaned)
    if m_size and m_size.group(1):
        size = m_size.group(1)

    brand = ""
    brand_patterns = [
        ("elsa", r"(?:^|[^a-z0-9])elsa(?=$|[^a-z0-9])"),
        ("lg", r"(?:^|[^a-z0-9])lg(?=$|[^a-z0-9])"),
        ("xiaomi", r"(?:^|[^a-z0-9])xiaomi(?=$|[^a-z0-9])"),
        ("asrock", r"(?:^|[^a-z0-9])asrock(?=$|[^a-z0-9])"),
        ("gigabyte", r"(?:^|[^a-z0-9])gigabyte(?=$|[^a-z0-9])"),
        ("msi", r"(?:^|[^a-z0-9])msi(?=$|[^a-z0-9])"),
        ("asus", r"(?:^|[^a-z0-9])asus(?=$|[^a-z0-9])"),
        ("aoc", r"(?:^|[^a-z0-9])aoc(?=$|[^a-z0-9])"),
        ("acer", r"(?:^|[^a-z0-9])acer(?=$|[^a-z0-9])"),
        ("benq", r"(?:^|[^a-z0-9])benq(?=$|[^a-z0-9])"),
        ("philips", r"(?:^|[^a-z0-9])philips(?=$|[^a-z0-9])"),
        ("viewsonic", r"(?:^|[^a-z0-9])viewsonic(?=$|[^a-z0-9])"),
        ("samsung", r"(?:^|[^a-z0-9])samsung(?=$|[^a-z0-9])"),
        ("dell", r"(?:^|[^a-z0-9])dell(?=$|[^a-z0-9])"),
        ("hp", r"(?:^|[^a-z0-9])hp(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    after_brand = cleaned
    # Remove leading descriptor words often present in DB names.
    after_brand = re.sub(r'^\s*(игровой\s+)?монитор\s+', '', after_brand, flags=re.IGNORECASE).strip()
    if size:
        after_brand = re.sub(r'^\s*\d{2}(?:\.\d)?\s*"\s*', '', after_brand, flags=re.IGNORECASE).strip()
    if brand:
        after_brand = re.sub(rf'^\s*{re.escape(brand)}\s+', '', after_brand, flags=re.IGNORECASE).strip()

    resolution = ""
    m_res = re.search(r'(\d{3,4}\s*x\s*\d{3,4})', cleaned, flags=re.IGNORECASE)
    if m_res and m_res.group(1):
        resolution = re.sub(r"\s+", "", m_res.group(1).lower())

    hz = ""
    m_hz = re.search(r'(\d{2,3})\s*(?:гц|hz)\b', low, flags=re.IGNORECASE)
    if m_hz and m_hz.group(1):
        hz = m_hz.group(1)

    white = bool(re.search(r'(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|бел', low, flags=re.IGNORECASE))

    model_text = re.split(r'\s*\(', after_brand, maxsplit=1)[0].strip()
    model_text = re.sub(r"\s+", " ", model_text)
    model = re.sub(r"[^a-z0-9]+", "", model_text.lower())
    code = ""
    # Prefer vendor article in parentheses: (P27UCB-RAGL), (ELA5444EU)
    for m_code in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9\-]{4,40})\)", cleaned):
        tok = str(m_code.group(1) or "").strip()
        norm = re.sub(r"[^a-z0-9]+", "", tok.lower())
        if len(norm) >= 6 and any(ch.isalpha() for ch in norm) and any(ch.isdigit() for ch in norm):
            code = norm
            break
    if not code:
        m_inline_code = re.search(r"\b((?:p|ela)\d[A-Za-z0-9\-]{4,32})\b", cleaned, flags=re.IGNORECASE)
        if m_inline_code and m_inline_code.group(1):
            code = re.sub(r"[^a-z0-9]+", "", m_inline_code.group(1).lower())

    return {
        "brand": brand,
        "model": model,
        "model_text": model_text.upper(),
        "code": code,
        "size": size,
        "resolution": resolution,
        "hz": hz,
        "white": white,
    }


def _find_monitor_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _monitor_brand_model_key(name)
    local_brand = local.get("brand", "")
    local_model = local.get("model", "")
    local_code = str(local.get("code", "") or "").strip()
    if not local_brand or not local_model:
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            model_text = str(local.get("model_text", "") or "").strip()
            brand_sql = local_brand
            if local_code:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 120",
                    (f"%{local_code}%",),
                ).fetchall())
            if brand_sql and model_text:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                    "LIMIT 120",
                    (f"%{brand_sql.lower()}%", f"%{model_text.lower()}%"),
                ).fetchall())
            compact_model = str(local.get("model", "") or "").strip()
            if compact_model and len(rows) < 20:
                tail = re.sub(r"[^a-z0-9]+", "", model_text.lower())
                model_token = model_text.lower()
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 120",
                    (f"%{model_token}%",),
                ).fetchall())
                if tail and tail != model_token:
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '\"', '') LIKE ? "
                        "LIMIT 120",
                        (f"%{tail}%",),
                    ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "mon_db_exact"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=15, min_score=0.10, allow_b2b=False):
        pool.append(cand)
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Монитор":
            continue
        cand_mon = _monitor_brand_model_key(cname)
        if cand_mon.get("brand") != local_brand:
            continue
        cand_model = cand_mon.get("model", "")
        cand_code = str(cand_mon.get("code", "") or "").strip()
        code_exact = bool(local_code and cand_code and cand_code == local_code)
        model_exact = cand_model == local_model
        model_close = bool(cand_model and local_model and (cand_model in local_model or local_model in cand_model))
        if not code_exact and not model_exact and not model_close:
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.90)
        if code_exact:
            score = max(score, 0.97)
            score += 0.05
        if model_exact:
            score += 0.07
        elif model_close:
            score += 0.04
        if local.get("size") and cand_mon.get("size") == local.get("size"):
            score += 0.03
        elif local.get("size") and cand_mon.get("size") and cand_mon.get("size") != local.get("size"):
            score -= 0.10
        if local.get("resolution") and cand_mon.get("resolution") == local.get("resolution"):
            score += 0.03
        elif local.get("resolution") and cand_mon.get("resolution") and cand_mon.get("resolution") != local.get("resolution"):
            score -= 0.10
        if local.get("hz") and cand_mon.get("hz") == local.get("hz"):
            score += 0.03
        elif local.get("hz") and cand_mon.get("hz"):
            try:
                diff_hz = abs(int(local.get("hz")) - int(cand_mon.get("hz")))
            except Exception:
                diff_hz = 999
            score += 0.005 if diff_hz <= 20 else -0.07
        if bool(local.get("white")) != bool(cand_mon.get("white")):
            score -= 0.05

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "mon_db")).strip() or "mon_db",
            "code": cand_code,
            "size": cand_mon.get("size", ""),
            "resolution": cand_mon.get("resolution", ""),
            "hz": cand_mon.get("hz", ""),
            "white": cand_mon.get("white"),
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]


def _gpu_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {
            "gpu_brand": "",
            "vendor": "",
            "gpu_model": "",
            "series": "",
            "sku": "",
            "memory_gb": "",
            "white": False,
            "oc": False,
        }
    low = raw.lower()
    gpu_brand = "nvidia" if "geforce" in low or "rtx" in low or "gtx" in low else ("amd" if "radeon" in low or re.search(r"(?:^|[^a-z0-9])rx\s*\d{3,4}", low) else "")
    vendor = ""
    vendor_patterns = [
        ("gigabyte", r"(?:^|[^a-z0-9])gigabyte(?=$|[^a-z0-9])"),
        ("sapphire", r"(?:^|[^a-z0-9])sapphire(?=$|[^a-z0-9])"),
        ("asus", r"(?:^|[^a-z0-9])asus(?=$|[^a-z0-9])"),
        ("msi", r"(?:^|[^a-z0-9])msi(?=$|[^a-z0-9])"),
        ("palit", r"(?:^|[^a-z0-9])palit(?=$|[^a-z0-9])"),
        ("gainward", r"(?:^|[^a-z0-9])gainward(?=$|[^a-z0-9])"),
        ("zotac", r"(?:^|[^a-z0-9])zotac(?=$|[^a-z0-9])"),
        ("inno3d", r"(?:^|[^a-z0-9])inno3d(?=$|[^a-z0-9])"),
        ("ocpc", r"(?:^|[^a-z0-9])ocpc(?=$|[^a-z0-9])"),
        ("colorful", r"(?:^|[^a-z0-9])colorful(?=$|[^a-z0-9])"),
    ]
    for value, pattern in vendor_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            vendor = value
            break

    gpu_model = ""
    patterns = [
        r"(rtx\s*\d{4}(?:\s*ti)?)",
        r"(gtx\s*\d{3,4}(?:\s*ti)?)",
        r"(gt\s*\d{3,4})",
        r"(rx\s*\d{3,4}\s*xt?)",
        r"(rx\s*\d{3,4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, low, flags=re.IGNORECASE)
        if m and m.group(1):
            gpu_model = re.sub(r"[^a-z0-9]+", "", m.group(1).lower())
            break

    sku = ""
    m_sku = re.search(r"\(([A-Za-z0-9+\- ]{6,40})\)", raw)
    if m_sku and m_sku.group(1):
        sku = re.sub(r"[^a-z0-9]+", "", m_sku.group(1).lower())
    if not sku:
        sku_patterns = [
            r"(gv-[a-z0-9+\- ]{6,40})",
            r"(ne[a-z0-9+\-]{8,40})",
            r"(zt-[a-z0-9+\-]{6,40})",
            r"(ocvn[a-z0-9+\-]{6,40})",
            r"(113\d{2}-\d{2}-\d{2}g)",
        ]
        for pattern in sku_patterns:
            m2 = re.search(pattern, low, flags=re.IGNORECASE)
            if m2 and m2.group(1):
                sku = re.sub(r"[^a-z0-9]+", "", m2.group(1).lower())
                break

    memory_gb = ""
    m_mem = re.search(r"(\d{1,2})\s*gb\b", low, flags=re.IGNORECASE)
    if m_mem and m_mem.group(1):
        memory_gb = m_mem.group(1)

    white = bool(re.search(r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|\bбел(?:ый|ая|ое|ые)?\b", low, flags=re.IGNORECASE))
    oc = bool(re.search(r"(?:^|[^a-z0-9])oc(?=$|[^a-z0-9])", low, flags=re.IGNORECASE))

    series_tokens = [
        ("aoruselite", r"aorus\s*elite"),
        ("aero", r"(?:^|[^a-z0-9])aero(?=$|[^a-z0-9])"),
        ("eaglemax", r"eagle\s*max"),
        ("eagleocice", r"eagle\s*oc\s*ice"),
        ("eagleoc", r"eagle\s*oc"),
        ("eagleice", r"eagle\s*ice"),
        ("eagle", r"(?:^|[^a-z0-9])eagle(?=$|[^a-z0-9])"),
        ("windforcemax", r"windforce\s*max"),
        ("windforceoc", r"windforce\s*oc"),
        ("windforce", r"windforce"),
        ("gamingocice", r"gaming\s*oc\s*ice"),
        ("gamingoc", r"gaming\s*oc"),
        ("gaming", r"(?:^|[^a-z0-9])gaming(?=$|[^a-z0-9])"),
        ("pulseoc", r"pulse\s*oc"),
        ("pulse", r"(?:^|[^a-z0-9])pulse(?=$|[^a-z0-9])"),
        ("pure", r"(?:^|[^a-z0-9])pure(?=$|[^a-z0-9])"),
        ("nitro", r"nitro\+?"),
        ("dualoc", r"dual\s*oc"),
        ("dual", r"(?:^|[^a-z0-9])dual(?=$|[^a-z0-9])"),
        ("stormxoc", r"stormx\s*oc"),
        ("stormx", r"(?:^|[^a-z0-9])stormx(?=$|[^a-z0-9])"),
        ("infinity3oc", r"infinity\s*3\s*oc"),
        ("infinity3", r"infinity\s*3"),
        ("infinity2oc", r"infinity\s*2\s*oc"),
        ("infinity2", r"infinity\s*2"),
        ("gamingprosoc", r"gamingpro-s\s*oc|gaming\s*pro-s\s*oc"),
        ("gamingpros", r"gamingpro-s|gaming\s*pro-s"),
        ("gamingprooc", r"gamingpro\s*oc|gaming\s*pro\s*oc"),
        ("gamingpro", r"gamingpro|gaming\s*pro"),
        ("zoneedition", r"zone\s*edition"),
        ("ventus", r"(?:^|[^a-z0-9])ventus(?=$|[^a-z0-9])"),
    ]
    series = ""
    for key, pattern in series_tokens:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    return {
        "gpu_brand": gpu_brand,
        "vendor": vendor,
        "gpu_model": gpu_model,
        "series": series,
        "sku": sku,
        "memory_gb": memory_gb,
        "white": white,
        "oc": oc,
    }


def _find_gpu_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _gpu_brand_model_key(name)
    if not local.get("vendor") or not local.get("gpu_model"):
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            model_query = local.get("gpu_model", "")
            vendor_query = local.get("vendor", "")
            sku_query = str(local.get("sku", "") or "").strip()
            if vendor_query and model_query:
                spaced_model = re.sub(r"([a-z]+)(\d)", r"\1 \2", model_query)
                if sku_query:
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '+', ''), '(', '') LIKE ? "
                        "LIMIT 80",
                        (f"%{sku_query.replace('+','')}%",),
                    ).fetchall())
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                    "LIMIT 160",
                    (f"%{vendor_query.lower()}%", f"%{spaced_model.lower()}%"),
                ).fetchall())
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '+', '') LIKE ? "
                    "LIMIT 160",
                    (f"%{model_query.replace('+','')}%",),
                ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "gpu_db_exact"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=18, min_score=0.10, allow_b2b=False):
        pool.append(cand)

    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Видеокарта":
            continue
        cand_gpu = _gpu_brand_model_key(cname)
        if cand_gpu.get("vendor") != local.get("vendor"):
            continue
        if cand_gpu.get("gpu_brand") != local.get("gpu_brand"):
            continue
        if cand_gpu.get("gpu_model") != local.get("gpu_model"):
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.90)
        local_sku = str(local.get("sku", "") or "").strip()
        cand_sku = str(cand_gpu.get("sku", "") or "").strip()
        if local_sku:
            if cand_sku == local_sku:
                score = 1.0
            elif cand_sku:
                # For GPU vendors with reliable bracket codes (especially Gigabyte), a different SKU is effectively a different card.
                if local.get("vendor") == "gigabyte":
                    continue
                score -= 0.14
        if local.get("series") and cand_gpu.get("series") == local.get("series"):
            score += 0.05
        elif local.get("series") and cand_gpu.get("series") and cand_gpu.get("series") != local.get("series"):
            score -= 0.10
        if local.get("memory_gb") and cand_gpu.get("memory_gb") == local.get("memory_gb"):
            score += 0.04
        elif local.get("memory_gb") and cand_gpu.get("memory_gb") and cand_gpu.get("memory_gb") != local.get("memory_gb"):
            score -= 0.12
        if local.get("white") != cand_gpu.get("white"):
            score -= 0.06
        if local.get("oc") and cand_gpu.get("oc"):
            score += 0.015
        elif local.get("oc") != cand_gpu.get("oc"):
            score -= 0.04
        if local.get("sku") and cand_gpu.get("sku") == local.get("sku"):
            score += 0.06
        elif local.get("sku") and cand_gpu.get("sku") and local.get("sku") != cand_gpu.get("sku"):
            score -= 0.08

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "gpu_db")).strip() or "gpu_db",
            "series": cand_gpu.get("series", ""),
            "sku": cand_gpu.get("sku", ""),
            "memory_gb": cand_gpu.get("memory_gb", ""),
            "white": cand_gpu.get("white"),
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]


def _ram_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {
            "ddr": "",
            "brand": "",
            "sku": "",
            "capacity_gb": "",
            "kit_modules": "",
            "mhz": "",
            "cl": "",
            "series": "",
            "white": False,
            "rgb": False,
            "ecc": False,
            "reg": False,
        }
    low = raw.lower()
    ddr = ""
    m_ddr = re.search(r"\bddr\s*([345]|iii|iv|v)\b", low, flags=re.IGNORECASE)
    if m_ddr and m_ddr.group(1):
        token = str(m_ddr.group(1) or "").lower()
        if token in {"v", "5"}:
            ddr = "ddr5"
        elif token in {"iv", "4"}:
            ddr = "ddr4"
        elif token in {"iii", "3"}:
            ddr = "ddr3"

    brand = ""
    brand_patterns = [
        ("kingston", r"(?:^|[^a-z0-9])kingston(?=$|[^a-z0-9])"),
        ("gskill", r"(?:^|[^a-z0-9])g\.?skill(?=$|[^a-z0-9])"),
        ("netac", r"(?:^|[^a-z0-9])netac(?=$|[^a-z0-9])"),
        ("team", r"(?:^|[^a-z0-9])team(?=$|[^a-z0-9])"),
        ("adata", r"(?:^|[^a-z0-9])a-?data|(?:^|[^a-z0-9])adata|(?:^|[^a-z0-9])xpg(?=$|[^a-z0-9])"),
        ("patriot", r"(?:^|[^a-z0-9])patriot(?=$|[^a-z0-9])"),
        ("corsair", r"(?:^|[^a-z0-9])corsair(?=$|[^a-z0-9])"),
        ("crucial", r"(?:^|[^a-z0-9])crucial(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    def _ram_norm_sku(value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _is_strong_ram_sku(value):
        v = _ram_norm_sku(value)
        if len(v) < 8:
            return False
        if not any(ch.isalpha() for ch in v) or not any(ch.isdigit() for ch in v):
            return False
        blocked = {
            "ddr3", "ddr4", "ddr5", "rgb", "argb", "mhz", "cl",
            "kitof2", "kitof4", "intel", "amd", "oem", "box"
        }
        if v in blocked:
            return False
        return True

    sku = ""
    m_sku = re.search(r"\(([A-Za-z0-9+\-\/ ]{6,80})\)", raw)
    if m_sku and m_sku.group(1):
        sku = _ram_norm_sku(m_sku.group(1))
    if not sku:
        sku_patterns = [
            r"(KF[0-9A-Z\-\/]{7,})",
            r"(KSM[0-9A-Z\-\/]{6,})",
            r"(KVR[0-9A-Z\-\/]{6,})",
            r"(KCS[0-9A-Z\-\/]{6,})",
            r"(F[45]-[0-9A-Z\-\/]{8,})",
            r"(NT[SA-Z0-9\-\/]{8,})",
            r"(TT[CA-Z0-9\-\/]{8,})",
            r"(AX[0-9A-Z\-\/]{8,})",
            r"(PS[DPV][0-9A-Z\-\/]{7,})",
            r"(CM[A-Z0-9\-\/]{8,})",
            r"(PVV[A-Z0-9\-\/]{6,})",
            r"(PVE[A-Z0-9\-\/]{6,})",
            r"(VEU[A-Z0-9\-\/]{6,})",
        ]
        for pattern in sku_patterns:
            m_inline = re.search(pattern, raw, flags=re.IGNORECASE)
            if m_inline and m_inline.group(1):
                sku = _ram_norm_sku(m_inline.group(1))
                break
    if not sku:
        # Fallback: often RAM code is the last uppercase token (e.g. VEUR532G6028K, PVVR564G600C30K)
        for token in reversed(re.findall(r"\b([A-Za-z0-9\-\/]{8,24})\b", raw)):
            if _is_strong_ram_sku(token):
                sku = _ram_norm_sku(token)
                break

    capacity_gb = ""
    m_cap = re.search(r"(\d{1,3})\s*(?:g|г)\s*(?:b|б)\b", low, flags=re.IGNORECASE)
    if m_cap and m_cap.group(1):
        capacity_gb = m_cap.group(1)
    if not capacity_gb:
        m_cap = re.search(r"\b(\d{1,2})\s*[xх]\s*(\d{1,3})\s*(?:g|г)\s*(?:b|б)\b", low, flags=re.IGNORECASE)
        if m_cap and m_cap.group(1) and m_cap.group(2):
            try:
                capacity_gb = str(int(m_cap.group(1)) * int(m_cap.group(2)))
            except Exception:
                capacity_gb = ""

    kit_modules = ""
    m_kit = re.search(r"kitof\s*(\d+)|kit\s*[xх]\s*(\d+)|(\d+)\s*[xх]\s*\d+\s*(?:g|г)\s*(?:b|б)", low, flags=re.IGNORECASE)
    if m_kit:
        for grp in m_kit.groups():
            if grp:
                kit_modules = grp
                break

    mhz = ""
    m_mhz = re.search(r"(\d{4,5})\s*mhz", low, flags=re.IGNORECASE)
    if m_mhz and m_mhz.group(1):
        mhz = m_mhz.group(1)

    cl = ""
    m_cl = re.search(r"\bcl\s*([0-9]{2})\b", low, flags=re.IGNORECASE)
    if m_cl and m_cl.group(1):
        cl = m_cl.group(1)

    series_patterns = [
        ("furybeastrgb", r"fury\s*beast\s*rgb"),
        ("furybeast", r"fury\s*beast"),
        ("furyrenegade", r"fury\s*renegade"),
        ("tridentzneorgb", r"trident\s*z5\s*neo\s*rgb"),
        ("tridentz5rgb", r"trident\s*z5\s*rgb"),
        ("tridentzrgb", r"trident\s*z\s*rgb"),
        ("tridentz", r"trident\s*z"),
        ("flarex5", r"flare\s*x5"),
        ("ripjawsv", r"ripjaws\s*v"),
        ("ripjawsm5neo", r"ripjaws\s*m5\s*neo\s*rgb"),
        ("ripjawsm5", r"ripjaws\s*m5\s*rgb"),
        ("aegis", r"(?:^|[^a-z0-9])aegis(?=$|[^a-z0-9])"),
        ("shadowiii", r"shadow\s*iii"),
        ("shadowii", r"shadow\s*ii"),
        ("shadows", r"shadow\s*s"),
        ("tcreateexpert", r"t-?create\s*expert"),
        ("vengeancelpx", r"vengeance\s*lpx"),
        ("lancerbladergb", r"lancer\s*blade\s*rgb"),
        ("lancerneonrgb", r"lancer\s*neon\s*rgb"),
        ("basic", r"(?:^|[^a-z0-9])basic(?=$|[^a-z0-9])"),
        ("signatureline", r"signature\s*(premium\s*)?line"),
    ]
    series = ""
    for key, pattern in series_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    white = bool(re.search(r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|\bбел(?:ый|ая|ое|ые)?\b", low, flags=re.IGNORECASE))
    rgb = bool(re.search(r"(?:^|[^a-z0-9])rgb(?=$|[^a-z0-9])", low, flags=re.IGNORECASE))
    ecc = bool(re.search(r"(?:^|[^a-z0-9])ecc(?=$|[^a-z0-9])", low, flags=re.IGNORECASE))
    reg = bool(re.search(r"registered|reg\b|rdimm|lrdimm", low, flags=re.IGNORECASE))

    return {
        "ddr": ddr,
        "brand": brand,
        "sku": sku,
        "capacity_gb": capacity_gb,
        "kit_modules": kit_modules,
        "mhz": mhz,
        "cl": cl,
        "series": series,
        "white": white,
        "rgb": rgb,
        "ecc": ecc,
        "reg": reg,
    }


def _find_ram_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _ram_brand_model_key(name)
    if not local.get("brand") or not local.get("ddr"):
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            sku_query = str(local.get("sku", "") or "").strip()
            brand_query = str(local.get("brand", "") or "").strip()
            if sku_query:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '+', '') LIKE ? "
                    "LIMIT 120",
                    (f"%{sku_query}%",),
                ).fetchall())
            if brand_query and len(rows) < 20:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 120",
                    (f"%{brand_query.lower()}%",),
                ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "ram_db_exact"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=20, min_score=0.10, allow_b2b=False):
        pool.append(cand)

    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Оперативная память":
            continue
        cand_ram = _ram_brand_model_key(cname)
        if cand_ram.get("brand") != local.get("brand"):
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.90)
        local_sku = str(local.get("sku", "") or "").strip()
        local_has_strong_sku = bool(local_sku and len(local_sku) >= 8)
        cand_sku = str(cand_ram.get("sku", "") or "").strip()
        local_ddr = str(local.get("ddr", "") or "").strip()
        cand_ddr = str(cand_ram.get("ddr", "") or "").strip()
        exact_sku = False
        if local_sku:
            if cand_sku == local_sku:
                exact_sku = True
                score = 1.0
            elif cand_sku:
                continue
            elif local_has_strong_sku:
                # If local RAM has a reliable SKU (usually in brackets), do not keep candidates without SKU.
                continue
        if local_ddr and cand_ddr and cand_ddr != local_ddr and not exact_sku:
            continue
        if local_ddr and not cand_ddr and not exact_sku:
            # Candidate is missing DDR marker text; allow only exact-SKU path to avoid junk.
            continue
        if local.get("capacity_gb") and cand_ram.get("capacity_gb") == local.get("capacity_gb"):
            score += 0.03
        elif local.get("capacity_gb") and cand_ram.get("capacity_gb") and cand_ram.get("capacity_gb") != local.get("capacity_gb"):
            score -= 0.10
        if local.get("kit_modules") and cand_ram.get("kit_modules") == local.get("kit_modules"):
            score += 0.025
        elif local.get("kit_modules") and cand_ram.get("kit_modules") and cand_ram.get("kit_modules") != local.get("kit_modules"):
            score -= 0.08
        if local.get("mhz") and cand_ram.get("mhz") == local.get("mhz"):
            score += 0.03
        elif local.get("mhz") and cand_ram.get("mhz") and cand_ram.get("mhz") != local.get("mhz"):
            score -= 0.08
        if local.get("cl") and cand_ram.get("cl") == local.get("cl"):
            score += 0.02
        elif local.get("cl") and cand_ram.get("cl") and cand_ram.get("cl") != local.get("cl"):
            score -= 0.05
        if local.get("series") and cand_ram.get("series") == local.get("series"):
            score += 0.04
        elif local.get("series") and cand_ram.get("series") and cand_ram.get("series") != local.get("series"):
            score -= 0.08
        for flag_key in ["white", "rgb", "ecc", "reg"]:
            if bool(local.get(flag_key)) != bool(cand_ram.get(flag_key)):
                score -= 0.05

        if exact_sku:
            score = 1.0

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "ram_db")).strip() or "ram_db",
            "sku": cand_ram.get("sku", ""),
            "mhz": cand_ram.get("mhz", ""),
            "capacity_gb": cand_ram.get("capacity_gb", ""),
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    local_sku = str(local.get("sku", "") or "").strip()
    if local_sku:
        exact_items = [item for item in items if str(item.get("sku", "") or "").strip() == local_sku]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _ssd_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {"brand": "", "code": "", "model": "", "capacity": "", "external": False}
    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("adata", r"(?:^|[^a-z0-9])a-?data|(?:^|[^a-z0-9])adata|(?:^|[^a-z0-9])xpg(?=$|[^a-z0-9])"),
        ("team", r"(?:^|[^a-z0-9])team(?=$|[^a-z0-9])"),
        ("netac", r"(?:^|[^a-z0-9])netac(?=$|[^a-z0-9])"),
        ("samsung", r"(?:^|[^a-z0-9])samsung(?=$|[^a-z0-9])"),
        ("kingston", r"(?:^|[^a-z0-9])kingston(?=$|[^a-z0-9])"),
        ("crucial", r"(?:^|[^a-z0-9])crucial(?=$|[^a-z0-9])"),
        ("wd", r"(?:^|[^a-z0-9])wd(?:$|[^a-z0-9])|western\s*digital"),
        ("transcend", r"(?:^|[^a-z0-9])transcend(?=$|[^a-z0-9])"),
        ("patriot", r"(?:^|[^a-z0-9])patriot(?=$|[^a-z0-9])"),
        ("hp", r"(?:^|[^a-z0-9])hp(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    def _ssd_norm(value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _is_strong_ssd_code(value):
        v = _ssd_norm(value)
        if len(v) < 8:
            return False
        if not any(ch.isalpha() for ch in v) or not any(ch.isdigit() for ch in v):
            return False
        blocked = {
            "ssd", "nvme", "m2", "pcie", "sata", "usb", "typec",
            "mbps", "tb", "gb", "rtl", "oem", "bulk", "series"
        }
        if v in blocked:
            return False
        return True

    code = ""
    # Parentheses may contain speeds "(500/400)" — pick only strong article-like tokens.
    for m_code in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{4,80})\)", raw):
        token = str(m_code.group(1) or "").strip()
        if _is_strong_ssd_code(token):
            code = _ssd_norm(token)
            break
    if not code:
        tokens = _raw_paren_article_tokens(raw)
        for tok in tokens:
            if _is_strong_ssd_code(tok):
                code = _ssd_norm(tok)
                break
    if not code:
        # Inline article fallback: "... SU800 ASU800SS-512GT-C ..."
        for token in re.findall(r"\b([A-Za-z0-9][A-Za-z0-9.\-/]{6,40})\b", raw):
            if _is_spec_code(_ssd_norm(token).upper()):
                continue
            if _is_strong_ssd_code(token):
                code = _ssd_norm(token)
                break

    model = ""
    for pattern in [
        r"\b(sa\d{3,4})\b",
        r"\b(su\d{3,4})\b",
        r"\b(n\d{3,4}[a-z]?)\b",
        r"\b(nv\d{3,5}(?:-q)?)\b",
        r"\b(sd\d{2,4})\b",
        r"\b(bx\d{3,4})\b",
        r"\b(a\d{3,4})\b",
        r"\b(skc\d{3,5})\b",
        r"\b(snv\d+[a-z0-9]*)\b",
        r"\b(n\d{3,4}[a-z]?)\b",
        r"\b(91\d{2}\s*pro\s*series)\b",
        r"\b(mars\s*980\s*blade)\b",
        r"\b(mars\s*980\s*pro)\b",
        r"\b(fury\s*renegade\s*g5)\b",
        r"\b(cardea\s*z\d{3})\b",
        r"\b(g\d{2}\s*pro)\b",
        r"\b(nv\d{3,5})\b",
        r"\b(p\d{1,4})\b",
        r"\b(sd\d{2,4})\b",
        r"\b(z\s*slim)\b",
    ]:
        m = re.search(pattern, low, flags=re.IGNORECASE)
        if m and m.group(1):
            model = _normalize_compact_name(m.group(1))
            break

    capacity = ""
    m_cap = re.search(r"\b(\d+(?:\.\d+)?)\s*(tb|gb|тб|гб)\b", low, flags=re.IGNORECASE)
    if m_cap and m_cap.group(1) and m_cap.group(2):
        unit = m_cap.group(2).lower()
        if unit in {"тб"}:
            unit = "tb"
        elif unit in {"гб"}:
            unit = "gb"
        capacity = f"{m_cap.group(1)}{unit}"

    external = bool(re.search(r"внешн|portable|usb", low, flags=re.IGNORECASE))
    return {"brand": brand, "code": code, "model": model, "capacity": capacity, "external": external}


def _find_ssd_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _ssd_brand_model_key(name)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_model = str(local.get("model", "") or "").strip()
    local_capacity = str(local.get("capacity", "") or "").strip()
    local_external = bool(local.get("external"))
    if not local_code and not local_brand:
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            if local_code:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 150",
                    (f"%{local_code}%",),
                ).fetchall())
            if local_brand and len(rows) < 80:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{local_brand.lower()}%",),
                ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "ssd_db_seed"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=25, min_score=0.10, allow_b2b=False):
        pool.append(cand)

    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    exact_items = []
    soft_items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if "ssd" not in cname.lower():
            continue

        cand_ssd = _ssd_brand_model_key(cname)
        cand_code = str(cand_ssd.get("code", "") or "").strip()
        cand_brand = str(cand_ssd.get("brand", "") or "").strip()
        cand_model = str(cand_ssd.get("model", "") or "").strip()
        cand_capacity = str(cand_ssd.get("capacity", "") or "").strip()
        cand_external = bool(cand_ssd.get("external"))

        if local_brand and cand_brand and cand_brand != local_brand:
            continue

        is_exact_code = bool(local_code and cand_code and cand_code == local_code)
        model_match = bool(local_model and cand_model and cand_model == local_model)
        capacity_match = bool(local_capacity and cand_capacity and cand_capacity == local_capacity)
        external_mismatch = (local_external != cand_external)

        if is_exact_code:
            score = max(float(cand.get("score", 0.0) or 0.0), 0.97)
            score = 1.0
            if model_match:
                score += 0.01
            if capacity_match:
                score += 0.01
        else:
            if local_code and cand_code and cand_code != local_code:
                # If both sides have explicit SKU/article and they differ — this is another SSD.
                continue
            # Fallback path when exact code is unavailable in DB:
            # require at least one strong anchor (model/capacity) to avoid junk.
            if not (model_match or capacity_match):
                continue
            if local_code and not cand_code and not (model_match and capacity_match):
                # Local has exact code but candidate has no extracted code:
                # keep only very strong structural match to avoid SU650/SU800 mixups.
                continue
            score = max(float(cand.get("score", 0.0) or 0.0), 0.82)
            if model_match:
                score += 0.08
            if capacity_match:
                score += 0.07
            if local_code and not cand_code:
                score -= 0.05
        if external_mismatch:
            score -= 0.08

        seen.add(cid)
        item = {
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "ssd_db")).strip() or ("ssd_db_code_exact" if is_exact_code else "ssd_db_fallback"),
            "code": cand_code,
            "model": cand_model,
            "capacity": cand_capacity,
        }
        if is_exact_code:
            exact_items.append(item)
        else:
            soft_items.append(item)

    exact_items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    soft_items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    items = exact_items if exact_items else soft_items
    return items[:max(1, int(top_n))]


def _psu_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {
            "brand": "",
            "watt": "",
            "eff": "",
            "modular": "",
            "code": "",
            "series": "",
            "form_factor": "",
            "atx": "",
            "white": False,
        }
    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("1stplayer", r"(?:^|[^a-z0-9])1st\s*player(?=$|[^a-z0-9])|(?:^|[^a-z0-9])1stplayer(?=$|[^a-z0-9])"),
        ("adataxpg", r"(?:^|[^a-z0-9])(?:adata|xpg)(?=$|[^a-z0-9])"),
        ("chieftec", r"(?:^|[^a-z0-9])chieftec(?=$|[^a-z0-9])"),
        ("cougar", r"(?:^|[^a-z0-9])cougar(?=$|[^a-z0-9])"),
        ("deepcool", r"(?:^|[^a-z0-9])deepcool(?=$|[^a-z0-9])"),
        ("lianli", r"(?:^|[^a-z0-9])lian\s*li(?=$|[^a-z0-9])|(?:^|[^a-z0-9])lianli(?=$|[^a-z0-9])"),
        ("gamemax", r"(?:^|[^a-z0-9])gamemax(?=$|[^a-z0-9])"),
        ("montech", r"(?:^|[^a-z0-9])montech(?=$|[^a-z0-9])"),
        ("ntech", r"(?:^|[^a-z0-9])n-?tech(?=$|[^a-z0-9])"),
        ("powercase", r"(?:^|[^a-z0-9])powercase(?=$|[^a-z0-9])"),
        ("projectx", r"(?:^|[^a-z0-9])project\s*x(?=$|[^a-z0-9])"),
        ("vicsone", r"(?:^|[^a-z0-9])vicsone(?=$|[^a-z0-9])"),
        ("zalman", r"(?:^|[^a-z0-9])zalman(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    watt = ""
    m_watt = re.search(r"\b(\d{3,4})\s*(?:w|вт)\b", low, flags=re.IGNORECASE)
    if m_watt and m_watt.group(1):
        watt = m_watt.group(1)

    eff = ""
    if re.search(r"80\s*plus\s*titanium|\btitanium\b", low, flags=re.IGNORECASE):
        eff = "titanium"
    elif re.search(r"80\s*plus\s*platinum|\bplatinum\b", low, flags=re.IGNORECASE):
        eff = "platinum"
    elif re.search(r"80\s*plus\s*gold|\bgold\b", low, flags=re.IGNORECASE):
        eff = "gold"
    elif re.search(r"80\s*plus\s*silver|\bsilver\b", low, flags=re.IGNORECASE):
        eff = "silver"
    elif re.search(r"80\s*plus\s*bronze|\bbronze\b", low, flags=re.IGNORECASE):
        eff = "bronze"
    elif re.search(r"80\s*plus\s*standard|\bstandard\b|80\s*plus\b", low, flags=re.IGNORECASE):
        eff = "standard"

    modular = ""
    if re.search(r"non[-\s]?modular|немодуль|не\s*модуль", low, flags=re.IGNORECASE):
        modular = "non"
    elif re.search(r"semi[-\s]?modular|полу[-\s]?модуль", low, flags=re.IGNORECASE):
        modular = "semi"
    elif re.search(r"full[-\s]?modular|полностью\s*модуль", low, flags=re.IGNORECASE):
        modular = "full"

    def _psu_norm(value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _is_strong_psu_code(value):
        norm = _psu_norm(value)
        if len(norm) < 6:
            return False
        if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
            return False
        blocked = {
            "atx", "atx20", "atx23", "atx24", "atx30", "atx31",
            "nonmodular", "semimodular", "fullmodular", "modular",
            "activepfc", "apfc", "llcdc", "dcdc", "ret", "oem", "bulk",
        }
        if norm in blocked:
            return False
        if norm.startswith("atx"):
            return False
        return True

    code = ""
    block_words = {"black", "white", "bronze", "gold", "silver", "platinum", "modular", "nonmodular"}
    preferred_prefixes = ("ps", "ha", "pps", "ppx", "r", "zm", "pn", "pb", "vte", "sr")

    def _token_rank(token):
        t = str(token or "").strip()
        norm = _psu_norm(t)
        if not _is_strong_psu_code(t):
            return -999
        if any(w in norm for w in block_words):
            return -999
        parts = [p for p in re.split(r"-+", t) if p]
        hyphens = max(0, len(parts) - 1)
        score = 0
        if 1 <= hyphens <= 3:
            score += 20
        if len(norm) <= 18:
            score += 12
        if norm.startswith(preferred_prefixes):
            score += 18
        if any(ch.isdigit() for ch in (parts[0] if parts else "")):
            score += 6
        if len(parts) >= 4:
            score -= 6
        return score

    token_candidates = []
    for m in re.finditer(r"\b([A-Za-z0-9]{1,10}(?:[.-][A-Za-z0-9]{1,16}){1,6})\b", raw):
        token = str(m.group(1) or "").strip()
        rank = _token_rank(token)
        if rank > -999:
            token_candidates.append((rank, token))
    if token_candidates:
        token_candidates.sort(key=lambda x: (-x[0], len(_psu_norm(x[1]))))
        code = _psu_norm(token_candidates[0][1])
    if not code:
        # Fallback: parentheses token (if inline heuristic found nothing).
        for m in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9\-]{3,64})\)", raw):
            token = str(m.group(1) or "").strip()
            if _is_strong_psu_code(token):
                code = _psu_norm(token)
                break

    series_patterns = [
        ("ngdpgold", r"ngdp\s*gold"),
        ("ackbronze", r"ack\s*bronze"),
        ("ackgold", r"ack\s*gold"),
        ("dkpremium", r"dk\s*premium"),
        ("core_reactor_ii_ve", r"core\s*reactor\s*ii\s*ve"),
        ("core_reactor_ii", r"core\s*reactor\s*ii"),
        ("cyber_core_ii", r"cyber\s*core\s*ii"),
        ("pylonii", r"pylon\s*ii"),
        ("pylon", r"(?:^|[^a-z0-9])pylon(?=$|[^a-z0-9])"),
        ("kyber", r"(?:^|[^a-z0-9])kyber(?=$|[^a-z0-9])"),
        ("fusion", r"(?:^|[^a-z0-9])fusion(?=$|[^a-z0-9])"),
        ("probe", r"(?:^|[^a-z0-9])probe(?=$|[^a-z0-9])"),
        ("pymcore", r"(?:^|[^a-z0-9])pymcore(?=$|[^a-z0-9])"),
        ("polarispro", r"polaris\s*pro"),
        ("polaris", r"(?:^|[^a-z0-9])polaris(?=$|[^a-z0-9])"),
        ("core", r"(?:^|[^a-z0-9])core(?=$|[^a-z0-9])"),
        ("proton", r"(?:^|[^a-z0-9])proton(?=$|[^a-z0-9])"),
        ("gamerstorm", r"(?:^|[^a-z0-9])gamerstorm(?=$|[^a-z0-9])"),
        ("centuryii", r"century\s*ii"),
        ("centuryg5", r"century\s*g5"),
        ("titangold", r"titan\s*gold"),
        ("titanpla", r"titan\s*pla"),
        ("fk", r"(?:^|[^a-z0-9])fk(?=$|[^a-z0-9])"),
    ]
    series = ""
    for key, pattern in series_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    form_factor = "sfx" if re.search(r"(?:^|[^a-z0-9])sfx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE) else "atx"
    atx = ""
    m_atx = re.search(r"\batx\s*([0-9](?:\.[0-9]{1,2})?)\b", low, flags=re.IGNORECASE)
    if m_atx and m_atx.group(1):
        atx = m_atx.group(1)
    white = bool(re.search(r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|\bбел(?:ый|ая|ое|ые)?\b", low, flags=re.IGNORECASE))
    return {
        "brand": brand,
        "watt": watt,
        "eff": eff,
        "modular": modular,
        "code": code,
        "series": series,
        "form_factor": form_factor,
        "atx": atx,
        "white": white,
    }


def _find_psu_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _psu_brand_model_key(name)
    if not local.get("brand") or not local.get("watt"):
        return []
    local_code = str(local.get("code", "") or "").strip()

    def _psu_code_match(a, b):
        a = re.sub(r"[^a-z0-9]+", "", str(a or "").lower())
        b = re.sub(r"[^a-z0-9]+", "", str(b or "").lower())
        if not a or not b:
            return False
        if a == b:
            return True
        # common suffixes in suppliers/DB variants
        strip_suffixes = ("bulk", "oem", "ret", "wgeu", "eu", "fa0b", "fc0b", "fc0w", "bk", "wh")
        for sfx in strip_suffixes:
            if a.endswith(sfx):
                a = a[: -len(sfx)]
            if b.endswith(sfx):
                b = b[: -len(sfx)]
        if a == b:
            return True
        if len(a) >= 6 and len(b) >= 6 and (a.startswith(b) or b.startswith(a)):
            return True
        if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
            return True
        return False

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            brand_query = str(local.get("brand", "") or "").strip()
            watt_query = str(local.get("watt", "") or "").strip()
            code_query = str(local.get("code", "") or "").strip()
            if code_query:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 180",
                    (f"%{code_query}%",),
                ).fetchall())
            if brand_query and watt_query:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{brand_query.lower()}%", f"%{watt_query}%"),
                ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "psu_db_exact"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=22, min_score=0.10, allow_b2b=False):
        pool.append(cand)
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Блок питания":
            continue
        cand_psu = _psu_brand_model_key(cname)
        if cand_psu.get("brand") != local.get("brand"):
            continue
        if local.get("watt") and cand_psu.get("watt") and cand_psu.get("watt") != local.get("watt"):
            continue
        if local.get("eff") and cand_psu.get("eff") and cand_psu.get("eff") != local.get("eff"):
            continue
        if local.get("modular") and cand_psu.get("modular") and cand_psu.get("modular") != local.get("modular"):
            continue
        if local.get("form_factor") and cand_psu.get("form_factor") and cand_psu.get("form_factor") != local.get("form_factor"):
            continue
        cand_code = str(cand_psu.get("code", "") or "").strip()
        if local_code and cand_code and not _psu_code_match(local_code, cand_code):
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.90)
        if local_code and cand_code and _psu_code_match(local_code, cand_code):
            score = 0.999
        if local.get("series") and cand_psu.get("series") == local.get("series"):
            score += 0.05
        elif local.get("series") and cand_psu.get("series") and cand_psu.get("series") != local.get("series"):
            score -= 0.08
        if local.get("atx") and cand_psu.get("atx"):
            try:
                score += 0.015 if abs(float(local.get("atx")) - float(cand_psu.get("atx"))) <= 0.11 else -0.05
            except Exception:
                pass
        if bool(local.get("white")) != bool(cand_psu.get("white")):
            score -= 0.05

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "psu_db")).strip() or "psu_db",
            "watt": cand_psu.get("watt", ""),
            "eff": cand_psu.get("eff", ""),
            "modular": cand_psu.get("modular", ""),
            "code": cand_code,
            "series": cand_psu.get("series", ""),
        })
    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_code:
        exact_items = [item for item in items if _psu_code_match(local_code, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _case_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {
            "brand": "",
            "code": "",
            "series": "",
            "form_factor": "",
            "with_psu": False,
            "watt": "",
            "white": False,
            "colors": set(),
        }
    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("aerocool", r"(?:^|[^a-z0-9])aerocool(?=$|[^a-z0-9])"),
        ("adataxpg", r"(?:^|[^a-z0-9])(?:adata|xpg)(?=$|[^a-z0-9])"),
        ("cougar", r"(?:^|[^a-z0-9])cougar(?=$|[^a-z0-9])"),
        ("deepcool", r"(?:^|[^a-z0-9])deepcool(?=$|[^a-z0-9])"),
        ("gamemax", r"(?:^|[^a-z0-9])gamemax(?=$|[^a-z0-9])"),
        ("geometricfuture", r"(?:^|[^a-z0-9])geometric\s*future(?=$|[^a-z0-9])"),
        ("montech", r"(?:^|[^a-z0-9])montech(?=$|[^a-z0-9])"),
        ("powercase", r"(?:^|[^a-z0-9])powercase(?=$|[^a-z0-9])"),
        ("projectx", r"(?:^|[^a-z0-9])project\s*x(?=$|[^a-z0-9])"),
        ("segotep", r"(?:^|[^a-z0-9])segotep(?=$|[^a-z0-9])"),
        ("vicsone", r"(?:^|[^a-z0-9])vicsone(?=$|[^a-z0-9])"),
        ("zalman", r"(?:^|[^a-z0-9])zalman(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    form_factor = ""
    if re.search(r"(?:^|[^a-z0-9])e-?atx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "eatx"
    elif re.search(r"(?:^|[^a-z0-9])microatx|m-?atx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "matx"
    elif re.search(r"(?:^|[^a-z0-9])mini-?itx|miniitx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "itx"
    elif re.search(r"(?:^|[^a-z0-9])atx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "atx"

    without_psu = bool(re.search(r"без\s*б/?п|без\s*блока\s*пит", low, flags=re.IGNORECASE))
    with_psu = False
    if not without_psu:
        if re.search(r"\b\d{3,4}\s*w\b", low, flags=re.IGNORECASE) or re.search(r"(?:^|[^a-zа-я0-9])с\s*б/?п(?=$|[^a-zа-я0-9])", low, flags=re.IGNORECASE) or re.search(r"(?:^|[^a-zа-я0-9])б/?п\s+[a-zа-я0-9]", low, flags=re.IGNORECASE):
            with_psu = True
    watt = ""
    m_watt = re.search(r"\b(\d{3,4})\s*w\b", low, flags=re.IGNORECASE)
    if m_watt and m_watt.group(1):
        watt = m_watt.group(1)

    code = ""
    m_paren = re.search(r"\(([A-Za-z0-9][A-Za-z0-9\-]{3,40})\)", raw)
    if m_paren and m_paren.group(1):
        cand = str(m_paren.group(1) or "").strip()
        if not re.match(r"^\d+\s*[xх]", cand.lower()):
            code = re.sub(r"[^a-z0-9]+", "", cand.lower())
    if not code:
        for pattern in [
            r"\b([A-Za-z]{2,6}-[A-Za-z0-9]{2,16}(?:-[A-Za-z0-9]{1,10})?)\b",
            r"\b([A-Za-z]{2,6}[0-9]{2,5}[A-Za-z0-9\-]{0,8})\b",
        ]:
            m_code = re.search(pattern, raw)
            if m_code and m_code.group(1):
                code = re.sub(r"[^a-z0-9]+", "", m_code.group(1).lower())
                break

    series = ""
    series_patterns = [
        ("invaderx", r"invader\s*x"),
        ("defender", r"(?:^|[^a-z0-9])defender(?=$|[^a-z0-9])"),
        ("lander", r"(?:^|[^a-z0-9])lander(?=$|[^a-z0-9])"),
        ("valorairplus", r"valor\s*air\s*plus"),
        ("valorair", r"valor\s*air"),
        ("airface", r"(?:^|[^a-z0-9])airface(?=$|[^a-z0-9])"),
        ("cc560", r"(?:^|[^a-z0-9])cc560(?=$|[^a-z0-9])"),
        ("cg580", r"(?:^|[^a-z0-9])cg580(?=$|[^a-z0-9])"),
        ("ch780", r"(?:^|[^a-z0-9])ch780(?=$|[^a-z0-9])"),
        ("ch170", r"(?:^|[^a-z0-9])ch170(?=$|[^a-z0-9])"),
        ("ch360", r"(?:^|[^a-z0-9])ch360(?=$|[^a-z0-9])"),
        ("ch160", r"(?:^|[^a-z0-9])ch160(?=$|[^a-z0-9])"),
        ("matrexx30", r"matrexx\s*30"),
        ("matrexx55", r"matrexx\s*55"),
        ("dragonknight", r"dragon\s*knight"),
        ("meshbox", r"(?:^|[^a-z0-9])meshbox(?=$|[^a-z0-9])"),
        ("precision", r"(?:^|[^a-z0-9])precision(?=$|[^a-z0-9])"),
        ("air1000", r"air\s*1000"),
        ("hs01pro", r"hs01\s*pro"),
        ("hs02pro", r"hs02\s*pro"),
        ("king95pro", r"king\s*95\s*pro"),
        ("skyone", r"sky\s*one"),
        ("skytwo", r"sky\s*two"),
        ("x3mesh", r"x3\s*mesh"),
        ("xrwood", r"xr\s*wood"),
    ]
    for key, pattern in series_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    color_map = {
        "black": [r"(?:^|[^a-z0-9])black(?=$|[^a-z0-9])", r"черн", r"ч[её]рн"],
        "white": [r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])", r"бел"],
        "gray": [r"(?:^|[^a-z0-9])gray(?=$|[^a-z0-9])", r"(?:^|[^a-z0-9])grey(?=$|[^a-z0-9])", r"сер"],
        "red": [r"(?:^|[^a-z0-9])red(?=$|[^a-z0-9])", r"красн"],
        "blue": [r"(?:^|[^a-z0-9])blue(?=$|[^a-z0-9])", r"син"],
        "green": [r"(?:^|[^a-z0-9])green(?=$|[^a-z0-9])", r"зел"],
        "yellow": [r"(?:^|[^a-z0-9])yellow(?=$|[^a-z0-9])", r"желт"],
        "pink": [r"(?:^|[^a-z0-9])pink(?=$|[^a-z0-9])", r"роз"],
        "orange": [r"(?:^|[^a-z0-9])orange(?=$|[^a-z0-9])", r"оранж"],
        "silver": [r"(?:^|[^a-z0-9])silver(?=$|[^a-z0-9])", r"серебр"],
    }
    colors = set()
    for color_key, patterns in color_map.items():
        for pat in patterns:
            if re.search(pat, low, flags=re.IGNORECASE):
                colors.add(color_key)
                break
    white = "white" in colors
    return {
        "brand": brand,
        "code": code,
        "series": series,
        "form_factor": form_factor,
        "with_psu": with_psu,
        "watt": watt,
        "white": white,
        "colors": colors,
    }


def _case_code_match(a, b):
    """Loose equality for case SKUs (R-… / DP-… vs short series codes in catalog names)."""
    a = re.sub(r"[^a-z0-9]+", "", str(a or "").lower())
    b = re.sub(r"[^a-z0-9]+", "", str(b or "").lower())
    if not a or not b:
        return False
    if a == b:
        return True

    def _strip_leading_r_sku(x):
        if x.startswith("r") and len(x) > 6 and x[1:2].isalpha():
            return x[1:]
        return x

    variants_a = {_strip_leading_r_sku(a), a}
    variants_b = {_strip_leading_r_sku(b), b}
    if variants_a & variants_b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 5 and len(longer) >= 10 and shorter in longer:
        return True
    if len(a) >= 6 and len(b) >= 6 and (a.startswith(b) or b.startswith(a)):
        return True
    if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
        return True
    return False


def _case_form_factor_compatible(local_ff, cand_ff):
    if not local_ff or not cand_ff or local_ff == cand_ff:
        return True
    pair = {local_ff, cand_ff}
    if pair <= {"atx", "eatx"}:
        return True
    return False


def _find_case_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _case_brand_model_key(name)
    if not local.get("brand"):
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            brand_query = str(local.get("brand", "") or "").strip()
            code_query = str(local.get("code", "") or "").strip()
            series_query = str(local.get("series", "") or "").strip()
            if code_query:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 200",
                    (f"%{code_query}%",),
                ).fetchall())
            if brand_query:
                brand_tokens = [brand_query.lower()]
                if brand_query == "adataxpg":
                    brand_tokens = ["adata xpg", "xpg", "adata"]
                elif brand_query == "projectx":
                    brand_tokens = ["project x", "projectx"]
                elif brand_query == "geometricfuture":
                    brand_tokens = ["geometric future", "geometricfuture"]
                for bt in brand_tokens:
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? "
                        "LIMIT 220",
                        (f"%{bt}%",),
                    ).fetchall())
            if series_query:
                series_tokens = {
                    "invaderx": ["invader x", "invaderx"],
                    "defender": ["defender"],
                    "lander": ["lander"],
                    "valorairplus": ["valor air plus", "valorairplus"],
                    "valorair": ["valor air", "valorair"],
                    "air1000": ["air 1000", "air1000"],
                    "king95pro": ["king 95 pro", "king95 pro", "king95pro"],
                    "x3mesh": ["x3 mesh", "x3mesh"],
                    "xrwood": ["xr wood", "xrwood"],
                    "cg580": ["cg 580", "cg580"],
                    "ch170": ["ch 170", "ch170"],
                    "ch360": ["ch 360", "ch360"],
                    "ch160": ["ch 160", "ch160"],
                    "matrexx30": ["matrexx 30", "matrexx30"],
                }.get(series_query, [series_query])
                for st in series_tokens:
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? "
                        "LIMIT 180",
                        (f"%{st.lower()}%",),
                    ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.90, "source": "case_db_exact"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=24, min_score=0.10, allow_b2b=False):
        pool.append(cand)
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Корпус":
            continue
        cand_case = _case_brand_model_key(cname)
        if cand_case.get("brand") != local.get("brand"):
            continue
        if local.get("form_factor") and cand_case.get("form_factor"):
            if not _case_form_factor_compatible(local.get("form_factor"), cand_case.get("form_factor")):
                continue
        if local.get("code") and cand_case.get("code") and not _case_code_match(local.get("code"), cand_case.get("code")):
            continue
        if local.get("with_psu") != cand_case.get("with_psu"):
            continue
        if local.get("with_psu") and local.get("watt") and cand_case.get("watt") and local.get("watt") != cand_case.get("watt"):
            continue
        local_colors = set(local.get("colors") or set())
        cand_colors = set(cand_case.get("colors") or set())
        if local_colors and cand_colors and not (local_colors & cand_colors):
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.88)
        if local.get("code") and cand_case.get("code") and _case_code_match(local.get("code"), cand_case.get("code")):
            score = 0.999
        if local.get("series") and cand_case.get("series") == local.get("series"):
            score += 0.05
        elif local.get("series") and cand_case.get("series") and cand_case.get("series") != local.get("series"):
            score -= 0.08
        if local_colors and cand_colors:
            shared_colors = local_colors & cand_colors
            extra_colors = cand_colors - local_colors
            score += min(0.05, 0.02 * len(shared_colors))
            score -= min(0.08, 0.02 * len(extra_colors))
        elif bool(local.get("white")) != bool(cand_case.get("white")):
            score -= 0.06

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "case_db")).strip() or "case_db",
            "code": cand_case.get("code", ""),
            "series": cand_case.get("series", ""),
            "form_factor": cand_case.get("form_factor", ""),
            "colors": sorted(cand_colors),
        })
    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    local_code = str(local.get("code", "") or "").strip()
    if local_code:
        exact_items = [item for item in items if _case_code_match(local_code, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _hdd_norm_article(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_strong_hdd_paren_code(token):
    v = _hdd_norm_article(token)
    if len(v) < 6:
        return False
    if not any(ch.isalpha() for ch in v) or not any(ch.isdigit() for ch in v):
        return False
    blocked = {
        "sataiii", "usb300", "usb301", "usb302", "usb310", "usb311", "usb312", "usb320",
        "6gbps", "12gbps", "7200rpm", "5400rpm", "5640rpm", "1000rpm",
        "256mb", "512mb", "128mb", "64mb",
        "rtl", "oem", "bulk",
    }
    if v in blocked:
        return False
    return True


def _hdd_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {"brand": "", "code": "", "capacity": "", "external": False, "form": ""}
    low = raw.lower()
    if re.search(r"\bnvme\b|\bm\.2\b|твердотельн", low, flags=re.IGNORECASE):
        return {"brand": "", "code": "", "capacity": "", "external": False, "form": ""}

    brand = ""
    brand_patterns = [
        ("wd", r"(?:^|[^a-z0-9])wd(?:$|[^a-z0-9])|western\s*digital"),
        ("seagate", r"(?:^|[^a-z0-9])seagate(?=$|[^a-z0-9])"),
        ("toshiba", r"(?:^|[^a-z0-9])toshiba(?=$|[^a-z0-9])"),
        ("adata", r"(?:^|[^a-z0-9])a-?data(?=$|[^a-z0-9])|(?:^|[^a-z0-9])adata(?=$|[^a-z0-9])"),
        ("netac", r"(?:^|[^a-z0-9])netac(?=$|[^a-z0-9])"),
        ("hgst", r"(?:^|[^a-z0-9])hgst(?=$|[^a-z0-9])"),
        ("hitachi", r"(?:^|[^a-z0-9])hitachi(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    code = ""
    for m_code in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{4,80})\)", raw):
        token = str(m_code.group(1) or "").strip()
        if _is_strong_hdd_paren_code(token):
            code = _hdd_norm_article(token)
            break
    if not code:
        for tok in _raw_paren_article_tokens(raw):
            if _is_strong_hdd_paren_code(tok):
                code = _hdd_norm_article(tok)
                break
    if not code:
        for token in re.findall(r"\b([A-Za-z0-9][A-Za-z0-9.\-/]{6,40})\b", raw):
            if _is_spec_code(_hdd_norm_article(token).upper()):
                continue
            if _is_strong_hdd_paren_code(token):
                code = _hdd_norm_article(token)
                break

    if not brand and code:
        if code.startswith("st") and len(code) >= 8:
            brand = "seagate"
        elif code.startswith(("wd", "wu")):
            brand = "wd"
        elif code.startswith(("mg", "mq", "hdwd", "hdtb", "dt")):
            brand = "toshiba"
        elif code.startswith(("ahd", "ahv")):
            brand = "adata"
        elif code.startswith("nt0"):
            brand = "netac"

    capacity = ""
    for m_cap in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(tb|gb|тб|гб)\b", low, flags=re.IGNORECASE):
        if not m_cap.group(1) or not m_cap.group(2):
            continue
        tail = low[m_cap.end():m_cap.end() + 3]
        if tail.startswith("/"):
            continue
        unit = m_cap.group(2).lower()
        if unit in {"тб"}:
            unit = "tb"
        elif unit in {"гб"}:
            unit = "gb"
        capacity = f"{m_cap.group(1)}{unit}"

    form = ""
    if re.search(r"2\s*[.,]\s*5\s*\"|2\s*,\s*5\s*\"", low, flags=re.IGNORECASE):
        form = "25"
    elif re.search(r"3\s*[.,]\s*5\s*\"|3\s*,\s*5\s*\"", low, flags=re.IGNORECASE):
        form = "35"

    external = bool(re.search(r"внешн|portable", low, flags=re.IGNORECASE))
    return {
        "brand": brand,
        "code": code,
        "capacity": capacity,
        "external": external,
        "form": form,
    }


def _looks_like_hdd_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.search(r"\bnvme\b|\bm\.2\b|твердотельн", low, flags=re.IGNORECASE):
        return False
    if re.search(r"(?:^|[^a-z0-9])ssd(?:$|[^a-z0-9])", low, flags=re.IGNORECASE) and not re.search(
            r"\bhdd\b|жестк|винчест|hard\s*drive", low, flags=re.IGNORECASE):
        return False
    if re.search(r"\bhdd\b|жестк|винчест|hard\s*drive", low, flags=re.IGNORECASE):
        return True
    if re.search(r"внешний\s+накопитель", low, flags=re.IGNORECASE) and re.search(
            r"\bhdd\b", low, flags=re.IGNORECASE):
        return True
    return False


def _find_hdd_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _hdd_brand_model_key(name)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_capacity = str(local.get("capacity", "") or "").strip()
    local_external = bool(local.get("external"))
    local_form = str(local.get("form", "") or "").strip()
    if not local_code and not local_brand:
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            if local_code:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 180",
                    (f"%{local_code}%",),
                ).fetchall())
            if local_brand and len(rows) < 90:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{local_brand.lower()}%",),
                ).fetchall())
            seed_best = {}
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid:
                    continue
                cat_ok = normalize_catalog_category_name(infer_category(raw_name)) == "Жесткий диск"
                prev = seed_best.get(oid)
                if prev is None:
                    seed_best[oid] = (raw_name, url, cat_ok)
                    continue
                pn, pu, pok = prev
                if cat_ok and not pok or cat_ok == pok and len(str(raw_name or "")) > len(str(pn or "")):
                    seed_best[oid] = (raw_name, url, cat_ok)
            for oid, (raw_name, url, cat_ok) in seed_best.items():
                if not cat_ok:
                    continue
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "hdd_db_seed"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=25, min_score=0.10, allow_b2b=False):
        pool.append(cand)

    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(cname)) != "Жесткий диск":
            continue
        cl = cname.lower()
        if re.search(r"\bnvme\b|\bm\.2\b|твердотельн", cl, flags=re.IGNORECASE):
            continue
        cand_h = _hdd_brand_model_key(cname)
        cand_code = str(cand_h.get("code", "") or "").strip()
        cand_brand = str(cand_h.get("brand", "") or "").strip()
        cand_capacity = str(cand_h.get("capacity", "") or "").strip()
        cand_external = bool(cand_h.get("external"))
        cand_form = str(cand_h.get("form", "") or "").strip()

        if local_brand and cand_brand and cand_brand != local_brand:
            continue
        if local_code and cand_code and not _case_code_match(local_code, cand_code):
            continue
        if local_capacity and cand_capacity and local_capacity.lower() != cand_capacity.lower():
            continue
        if local_external != cand_external:
            continue
        if local_form and cand_form and local_form != cand_form:
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.88)
        if local_code and cand_code and _case_code_match(local_code, cand_code):
            score = 0.999

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "hdd_db")).strip() or "hdd_db",
            "code": cand_code,
            "capacity": cand_capacity,
        })
    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_code:
        exact_items = [item for item in items if _case_code_match(local_code, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _printer_mfp_norm_article(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _looks_like_printer_or_mfp_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.search(r"\bпринтер\b|\bпринтеры\b|\bмфу\b|\bmfp\b", low, flags=re.IGNORECASE):
        return True
    return False


def _printer_mfp_catalog_category_ok(raw_name):
    rn = str(raw_name or "").strip()
    if not rn:
        return False
    low = rn.lower()
    if re.search(r"\bпринтер\b|\bпринтеры\b|\bмфу\b|\bmfp\b|\bmultifunction\b", low, flags=re.IGNORECASE):
        return True
    try:
        cat = normalize_catalog_category_name(infer_category(rn))
    except Exception:
        cat = ""
    return cat == "Принтер и МФУ"


def _printer_mfp_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {"brand": "", "article": "", "model_compact": "", "model_display": ""}
    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("canon", r"\bcanon\b"),
        ("pantum", r"\bpantum\b"),
        ("hp", r"(?:^|[^a-z0-9])hp(?=$|[^a-z0-9])"),
        ("epson", r"\bepson\b"),
        ("brother", r"\bbrother\b"),
        ("xerox", r"\bxerox\b"),
        ("kyocera", r"\bkyocera\b"),
        ("ricoh", r"\bricoh\b"),
        ("samsung", r"\bsamsung\b"),
        ("lexmark", r"\blexmark\b"),
        ("oki", r"\boki\b"),
        ("sharp", r"\bsharp\b"),
        ("konica", r"\bkonica\b"),
        ("develop", r"\bdevelop\b"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    work = re.sub(r"^\s*(?:принтер|мфу)\s+", "", raw, flags=re.IGNORECASE).strip()
    if brand:
        work = re.sub(rf"^.*?\b{re.escape(brand)}\b\s*", "", work, count=1, flags=re.IGNORECASE).strip()

    head = work.split("(", 1)[0].strip()
    head = re.split(r",\s*(?:лазерный|струйный|цветн|черно|формат)", head, 1, flags=re.IGNORECASE)[0].strip()
    model_display = head[:160] if head else ""
    model_compact = re.sub(r"[^a-z0-9]+", "", head.lower())

    article = ""
    for m_code in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{4,40})\)", raw):
        token = str(m_code.group(1) or "").strip()
        if re.match(r"^\d+\s*x\s*\d+", token, flags=re.IGNORECASE):
            continue
        if re.search(r"(?:dpi|мм|стр/мин|lan|wifi)", token, flags=re.IGNORECASE):
            continue
        av = _printer_mfp_norm_article(token)
        if len(av) < 6:
            continue
        if not any(ch.isdigit() for ch in av) or not any(ch.isalpha() for ch in av):
            continue
        article = av
        break

    return {
        "brand": brand,
        "article": article,
        "model_compact": model_compact,
        "model_display": model_display,
    }


def _find_printer_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _printer_mfp_brand_model_key(name)
    local_article = str(local.get("article", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_mc = str(local.get("model_compact", "") or "").strip()
    if not local_brand and not local_article and len(local_mc) < 5:
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            if local_article:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 180",
                    (f"%{local_article}%",),
                ).fetchall())
            if local_brand and len(rows) < 90:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{local_brand.lower()}%",),
                ).fetchall())
            if local_mc and len(local_mc) >= 6 and len(rows) < 140:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 180",
                    (f"%{local_mc}%",),
                ).fetchall())
            seed_best = {}
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid:
                    continue
                if not _printer_mfp_catalog_category_ok(raw_name):
                    continue
                prev = seed_best.get(oid)
                if prev is None:
                    seed_best[oid] = (raw_name, url, True)
                    continue
                pn, pu, _ = prev
                if len(str(raw_name or "")) > len(str(pn or "")):
                    seed_best[oid] = (raw_name, url, True)
            for oid, (raw_name, url, _cat_ok) in seed_best.items():
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "printer_db_seed"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=25, min_score=0.10, allow_b2b=False):
        pool.append(cand)

    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if not _printer_mfp_catalog_category_ok(cname):
            continue
        cand_local = _printer_mfp_brand_model_key(cname)
        cand_article = str(cand_local.get("article", "") or "").strip()
        cand_mc = str(cand_local.get("model_compact", "") or "").strip()
        cand_brand = str(cand_local.get("brand", "") or "").strip()

        if local_brand and cand_brand and local_brand != cand_brand:
            continue

        match_ok = False
        if local_article:
            if cand_article and _case_code_match(local_article, cand_article) or local_article in _printer_mfp_norm_article(cname):
                match_ok = True
        if not match_ok and local_mc and len(local_mc) >= 5 and cand_mc:
            if local_mc in cand_mc or cand_mc in local_mc or local_mc == cand_mc:
                match_ok = True
        if not match_ok:
            continue

        score = max(float(cand.get("score", 0.0) or 0.0), 0.86)
        if local_article and cand_article and _case_code_match(local_article, cand_article):
            score = 0.999
        elif local_mc and cand_mc and (local_mc in cand_mc or cand_mc in local_mc):
            score = max(score, 0.95)

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "printer_db")).strip() or "printer_db",
            "code": cand_article or cand_mc,
        })
    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_article:
        exact_items = [item for item in items if _case_code_match(local_article, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _cooler_norm_article(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _cooler_paren_looks_socket_bundle(token):
    t = str(token or "").strip().lower()
    if not t:
        return True
    if re.match(r"^\d", t):
        return True
    if t.count("/") >= 2 and re.search(r"\b(lga|am\d|fm\d)\b", t):
        return True
    if re.search(r"\d{2,4}\s*шт\s*/", t):
        return True
    return False


def _is_strong_cooler_paren_code(token):
    raw_t = str(token or "").strip()
    # Разрешаем артикулы вроде 1C251B1361000 / 4N005-01-20G (с цифры в начале), отсекаем только «чисто числовые» скобки.
    if not raw_t or re.match(r"^\d+$", raw_t):
        return False
    v = _cooler_norm_article(raw_t)
    if len(v) < 4 or not any(ch.isalpha() for ch in v):
        return False
    blocked = {"sataiii", "usb320", "usb310", "rtl", "oem", "bulk", "ret", "box"}
    if v in blocked:
        return False
    return True


def _cooler_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {"brand": "", "code": "", "tdp": "", "colors": set(), "white": False}
    low = raw.lower()
    if re.search(r"\bкорпус\b|\bбез\s+бп\b", low, flags=re.IGNORECASE):
        return {"brand": "", "code": "", "tdp": "", "colors": set(), "white": False}

    brand = ""
    brand_patterns = [
        ("deepcool", r"deep\s*cool|deepcool"),
        ("cryorig", r"(?:^|[^a-z0-9])cryorig(?=$|[^a-z0-9])"),
        ("idcooling", r"id[\s\-]*cooling|(?:^|[^a-z0-9])id\s+cooling"),
        ("montech", r"(?:^|[^a-z0-9])montech(?=$|[^a-z0-9])"),
        ("xpg", r"\bxpg\b"),
        ("adata", r"\badata\b"),
        ("geometricfuture", r"geometric\s*future|geometricfuture"),
        ("sapphire", r"\bsapphire\b"),
        ("thermalright", r"thermal\s*right|thermalright"),
        ("arctic", r"arctic\s*cooling|(?:^|[^a-z0-9])arctic(?=$|[^a-z0-9])"),
        ("alseye", r"(?:^|[^a-z0-9])alseye(?=$|[^a-z0-9])"),
        ("noctua", r"(?:^|[^a-z0-9])noctua(?=$|[^a-z0-9])"),
        ("bequiet", r"be\s*quiet|bequiet"),
        ("zalman", r"(?:^|[^a-z0-9])zalman(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    code = ""
    for m_code in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{3,80})\)", raw):
        token = str(m_code.group(1) or "").strip()
        if _cooler_paren_looks_socket_bundle(token):
            continue
        if _is_strong_cooler_paren_code(token):
            code = _cooler_norm_article(token)
            break
    if not code:
        for tok in _raw_paren_article_tokens(raw):
            if _cooler_paren_looks_socket_bundle(tok):
                continue
            if _is_strong_cooler_paren_code(tok):
                code = _cooler_norm_article(tok)
                break
    if not code:
        for pattern in [
            r"\b(R-[A-Za-z0-9\-]{6,40})\b",
            r"\b(CR-[A-Za-z0-9\-]{2,24})\b",
            r"\b(MACHO-[A-Z0-9\-]{2,24})\b",
            r"\b(ACALP[a-z0-9]{4,20})\b",
            r"\b(AS-[A-Z0-9\-]{2,20})\b",
            r"\b(SE-\d{3}(?:-[A-Z0-9]{2,})+)\b",
            r"\b(IS-\d{2}[A-Z]*(?:-[A-Z]{2,})?)\b",
            r"\b(DK-\d{2}[A-Z]?)\b",
            r"\b(AG\d{3})\b",
            r"\b(AK\d{3})\b",
            r"\b(NX\d{3})\b",
            r"\b(FROZN\s+A\d{3}(?:\s+[A-Z]+)*)\b",
            r"\b(LEVANTE[A-Z0-9\-]{4,36})\b",
            r"\b(ACFRE\d{5}[A-Z]?)\b",
            r"\b(F-[A-Z0-9\-]{4,40})\b",
            r"\b(A-ELITE[A-Z0-9\-]{2,36})\b",
            r"\b(C-MATRIX[A-Z0-9\-]{2,24})\b",
            r"\b(TURBO-RIGHT-[A-Z0-9\-]{2,24})\b",
            r"\b(4N\d{3}-\d{2}-\d{2}[A-Z])\b",
            r"\b(1C[0-9A-Z]{8,14})\b",
        ]:
            m = re.search(pattern, raw, flags=re.IGNORECASE)
            if m and m.group(1):
                cand = str(m.group(1) or "").strip()
                if _is_strong_cooler_paren_code(cand):
                    code = _cooler_norm_article(cand)
                    break

    if not brand and code:
        if re.search(r"deep\s*cool|deepcool", low, flags=re.IGNORECASE):
            brand = "deepcool"
        elif re.search(r"id[\s\-]*cooling|id\s+cooling", low, flags=re.IGNORECASE):
            brand = "idcooling"
        elif re.search(r"cryorig", low, flags=re.IGNORECASE) or code.startswith("cr"):
            brand = "cryorig"
        elif re.search(r"thermal\s*right|thermalright|macho", low, flags=re.IGNORECASE) or code.startswith("macho"):
            brand = "thermalright"
        elif code.startswith("acalp") or re.search(r"alpine", low, flags=re.IGNORECASE):
            brand = "arctic"
        elif re.search(r"montech", low, flags=re.IGNORECASE) or code.startswith("nx"):
            brand = "montech"
        elif re.search(r"alseye", low, flags=re.IGNORECASE):
            brand = "alseye"
        elif re.search(r"\blevante\b|levanteii", low, flags=re.IGNORECASE) or (code and "levante" in code):
            brand = "xpg"
        elif (code and str(code).upper().startswith("ACFRE")) or re.search(r"liquid\s+freezer|freezer\s+iii", low, flags=re.IGNORECASE):
            brand = "arctic"
        elif re.search(r"geometric|eskimo", low, flags=re.IGNORECASE) or (code and re.match(r"^1c", str(code), flags=re.IGNORECASE)):
            brand = "geometricfuture"
        elif re.search(r"\bsapphire\b|nitro\+", low, flags=re.IGNORECASE) or (code and str(code).upper().startswith("4n")):
            brand = "sapphire"

    tdp = ""
    m_tdp = re.search(r"\btdp\s*(\d{2,4})\s*w\b", low, flags=re.IGNORECASE)
    if m_tdp and m_tdp.group(1):
        tdp = str(int(m_tdp.group(1)))
    if not tdp:
        m_tdp2 = re.search(r"\b(\d{2,4})\s*w\s*tdp\b", low, flags=re.IGNORECASE)
        if m_tdp2 and m_tdp2.group(1):
            tdp = str(int(m_tdp2.group(1)))

    color_map = {
        "black": [r"(?:^|[^a-z0-9])black(?=$|[^a-z0-9])", r"\bbk\b", r"черн"],
        "white": [r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])", r"\bwh\b", r"\bwh\s", r"бел"],
        "gray": [r"(?:^|[^a-z0-9])grey(?=$|[^a-z0-9])", r"(?:^|[^a-z0-9])gray(?=$|[^a-z0-9])", r"сер"],
    }
    colors = set()
    for color_key, patterns in color_map.items():
        for pat in patterns:
            if re.search(pat, low, flags=re.IGNORECASE):
                colors.add(color_key)
                break
    white = "white" in colors
    return {"brand": brand, "code": code, "tdp": tdp, "colors": colors, "white": white}


def _cooler_catalog_category_ok(raw_name):
    cat = normalize_catalog_category_name(infer_category(str(raw_name or "")))
    low = str(raw_name or "").lower()
    if cat == "Кулер":
        return True
    if cat == "Охлаждение":
        if re.search(r"кулер|для\s*процессора|cpu\s*cooler", low, flags=re.IGNORECASE):
            return True
        # СЖО / водянка для CPU в каталоге Onliner
        if re.search(
            r"жидкостн|\bсжо\b|водян|water\s*cool|all[\s\-]in[\s\-]one|"
            r"freezer|levante|dashflow|eskimo|frozen\s+|aqua\s+elite|"
            r"насос|\bpump\b|240mm|280mm|360mm|420mm|2x120mm|3x120mm|3x140mm",
            low,
            flags=re.IGNORECASE,
        ):
            return True
    return False


def _cooler_seed_rank(raw_name):
    cat = normalize_catalog_category_name(infer_category(str(raw_name or "")))
    if cat == "Кулер":
        base = 100
    elif cat == "Охлаждение":
        base = 50
    else:
        base = 0
    return base + min(80, len(str(raw_name or "")))


def _looks_like_cooler_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.search(r"\bкорпус\b|\bжестк|\bhdd\b", low, flags=re.IGNORECASE):
        return False
    if re.match(r"^\s*кулер\b", low, flags=re.IGNORECASE):
        return True
    if re.search(r"\bcpu\s*cooler\b|\bдля\s*процессора\b.*\bкулер\b", low, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_liquid_cpu_cooling_name(text):
    """СЖО / AIO для процессора в прайсе (не вентиляторы в корпус)."""
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.search(r"\bкорпус\b|\bжестк|\bhdd\b|\bssd\b", low, flags=re.IGNORECASE):
        return False
    if re.search(
        r"система\s+водяного\s+охлаждения|водяного\s+охлаждения\b|"
        r"\bсжо\b|жидкостн(?:ое|ая|ые)?\s+охлажден|водян(?:ое|ая|ые)?\s+охлажден",
        low,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(r"\ball[\s\-]in[\s\-]one\b|\baio\b|liquid\s+(freezer|cool)|water\s*cool", low, flags=re.IGNORECASE):
        return True
    if re.search(
        r"\b(dashflow|levante|eskimo|lightflow|liquid\s+freezer|freezer\s+iii)\b|"
        r"\bfrozen\s+(edge|horizon|infinity|magic|notte|prism|warframe)\b|"
        r"\baqua\s+elite\b|\bcore\s+matrix\b|\bturbo\s+right\b|\bnitro\+|"
        r"\bid[\s\-]*cooling\s+(sl|dashflow|dx|fx)\w",
        low,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _find_cooler_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = _cooler_brand_model_key(name)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_tdp = str(local.get("tdp", "") or "").strip()
    local_is_liquid = _looks_like_liquid_cpu_cooling_name(name)
    if not local_code and not local_brand:
        return []

    pool = []
    try:
        with _db_connection() as conn:
            rows = []
            if local_code:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 200",
                    (f"%{local_code}%",),
                ).fetchall())
            if local_brand and len(rows) < 90:
                bt = {
                    "bequiet": ["be quiet", "bequiet"],
                    "idcooling": ["id-cooling", "id cooling", "idcooling"],
                    "xpg": ["xpg", "adata xpg"],
                    "geometricfuture": ["geometric future", "geometricfuture"],
                }.get(local_brand, [local_brand])
                for brand_q in bt:
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? "
                        "LIMIT 220",
                        (f"%{brand_q.lower()}%",),
                    ).fetchall())
            seed_map = {}
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid:
                    continue
                if not _cooler_catalog_category_ok(raw_name):
                    continue
                rank = _cooler_seed_rank(raw_name)
                prev = seed_map.get(oid)
                if prev is None or rank > prev[2]:
                    seed_map[oid] = (raw_name, url, rank)
            for oid, (raw_name, url, _) in seed_map.items():
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "cooler_db_seed"})
    except Exception:
        pass

    for cand in db_find_top_candidates(name, top_n=25, min_score=0.10, allow_b2b=False):
        pool.append(cand)

    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if not _cooler_catalog_category_ok(cname):
            continue
        cl = cname.lower()
        if not local_is_liquid:
            if re.search(r"жидкостн|\bсжо\b|водян", cl, flags=re.IGNORECASE) and "кулер" not in cl:
                continue
        cand_c = _cooler_brand_model_key(cname)
        cand_code = str(cand_c.get("code", "") or "").strip()
        cand_brand = str(cand_c.get("brand", "") or "").strip()
        cand_tdp = str(cand_c.get("tdp", "") or "").strip()

        if local_brand and cand_brand and cand_brand != local_brand:
            continue
        nm_lc = _cooler_norm_article(cname)
        if local_code:
            if cand_code:
                if not _case_code_match(local_code, cand_code):
                    continue
            elif len(local_code) >= 5:
                # Parsed catalog code is often missing; avoid unrelated same-brand hits (e.g. Thermalright Assassin vs Macho).
                if local_code not in nm_lc:
                    if local_brand == "cryorig":
                        m_h = re.match(r"^crh(\d+)", local_code)
                        if not (m_h and f"h{m_h.group(1)}" in nm_lc):
                            continue
                    else:
                        continue
        local_colors = set(local.get("colors") or set())
        cand_colors = set(cand_c.get("colors") or set())
        if local_colors and cand_colors and not (local_colors & cand_colors):
            continue
        if local_tdp and cand_tdp:
            try:
                if abs(int(local_tdp) - int(cand_tdp)) > 25:
                    continue
            except Exception:
                pass

        score = max(float(cand.get("score", 0.0) or 0.0), 0.88)
        if local_code and cand_code and _case_code_match(local_code, cand_code):
            score = 0.999

        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "cooler_db")).strip() or "cooler_db",
            "code": cand_code,
            "tdp": cand_tdp,
        })
    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_code:
        exact_items = [item for item in items if _case_code_match(local_code, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _looks_like_peripheral_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    return bool(re.search(
        r"клавиатур|keyboard|мышь|мыши|mouse|гарнитур|наушник|headset|headphones|колонк|акустик|speaker|soundbar",
        low,
        flags=re.IGNORECASE,
    ))


def _peripheral_catalog_category_ok(raw_name):
    rn = str(raw_name or "").strip()
    if not rn:
        return False
    try:
        cat = normalize_catalog_category_name(infer_category(rn))
    except Exception:
        cat = ""
    if cat in {"Клавиатура", "Мышь", "Наушники", "Акустика"}:
        return True
    return _looks_like_peripheral_name(rn)


def _find_peripheral_review_candidates(product_name, top_n=5):
    name = str(product_name or "").strip()
    if not name:
        return []
    pool = []
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool.append(exact)
    pool.extend(db_find_top_candidates(name, top_n=25, min_score=0.18, allow_b2b=False))
    items = []
    seen = set()
    for cand in pool:
        if not isinstance(cand, dict):
            continue
        cid = normalize_onliner_id(cand.get("id", ""))
        cname = str(cand.get("name", "") or "").strip()
        if not cid or not cname or cid in seen:
            continue
        if not _peripheral_catalog_category_ok(cname):
            continue
        score = float(cand.get("score", 0.0) or 0.0)
        if score < 0.25 and not str(cand.get("source", "")).startswith("exact"):
            continue
        seen.add(cid)
        items.append({
            "id": cid,
            "name": cname,
            "url": str(cand.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(cand.get("source", "peripheral_db")).strip() or "peripheral_db",
        })
    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]


def _looks_like_case_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.match(r"^\s*корпус\b", low, flags=re.IGNORECASE):
        return True
    # Typical case descriptors in full RU/EN names
    case_markers = [
        r"tempered\s*glass",
        r"vga\s*max",
        r"cpu\s*max",
        r"(?:^|[^a-z0-9])mesh(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])без\s*б/?п(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])mini-?itx(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])microatx(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])e-?atx(?=$|[^a-z0-9])",
    ]
    if any(re.search(p, low, flags=re.IGNORECASE) for p in case_markers):
        return True

    # Short catalog names without "Корпус": Brand + recognizable case model line
    brand_prefix = r"^\s*(deepcool|montech|gamemax|zalman|adata|xpg|aerocool|powercase|cougar|vicsone|segotep|project\s*x)\b"
    model_tokens = r"(cc560|ch780|ch160|matrexx|invader|defender|lander|valor\s*air|air\s*1000|king\s*95|x3\s*mesh|xr\s*wood|hs0[12]\s*pro|sky\s*one|sky\s*two|meshbox|dragon\s*knight|precision)"
    if re.search(brand_prefix, low, flags=re.IGNORECASE) and re.search(model_tokens, low, flags=re.IGNORECASE):
        return True
    return False


def search_onliner_candidates(local_name, category_name="", query="", limit=80, max_queries=4, timeout_sec=6):
    app_settings = load_app_settings()
    search_cfg = (app_settings.get("no_id_search") or {})
    name = str(local_name or "").strip()
    text_query = str(query or "").strip()
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    hints = _category_path_hints(category_name)
    limit = max(5, min(int(limit or search_cfg.get("max_candidates", 80) or 80), 150))
    max_queries = max(1, min(int(max_queries or search_cfg.get("max_queries", 4) or 4), 8))
    category_rules = get_no_id_category_rules(app_settings)
    category_rule = category_rules.get(str(category_name or "").strip(), {}) if isinstance(category_rules, dict) else {}
    require_category_hint = _coerce_bool(search_cfg.get("require_category_hint", False), default=False)
    if not name and not text_query:
        return []

    queries = []
    seen_queries = set()

    def add_query(value):
        q = str(value or "").strip()
        key = q.lower()
        if not q or key in seen_queries:
            return
        seen_queries.add(key)
        queries.append(q)

    if text_query:
        add_query(text_query)
    for q in _tgpc_pc_code_queries(name or text_query):
        add_query(q)
    if _is_tgpc_pc_name(name or text_query):
        for q in _tgpc_pc_code_queries(name or text_query):
            add_query(f"TGPC {q}")
            add_query(f"Компьютеры TGPC {q}")
    if _coerce_bool(search_cfg.get("prefer_paren_model", True), default=True):
        for q in _priority_model_queries(name):
            add_query(q)
    art = str(extract_article(name) or "").strip()
    if _coerce_bool(search_cfg.get("prefer_article_tokens", True), default=True):
        add_query(art)
    token_pool = list(_name_tokens(name)[:8])
    if not _coerce_bool(search_cfg.get("include_brand_token", True), default=True):
        brand = _preferred_brand_token(name)
        brand_norm = _normalize_compact_name(brand)
        token_pool = [tok for tok in token_pool if _normalize_compact_name(tok) != brand_norm]
    token_query = " ".join(token_pool).strip()
    add_query(token_query)
    if isinstance(category_rule, dict):
        add_query(category_rule.get("query_hint", ""))
    if name:
        add_query(name[:130])
    queries = queries[:max(1, int(max_queries or 1))]

    cache_key = f"{ID_REPLACE_QUERY_CACHE_VERSION}|{str(category_name or '').strip().lower()}|{(text_query or token_query or name[:80]).strip().lower()}|{int(limit)}"
    now_ts = int(time.time())
    with ID_REPLACE_QUERY_CACHE_LOCK:
        cached = ID_REPLACE_QUERY_CACHE.get(cache_key)
        if isinstance(cached, dict) and now_ts - int(cached.get("ts", 0)) <= ID_REPLACE_QUERY_CACHE_TTL:
            return list(cached.get("items") or [])[:limit]

    seen_ids = set()
    candidates = []

    def _push_candidate(item):
        if not isinstance(item, dict):
            return
        pid = normalize_onliner_id(item.get("id", ""))
        pname = str(item.get("name", "") or "").strip()
        if not pid or not pname or pid in seen_ids:
            return
        score = round(float(item.get("score", 0.0) or 0.0), 3)
        if score < 0.34:
            return
        payload = {
            "id": pid,
            "name": pname,
            "url": str(item.get("url", "") or "").strip(),
            "score": score,
            "source": str(item.get("source", "") or "api"),
            "reason": str(item.get("reason", "") or ""),
        }
        candidates.append(payload)
        seen_ids.add(pid)

    for c in onliner_b2b_search_candidates(name or text_query, category_name=category_name, limit=min(limit, 24)):
        _push_candidate(c)
        if len(candidates) >= limit:
            break

    local_models = _model_hint_tokens(name or text_query)
    local_paren_models = _model_hint_tokens(" ".join(_paren_chunks(name or text_query)))
    local_articles = _article_like_tokens(name or text_query)
    local_text = str(name or text_query).lower()
    local_has_special_edition = bool(re.search(r"\b(xbox|playstation|usb)\b", local_text))
    local_is_tgpc_pc = _is_tgpc_pc_name(name or text_query)
    local_tgpc_code = _extract_tgpc_pc_code(name or text_query) if local_is_tgpc_pc else ""
    for q in queries:
        try:
            rs = onliner_api_get(
                f"https://catalog.api.onliner.by/search/products?query={quote(q)}",
                timeout=max(2, int(timeout_sec or 6)),
                headers=headers,
            )
            if not rs.ok:
                continue
            data = rs.json() or {}
            products = data.get("products") or []
        except Exception:
            continue
        for p in products[:40]:
            pid = normalize_onliner_id(p.get("id", ""))
            pname = str(p.get("full_name") or p.get("name") or "").strip()
            purl = str(p.get("html_url") or "").strip()
            if not pid or not pname or pid in seen_ids:
                continue
            allowed, _reason = _strict_candidate_allowed(name or text_query, pname)
            if not allowed:
                continue
            if require_category_hint and hints and purl and not any(h in purl for h in hints):
                continue
            cmp = calc_name_match(name or text_query, pname)
            score = float(cmp.get("score", 0.0) or 0.0)
            candidate_models = _model_hint_tokens(pname)
            candidate_articles = _article_like_tokens(pname)
            paren_hits = _token_family_match(local_paren_models, candidate_models)
            if cmp.get("match"):
                score = max(score, 0.74)
            if paren_hits:
                score = max(score, 0.95)
            if local_articles and candidate_articles and not _token_family_match(local_articles, candidate_articles):
                score = min(score, 0.18)
            elif local_models and candidate_models and not _token_family_match(local_models, candidate_models):
                score *= 0.62
            candidate_lower = pname.lower()
            if local_is_tgpc_pc:
                candidate_is_tgpc = "tgpc" in candidate_lower
                candidate_is_pc_url = bool(purl and any(h in purl for h in ["/desktop/", "/computer/", "/tgpc/"]))
                if not candidate_is_tgpc and not candidate_is_pc_url:
                    continue
                if not candidate_is_tgpc:
                    score *= 0.70
                if not candidate_is_pc_url:
                    score *= 0.80
                # Если знаем конкретный код конфигурации (91479, 91482, ...),
                # кандидат без этого кода в названии/URL — ненадёжный вариант.
                if local_tgpc_code:
                    cand_code = _extract_tgpc_pc_code(pname)
                    if cand_code and cand_code != local_tgpc_code:
                        # Код есть, но другой — точно не тот товар
                        score = min(score, 0.12)
                    elif not cand_code and local_tgpc_code not in (pname + purl):
                        # Кода нет нигде — возможно общая страница серии, не конкретная конфиг
                        score = min(score, 0.68)
            if isinstance(category_rule, dict):
                must_contain = [str(x).strip().lower() for x in (category_rule.get("must_contain") or []) if str(x).strip()]
                ignore_words = [str(x).strip().lower() for x in (category_rule.get("ignore_words") or []) if str(x).strip()]
                if must_contain and not any(x in candidate_lower for x in must_contain):
                    score *= 0.55
                if ignore_words and any(x in candidate_lower for x in ignore_words):
                    score *= 0.35
            candidate_has_special_edition = bool(re.search(r"\b(xbox|playstation|usb)\b", candidate_lower))
            candidate_has_color = bool(re.search(r"\((черный|чёрный|белый|зеленый|зелёный|розовый|синий|красный|yellow|pink|white|black|green|blue)\)", candidate_lower))
            if not local_has_special_edition and candidate_has_special_edition:
                score *= 0.78
            elif not local_has_special_edition and candidate_has_color:
                score = max(score, score + 0.03)
            if hints and purl and not any(h in purl for h in hints):
                score *= 0.78
            if score < 0.34:
                continue
            _push_candidate({
                "id": pid,
                "name": pname,
                "url": purl,
                "score": round(float(score), 3),
                "source": "api",
                "reason": str(cmp.get("reason", "") or ""),
            })
        if len(candidates) >= limit:
            break

    candidates.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
    top_score = float(candidates[0].get("score", 0.0) or 0.0) if candidates else 0.0
    if top_score >= 0.90:
        min_score = 0.52
    elif top_score >= 0.78:
        min_score = 0.46
    else:
        min_score = 0.40
    final_items = [c for c in candidates if float(c.get("score", 0.0) or 0.0) >= min_score][:limit]
    with ID_REPLACE_QUERY_CACHE_LOCK:
        ID_REPLACE_QUERY_CACHE[cache_key] = {"ts": now_ts, "items": final_items}
        if len(ID_REPLACE_QUERY_CACHE) > 400:
            keys = list(ID_REPLACE_QUERY_CACHE.keys())[:120]
            for k in keys:
                ID_REPLACE_QUERY_CACHE.pop(k, None)
    return final_items


def _name_tokens(text):
    words = re.findall(r"[a-zа-я0-9]+", str(text or "").lower())
    stop = {
        "для", "с", "и", "на", "по", "ret", "rtl", "oem", "box",
        "black", "white", "blue", "red", "green", "grey", "gray", "silver", "gold",
        "черный", "чёрный", "белый", "синий", "голубой", "красный", "зеленый", "зелёный",
        "серый", "серебристый", "золотой", "желтый", "жёлтый", "orange", "pink", "purple",
    }
    out = []
    seen = set()

    def _push(token):
        token = str(token or "").strip()
        if len(token) < 3 or token in stop or token in seen:
            return
        seen.add(token)
        out.append(token)

    for w in words:
        _push(w)
        m = re.match(r"^(\d{2,4})(w|mhz|gb|tb)$", w)
        if m:
            _push(m.group(1))
            continue
        m = re.match(r"^(\d{2,4})(mm)$", w)
        if m:
            _push(m.group(1))
    return out


def _normalize_compact_name(text):
    return re.sub(r"[^a-zа-я0-9]+", "", str(text or "").lower())


def _normalize_match_text(text):
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"\(([^()]*)\)", lambda m: " " if _is_color_only_chunk(m.group(1)) else f" {m.group(1)} ", raw)
    raw = re.sub(r"[^a-zа-я0-9]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _paren_chunks(text):
    return [str(x).strip() for x in re.findall(r"\(([^()]*)\)", str(text or "")) if str(x).strip()]


def _is_color_only_chunk(text):
    words = [w for w in re.findall(r"[a-zа-я0-9]+", str(text or "").lower()) if len(w) >= 3]
    if not words:
        return False
    return all(w in {
        "black", "white", "blue", "red", "green", "grey", "gray", "silver", "gold",
        "черный", "чёрный", "белый", "синий", "голубой", "красный", "зеленый", "зелёный",
        "серый", "серебристый", "золотой", "желтый", "жёлтый", "orange", "pink", "purple",
    } for w in words)


def _model_hint_tokens(text):
    raw = str(text or "")
    out = set()
    for token in _article_like_tokens(raw):
        out.add(token)
    for chunk in _paren_chunks(raw):
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{3,}", chunk):
            norm = _normalize_compact_name(token)
            upper = norm.upper()
            if (len(norm) >= 4
                    and any(ch.isdigit() for ch in norm)
                    and any(ch.isalpha() for ch in norm)
                    and not re.match(r'^\d+[xX][A-Z]', upper)
                    and not _is_spec_code(upper)):
                out.add(norm)
    for token in _name_tokens(raw):
        if len(token) >= 4 and any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
            upper = token.upper()
            if not re.match(r'^\d+[xX][A-Z]', upper) and not _is_spec_code(upper):
                out.add(token)
    refined = set()
    for token in out:
        refined.add(token)
        m = re.match(r"([a-z]{1,5}\d{2,5}[a-z]{0,3})", token)
        if m:
            refined.add(m.group(1))
    return refined


def _token_family_match(left_tokens, right_tokens):
    a = set(left_tokens or [])
    b = set(right_tokens or [])
    if not a or not b:
        return set()
    hits = set()
    for left in a:
        for right in b:
            if left == right:
                hits.add(left)
                continue
            short, long = (left, right) if len(left) <= len(right) else (right, left)
            if len(short) >= 8 and long.startswith(short):
                hits.add(short)
    return hits


def _capacity_tokens(text):
    raw = _normalize_match_text(text)
    hits = set()
    for num, unit in re.findall(r"(\d+(?:[\.,]\d+)?)\s*(tb|gb)", raw):
        norm_num = str(num).replace(",", ".").rstrip("0").rstrip(".")
        hits.add(f"{norm_num}{unit}")
    return hits


def _important_name_tokens(text):
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    generic = {
        "беспроводная", "беспроводной", "беспроводное", "wireless",
        "проводная", "проводной", "wired",
        "игровая", "игровой", "gaming",
        "гарнитура", "наушники", "headset", "headphones",
        "мышь", "мышка", "mouse",
        "клавиатура", "keyboard",
        "колонки", "колонка", "акустика", "speakers",
        "черный", "чёрный", "белый", "синий", "красный", "зеленый", "зелёный",
        "black", "white", "blue", "red", "green", "grey", "gray", "pink", "purple",
    }
    tokens = []
    seen = set()
    for token in re.findall(r"[a-zа-я0-9]+", raw):
        if len(token) < 3:
            continue
        if token in generic:
            continue
        if token.isdigit():
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _ordered_token_hits(left_tokens, right_tokens):
    right_set = set(right_tokens or [])
    return [tok for tok in (left_tokens or []) if tok in right_set]


# Color groups: each group contains all equivalent color tokens (EN + RU).
# The first element of each tuple is the canonical key.
_COLOR_GROUPS = [
    ("black",     {"black", "черный", "чёрный", "черн", "blk"}),
    ("white",     {"white", "белый", "wht"}),
    ("silver",    {"silver", "grey", "gray", "серый", "серебристый", "серебро"}),
    ("blue",      {"blue", "синий", "голубой", "dark blue"}),
    ("red",       {"red", "красный"}),
    ("green",     {"green", "зеленый", "зелёный"}),
    ("gold",      {"gold", "золотой", "золото"}),
    ("yellow",    {"yellow", "желтый", "жёлтый"}),
    ("orange",    {"orange", "оранжевый"}),
    ("purple",    {"purple", "violet", "фиолетовый"}),
    ("pink",      {"pink", "розовый"}),
    ("brown",     {"brown", "коричневый"}),
]
# Flat map: any color word → canonical key
_COLOR_CANON = {}
for _ckey, _cset in _COLOR_GROUPS:
    for _cv in _cset:
        _COLOR_CANON[_cv] = _ckey


def _color_tokens(text):
    """Return set of CANONICAL color keys found in text (cross-language)."""
    raw = re.sub(r"[^a-zа-яёa-z0-9]+", " ", str(text or "").lower())
    hits = set()
    for word, canon in _COLOR_CANON.items():
        if f" {word} " in f" {raw} ":
            hits.add(canon)
    return hits


# ── Product category detection ────────────────────────────────────────────
# Each group is a frozenset of all known forms (RU abbreviation, RU full, EN).
# The matching key is the frozenset itself — two names share a category only
# if they map to the same frozenset.
_CATEGORY_GROUPS = [
    frozenset(["бп", "блок питания", "блоки питания", "psu", "power supply"]),
    frozenset(["ибп", "ибп ", "источник бесперебойного питания", "ups"]),
    frozenset(["мфу", "мфу ", "multifunctional", "принтер-сканер"]),
    frozenset(["принтер", "printer"]),
    frozenset(["сканер", "scanner"]),
    frozenset(["монитор", "monitor", "дисплей", "display"]),
    frozenset(["клавиатура", "keyboard"]),
    frozenset(["мышь", "мышка", "mouse"]),
    frozenset(["гарнитура", "наушники", "headset", "headphones"]),
    frozenset(["колонки", "колонка", "акустика", "speakers"]),
    frozenset(["корпус", "case"]),
    frozenset(["кулер", "cooler", "охладитель", "cooling"]),
    frozenset(["видеокарта", "видеоадаптер", "gpu", "graphics"]),
    frozenset(["процессор", "cpu", "processor"]),
    frozenset(["материнская плата", "материнка", "motherboard", "mainboard"]),
    frozenset(["оперативная память", "память ddr", "озу", "ram"]),
    frozenset(["ssd", "ссд накопитель", "твердотельный накопитель"]),
    frozenset(["hdd", "жесткий диск", "жёсткий диск", "hdd накопитель"]),
    frozenset(["ноутбук", "laptop", "notebook"]),
    frozenset(["планшет", "tablet"]),
    frozenset(["смартфон", "телефон", "phone", "smartphone"]),
    frozenset(["кабель", "cable", "шнур", "провод"]),
    frozenset(["разветвитель", "разветвитель для", "хаб", "hub", "splitter",
               "usb-хаб", "usb хаб", "usb-hub"]),
    frozenset(["dok-stantsiya", "dok stantsiya", "dock station", "док-станция", "док станция"]),
    frozenset(["адаптер", "adapter", "переходник", "конвертер"]),
    frozenset(["флеш", "флешка", "usb накопитель", "usb flash"]),
    frozenset(["роутер", "маршрутизатор", "router", "wi-fi роутер"]),
    frozenset(["коммутатор", "switch", "свитч"]),
    frozenset(["зарядное устройство", "сзу", "зарядка", "charger"]),
    frozenset(["источник питания", "блок питания для ноутбука"]),
    frozenset(["стабилизатор", "стабилизатор напряжения"]),
    frozenset(["термопаста", "термопрокладка", "thermal paste"]),
    frozenset(["кронштейн", "крепление", "bracket", "mount"]),
    frozenset(["внешний накопитель", "внешний жесткий диск", "portable hdd"]),
    frozenset(["картридж", "cartridge", "тонер"]),
    frozenset(["веб-камера", "вебкамера", "webcam"]),
    frozenset(["микрофон", "microphone"]),
    frozenset(["удлинитель", "сетевой фильтр", "surge protector"]),
    frozenset(["охлаждающая подставка", "подставка для ноутбука"]),
    frozenset(["кулер для процессора", "процессорный кулер"]),
    frozenset(["система охлаждения", "водяное охлаждение", "сжо", "aio cooler"]),
    frozenset(["вентилятор", "fan", "корпусной вентилятор"]),
    frozenset(["память", "модуль памяти"]),  # generic fallback for RAM
]
# Flat map: normalized-lowercase form → frozenset (canonical group)
_CATEGORY_LOOKUP = {}
for _grp in _CATEGORY_GROUPS:
    for _form in _grp:
        _CATEGORY_LOOKUP[_form.strip().lower()] = _grp


def _extract_product_category(name: str):
    """Return the canonical category frozenset for name, or None if unknown.

    Tries to match the first 1–3 words against the category map.
    """
    raw = str(name or "").strip().lower()
    # Try progressively shorter prefixes: 3 words, 2 words, 1 word
    words = re.split(r"[\s,.(]+", raw)
    for n in (3, 2, 1):
        prefix = " ".join(words[:n])
        if prefix in _CATEGORY_LOOKUP:
            return _CATEGORY_LOOKUP[prefix]
    return None


_SPEC_CODE_PREFIXES = {
    # Storage/RAID connector standards — not unique product articles
    "SFF", "SAS", "SATA", "SASATA",
    # PCIe form-factor codes
    "PCIE", "PCIEX", "M2",
    # USB / display standards
    "USB", "HDMI", "DISPLAYPORT", "THUNDERBOLT",
    # Memory standards
    "DIMM", "SODIMM", "DDR", "LPDDR",
    # Power connector codes
    "ATX", "EPS",
    # NVMe / NVME
    "NVME",
    # Common spec-only prefixes that appear in cable/adapter names
    "OCU", "OCULINK",
}


def _is_spec_code(norm_upper: str) -> bool:
    """Return True if the token is a well-known interface/spec code rather than a unique article."""
    for prefix in _SPEC_CODE_PREFIXES:
        if norm_upper.startswith(prefix):
            return True
    return False


def _raw_paren_article_tokens(text):
    """Extract vendor article codes from parentheses — RAM/GPU/SSD (e.g. (KF436C16RB12/16), (KF560C36BBE-32))."""
    raw_text = str(text or "")
    found = []
    seen = set()
    # Must start with a letter; mix of letters+digits; ≥6 chars — skips (Black), (OEM), (52502)
    for m in re.finditer(
        r"\(\s*([A-Za-z][A-Za-z0-9.\-/]{5,})\s*\)",
        raw_text,
    ):
        tok = m.group(1).strip()
        if not (any(ch.isdigit() for ch in tok) and any(ch.isalpha() for ch in tok)):
            continue
        norm = _normalize_compact_name(tok)
        if _is_spec_code(norm.upper()):
            continue
        if norm in seen:
            continue
        seen.add(norm)
        found.append(tok)
    return found


def _raw_search_tokens(text):
    """Return raw tokens (preserving hyphens/dots) for SQL LIKE queries.
    E.g. 'GK-240L' stays 'GK-240L' so LIKE '%GK-240L%' can match the DB entry."""
    raw_text = str(text or "")
    out = []
    seen_norm = set()
    # Highest priority: explicit article in parentheses (ОЗУ Kingston и т.п.)
    for tok in _raw_paren_article_tokens(raw_text):
        norm = _normalize_compact_name(tok)
        if norm not in seen_norm:
            seen_norm.add(norm)
            out.append(tok)
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{3,}", raw_text):
        if not (any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t)):
            continue
        upper = t.upper()
        norm = _normalize_compact_name(t)
        if _is_spec_code(norm.upper()):
            continue
        if re.match(r'^\d+[xX][A-Z]', upper):
            continue
        m = re.match(r'^\d+([A-Z]{1,4})$', upper)
        if m and m.group(1) in {"MM", "CM", "W", "V", "A", "MHZ", "GHZ", "DPI", "HZ", "RPM"}:
            continue
        if norm not in seen_norm:
            seen_norm.add(norm)
            out.append(t)  # keep original form with hyphens
    # Also add GPU combined tokens (raw, so "RX5700XT" still fine for LIKE)
    for gm in re.finditer(
        r"\b(RX|GTX|RTX|R[0-9]|HD|VEGA|ARC)\s+(\d{3,4})\s*(XT|Ti|TI|XTX|SUPER|M|S)?\b",
        raw_text, re.IGNORECASE
    ):
        combined = gm.group(1) + gm.group(2) + (gm.group(3) or "")
        if combined not in out:
            out.append(combined)
    return out[:5]


def _article_like_tokens(text):
    raw = str(text or "")
    out = set()

    _MEASURE_UNITS = {"MM", "CM", "M", "W", "V", "A", "MHZ", "GHZ",
                      "TB", "GB", "MB", "KB", "DPI", "PPI", "RPM", "HZ",
                      "BIT", "BITS", "MS", "NM", "G", "KG", "LM"}

    def _add(norm):
        upper = norm.upper()
        # Reject multiplier-connector patterns: 1xUSB, 2xHDMI, 4xSATA
        if re.match(r'^\d+[xX][A-Z]', upper):
            return
        # Reject pure-measurement tokens: 350MM, 1200DPI, 120MM, 450W
        m = re.match(r'^\d+([A-Z]{1,4})$', upper)
        if m and m.group(1) in _MEASURE_UNITS:
            return
        if (len(norm) >= 5
                and any(ch.isdigit() for ch in norm)
                and any(ch.isalpha() for ch in norm)
                and not _is_spec_code(upper)):
            out.add(norm)

    for tok in _raw_paren_article_tokens(raw):
        _add(_normalize_compact_name(tok))

    for q in _tgpc_pc_code_queries(raw):
        _add(_normalize_compact_name(q))
    for t in extract_article_candidates(raw):
        _add(_normalize_compact_name(t))
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{3,}", raw):
        _add(_normalize_compact_name(t))
        # Also try each segment of hyphenated compound codes:
        # "DP-ATX-MATREXX55-V3" → also add "MATREXX55" as a token
        segs = re.split(r'[-/]', t)
        if len(segs) > 1:
            for seg in segs:
                _add(_normalize_compact_name(seg))

    # Склеиваем GPU-паттерны: "RX 5700 XT" → "RX5700XT", "GTX 1660 Super" → "GTX1660SUPER"
    for m in re.finditer(
        r"\b(RX|GTX|RTX|R[0-9]|HD|VEGA|ARC)\s+(\d{3,4})\s*(XT|Ti|TI|XTX|SUPER|M|S)?\b",
        raw, re.IGNORECASE
    ):
        combined = m.group(1) + m.group(2) + (m.group(3) or "")
        _add(_normalize_compact_name(combined))

    # Процессорные суффиксы: "5600X", "5900X", "i9-13900K" — короткие коды в скобках
    for m in re.finditer(r"\b([A-Za-z]{1,4}[-]?\d{3,5}[A-Za-z]{0,3})\b", raw):
        _add(_normalize_compact_name(m.group(1)))

    return out


def _extract_tgpc_pc_code(text):
    """
    Извлекает 5-значный числовой код конфигурации TGPC ПК (напр. '91479' из '91479 I-X').
    Каждый код уникален — разные коды означают разные товары.
    """
    raw = str(text or "").strip()
    for pat in [
        r"\b(\d{4,6})\s+[A-ZА-Яa-zа-я]-[Xx]\b",
        r"\((\d{4,6})\s+[A-ZА-Яa-zа-я]-[Xx]\)",
        r"\b(\d{4,6})[A-ZА-Яa-zа-я]-[Xx]\b",
    ]:
        m = re.search(pat, raw, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_gpu_model(text):
    """
    Извлекает нормализованный токен видеокарты из названия ПК.
    Пример: 'RTX 5070Ti 16Gb' → 'RTX5070TI', 'RTX 5060 8Gb' → 'RTX5060'.
    """
    raw = _normalize_match_text(str(text or ""))
    # NVIDIA RTX/GTX
    m = re.search(r"\b(rtx|gtx)\s*(\d{3,4})\s*(ti|super)?\b", raw, flags=re.IGNORECASE)
    if m:
        parts = [m.group(1).upper(), m.group(2)]
        if m.group(3):
            parts.append(m.group(3).upper())
        return "".join(parts)
    # AMD RX/Radeon
    m = re.search(r"\b(rx)\s*(\d{3,4})\s*(xt|gre|xtx)?\b", raw, flags=re.IGNORECASE)
    if m:
        parts = ["RX", m.group(2)]
        if m.group(3):
            parts.append(m.group(3).upper())
        return "".join(parts)
    # Intel Arc
    m = re.search(r"\barc\s+(a\d{3})\b", raw, flags=re.IGNORECASE)
    if m:
        return "ARC" + m.group(1).upper()
    return ""


def calc_name_match(local_name, onliner_name):
    a = str(local_name or "").strip()
    b = str(onliner_name or "").strip()
    if not a or not b:
        return {"score": 0.0, "match": False, "reason": "no_name"}

    # ── Категорийный барьер: разные категории → сразу 0 ─────────────────────
    cat_a = _extract_product_category(a)
    cat_b = _extract_product_category(b)
    if cat_a and cat_b and cat_a != cat_b:
        return {"score": 0.02, "match": False, "reason": "category_mismatch"}
    # ─────────────────────────────────────────────────────────────────────────

    # ── TGPC ПК: строгая проверка по уникальному коду конфигурации ──────────
    local_tgpc_code = _extract_tgpc_pc_code(a)
    onl_tgpc_code = _extract_tgpc_pc_code(b)
    if local_tgpc_code:
        if onl_tgpc_code:
            if local_tgpc_code != onl_tgpc_code:
                # Разные коды → гарантированно разные товары
                return {"score": 0.04, "match": False, "reason": "tgpc_code_mismatch"}
            # Коды совпали — дополнительно сверяем GPU
            local_gpu = _extract_gpu_model(a)
            onl_gpu = _extract_gpu_model(b)
            if local_gpu and onl_gpu and local_gpu != onl_gpu:
                # Один и тот же код, но GPU отличается — Onliner вернул похожую конфигурацию
                return {"score": 0.35, "match": False, "reason": "tgpc_gpu_mismatch"}
            return {"score": 1.0, "match": True, "reason": "tgpc_code_exact"}
        # Наш код есть, у Onliner-продукта кода нет — неоднозначно,
        # не блокируем, но потолок оценки будет ограничен ниже
    # ────────────────────────────────────────────────────────────────────────

    art_local = str(extract_article(a) or "").upper()
    art_onl = str(extract_article(b) or "").upper()
    if art_local and art_onl and art_local == art_onl:
        return {"score": 1.0, "match": True, "reason": "article"}

    # Часто артикулы не в скобках, поэтому отдельно проверяем article-like токены.
    local_article_like = _article_like_tokens(a)
    onl_article_like = _article_like_tokens(b)
    if local_article_like and onl_article_like and (local_article_like & onl_article_like):
        local_capacity = _capacity_tokens(a)
        onl_capacity = _capacity_tokens(b)
        local_colors = _color_tokens(a)
        onl_colors = _color_tokens(b)
        score = 0.97
        if local_capacity and onl_capacity and not (local_capacity & onl_capacity):
            score = 0.83
        elif local_colors and onl_colors and (local_colors & onl_colors):
            score = 0.985
        return {"score": score, "match": True, "reason": "article_like"}

    local_paren_models = _model_hint_tokens(" ".join(_paren_chunks(a)))
    onl_paren_models = _model_hint_tokens(" ".join(_paren_chunks(b)))
    paren_intersection = _token_family_match(local_paren_models, onl_paren_models)
    if paren_intersection:
        return {"score": 0.94, "match": True, "reason": "paren_model"}

    local_models = _model_hint_tokens(a)
    onl_models = _model_hint_tokens(b)
    model_intersection = _token_family_match(local_models, onl_models)
    if model_intersection:
        base_score = 0.90 if local_paren_models and model_intersection.intersection(local_paren_models) else 0.84
        local_capacity = _capacity_tokens(a)
        onl_capacity = _capacity_tokens(b)
        local_colors = _color_tokens(a)
        onl_colors = _color_tokens(b)
        if local_capacity and onl_capacity and (local_capacity & onl_capacity):
            base_score = max(base_score, 0.92)
        if local_colors and onl_colors and (local_colors & onl_colors):
            base_score = min(0.97, base_score + 0.02)
        return {"score": base_score, "match": True, "reason": "model_token"}
    if local_article_like and onl_article_like and not _token_family_match(local_article_like, onl_article_like):
        return {"score": 0.18, "match": False, "reason": "article_conflict"}

    clean_a = _normalize_match_text(a)
    clean_b = _normalize_match_text(b)
    local_capacity = _capacity_tokens(clean_a)
    onl_capacity = _capacity_tokens(clean_b)
    local_colors = _color_tokens(clean_a)
    onl_colors = _color_tokens(clean_b)
    ta = set(_name_tokens(clean_a))
    tb = set(_name_tokens(clean_b))
    important_a = _important_name_tokens(a)
    important_b = _important_name_tokens(b)
    important_hits = _ordered_token_hits(important_a, important_b)
    brand_a = _normalize_compact_name(_preferred_brand_token(a))
    brand_b = _normalize_compact_name(_preferred_brand_token(b))
    same_brand = bool(brand_a and brand_b and brand_a == brand_b)
    overlap = 0.0
    if ta and tb:
        overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    seq = SequenceMatcher(None, " ".join(sorted(ta))[:300], " ".join(sorted(tb))[:300]).ratio() if ta and tb else 0.0
    raw_seq = SequenceMatcher(None, clean_a[:260], clean_b[:260]).ratio()
    score = (0.58 * overlap) + (0.24 * seq) + (0.18 * raw_seq)

    # Легкий буст за вложенность нормализованных строк.
    ac = _normalize_compact_name(clean_a)
    bc = _normalize_compact_name(clean_b)
    if ac and bc and (ac in bc or bc in ac):
        score += 0.08
    if same_brand:
        score += 0.05
    if len(important_hits) >= 2:
        score += 0.12
        if same_brand:
            score += 0.08
    if len(important_hits) >= 3:
        score += 0.05
    if local_capacity and onl_capacity:
        if local_capacity & onl_capacity:
            score += 0.10
        else:
            score -= 0.14
    if local_colors and onl_colors and (local_colors & onl_colors):
        score += 0.03
    if local_models and onl_models and not model_intersection:
        score -= 0.22
    if local_paren_models and onl_models and not (local_paren_models & onl_models):
        score -= 0.10

    score = round(min(1.0, max(0.0, score)), 3)

    # Если у нашего товара есть TGPC-код, а у кандидата нет — снижаем потолок.
    # Такой кандидат может быть общей страницей серии, а не конкретной конфигурацией.
    if local_tgpc_code and not onl_tgpc_code:
        score = round(min(score, 0.72), 3)

    ok = score >= 0.64 or overlap >= 0.78 or raw_seq >= 0.84 or (same_brand and len(important_hits) >= 2 and score >= 0.72)
    reason = "tokens"
    if same_brand and len(important_hits) >= 2:
        reason = "brand_model_tokens"
    return {"score": float(score), "match": bool(ok), "reason": reason}


def _harden_base_verify_result(oid, local_name, verify_result):
    """
    Усилить проверку "Проверить база":
    если ID существует в каталоге, но название явно не совпадает,
    понижаем статус до unverified/mismatch.
    """
    result = dict(verify_result or {})
    status = str(result.get("status", "")).strip().lower()
    if status != "match":
        return result

    catalog_name = str(result.get("catalog_name", "")).strip()
    if not catalog_name:
        return result

    cmp = calc_name_match(local_name, catalog_name)
    cmp_score = float(cmp.get("score", 0.0) or 0.0)
    art_local = _article_like_tokens(local_name)
    art_catalog = _article_like_tokens(catalog_name)
    article_intersection = bool(art_local and art_catalog and (art_local & art_catalog))

    # Жесткая защита: если артикулами конфликтуют (оба есть, но пересечения нет), это mismatch.
    if art_local and art_catalog and not article_intersection:
        guessed = lookup_catalog_match_details(local_name)
        result.update({
            "status": "mismatch",
            "score": round(min(cmp_score, 0.49), 3),
            "catalog_id": str((guessed or {}).get("id", "")).strip() or str(result.get("catalog_id", "")).strip(),
            "catalog_name": str((guessed or {}).get("model", "")).strip() or catalog_name,
            "url": str((guessed or {}).get("url", "")).strip() or str(result.get("url", "")).strip(),
        })
        return result

    if article_intersection or cmp_score >= 0.62:
        result["score"] = max(float(result.get("score", 0.0) or 0.0), round(cmp_score, 3))
        return result

    if cmp_score >= 0.48:
        result.update({"status": "unverified", "score": round(cmp_score, 3)})
        return result

    guessed = lookup_catalog_match_details(local_name)
    result.update({
        "status": "mismatch",
        "score": round(cmp_score, 3),
        "catalog_id": str((guessed or {}).get("id", "")).strip() or str(result.get("catalog_id", "")).strip(),
        "catalog_name": str((guessed or {}).get("model", "")).strip() or catalog_name,
        "url": str((guessed or {}).get("url", "")).strip() or str(result.get("url", "")).strip(),
    })
    return result


def _openai_autosort_predict_category(product_name, categories, local_hint=""):
    """
    AI-предложение категории для спорных кейсов автосортировки.
    Возвращает (category, confidence, reason) или ("", 0.0, reason).
    """
    if not OPENAI_API_KEY:
        return "", 0.0, "no_api_key"

    name = str(product_name or "").strip()
    valid_categories = [str(c).strip() for c in (categories or []) if str(c).strip()]
    if not name or not valid_categories:
        return "", 0.0, "bad_input"

    cache_key = f"{name.lower()}|{'|'.join(sorted(valid_categories))}"[:1500]
    with AI_CATEGORY_CACHE_LOCK:
        cached = AI_CATEGORY_CACHE.get(cache_key)
    if isinstance(cached, dict):
        return (
            str(cached.get("category", "")).strip(),
            float(cached.get("confidence", 0.0) or 0.0),
            str(cached.get("reason", "cache")).strip() or "cache",
        )

    system_prompt = (
        "You are a strict product categorization assistant for IT goods. "
        "Pick ONLY one category from the provided list. "
        "If uncertain, return empty category with low confidence. "
        "Respond as compact JSON only."
    )
    user_prompt = {
        "task": "categorize_product",
        "product_name": name,
        "allowed_categories": valid_categories,
        "local_hint": str(local_hint or "").strip(),
        "output_format": {
            "category": "string from allowed_categories or empty",
            "confidence": "number 0..1",
            "reason": "short string",
        },
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_AUTOSORT_MODEL,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
            },
            timeout=OPENAI_AUTOSORT_TIMEOUT_SEC,
        )
        if not resp.ok:
            return "", 0.0, f"http_{resp.status_code}"
        payload = resp.json() or {}
        choices = payload.get("choices") or []
        if not choices:
            return "", 0.0, "no_choices"
        content = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
        if not content:
            return "", 0.0, "empty_content"
        parsed = json.loads(content)
        category = str((parsed or {}).get("category", "")).strip()
        confidence = float((parsed or {}).get("confidence", 0.0) or 0.0)
        reason = str((parsed or {}).get("reason", "ai")).strip() or "ai"

        if category not in valid_categories:
            category = ""
            confidence = 0.0
            reason = "category_out_of_allowed"
        confidence = max(0.0, min(1.0, confidence))

        to_cache = {"category": category, "confidence": confidence, "reason": reason}
        with AI_CATEGORY_CACHE_LOCK:
            AI_CATEGORY_CACHE[cache_key] = to_cache
            if len(AI_CATEGORY_CACHE) > 2500:
                # Детеминированная чистка хвоста кэша.
                for k in list(AI_CATEGORY_CACHE.keys())[:400]:
                    AI_CATEGORY_CACHE.pop(k, None)

        return category, confidence, reason
    except Exception:
        return "", 0.0, "exception"


def normalize_onliner_id(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _count_rows_without_onliner_id(df):
    if df is None or getattr(df, "empty", False):
        return 0
    if "OnlinerID" not in df.columns:
        return len(df)
    return sum(1 for _, row in df.iterrows() if not normalize_onliner_id(row.get("OnlinerID", "")))


def _count_rows_with_duplicate_onliner_id(df):
    if df is None or getattr(df, "empty", False):
        return 0
    if "OnlinerID" not in df.columns:
        return 0
    counts = {}
    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        counts[oid] = counts.get(oid, 0) + 1
    duplicate_ids = {oid for oid, cnt in counts.items() if cnt > 1}
    if not duplicate_ids:
        return 0
    return sum(1 for _, row in df.iterrows() if normalize_onliner_id(row.get("OnlinerID", "")) in duplicate_ids)


def reconcile_ids_from_catalog(df):
    """
    Принудительно сверить OnlinerID по All_Catalog.
    Если по названию найден однозначный ID и он отличается от текущего — исправить.
    """
    if "OnlinerID" not in df.columns:
        return 0
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    # В pandas string-dtype прямое присваивание числам/float может падать.
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    corrected = 0
    for i, row in df.iterrows():
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        catalog_id, catalog_url = lookup_id_from_catalog_sheet(name)
        if not catalog_id:
            continue
        current_id = normalize_onliner_id(row.get("OnlinerID", ""))
        if current_id != str(catalog_id):
            df.at[i, "OnlinerID"] = str(catalog_id)
            if catalog_url:
                df.at[i, "Ссылка"] = catalog_url
            corrected += 1
        elif catalog_url and not str(row.get("Ссылка", "")).strip():
            df.at[i, "Ссылка"] = catalog_url
    return corrected


def enforce_catalog_consistency(df, session_dir=None):
    """
    Жесткая сверка с All_Catalog:
    - если найден однозначный CatalogID, он считается эталоном;
    - если текущий OnlinerID отличается — исправляем;
    - если есть артикул, но каталог не дал соответствие — ID очищаем (безопасный режим).
    Дополнительно пишет отчет по спорным строкам.
    """
    if "OnlinerID" not in df.columns:
        return {
            "checked": 0,
            "set_from_catalog": 0,
            "corrected_conflicts": 0,
            "cleared_unverified": 0,
            "report_rows": 0,
        }

    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")

    checked = 0
    set_from_catalog = 0
    corrected_conflicts = 0
    cleared_unverified = 0
    report_rows = []

    for i, row in df.iterrows():
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        checked += 1
        current_id = normalize_onliner_id(row.get("OnlinerID", ""))
        article = get_article_from_name(name)
        catalog_id, catalog_url = lookup_id_from_catalog_sheet(name)

        if catalog_id:
            catalog_id = str(catalog_id).strip()
            if not current_id:
                df.at[i, "OnlinerID"] = catalog_id
                set_from_catalog += 1
            elif current_id != catalog_id:
                report_rows.append({
                    "row": int(i) + 2,
                    "supplier": str(row.get("Поставщик", "")).strip(),
                    "name": name,
                    "article": article,
                    "current_id": current_id,
                    "catalog_id": catalog_id,
                    "action": "corrected_to_catalog",
                })
                df.at[i, "OnlinerID"] = catalog_id
                corrected_conflicts += 1
            if catalog_url:
                df.at[i, "Ссылка"] = str(catalog_url).strip()
            continue

        # Нет однозначного соответствия в каталоге.
        # Безопасный режим: если у товара есть артикул, но каталог не подтверждает ID —
        # снимаем ID, чтобы не отправить неверную позицию в магазин.
        if article and current_id:
            report_rows.append({
                "row": int(i) + 2,
                "supplier": str(row.get("Поставщик", "")).strip(),
                "name": name,
                "article": article,
                "current_id": current_id,
                "catalog_id": "",
                "action": "cleared_unverified_no_catalog_match",
            })
            df.at[i, "OnlinerID"] = ""
            df.at[i, "Ссылка"] = ""
            cleared_unverified += 1

    if session_dir:
        session_dir = Path(session_dir)
        try:
            report_df = pd.DataFrame(report_rows)
            report_path = session_dir / "id_quality_report.csv"
            report_df.to_csv(report_path, index=False, encoding="utf-8-sig")
            summary = {
                "checked": checked,
                "set_from_catalog": set_from_catalog,
                "corrected_conflicts": corrected_conflicts,
                "cleared_unverified": cleared_unverified,
                "report_rows": len(report_rows),
                "report_file": str(report_path),
            }
            with open(session_dir / "id_quality_report.json", "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Не удалось сохранить ID quality report: {e}")

    return {
        "checked": checked,
        "set_from_catalog": set_from_catalog,
        "corrected_conflicts": corrected_conflicts,
        "cleared_unverified": cleared_unverified,
        "report_rows": len(report_rows),
    }


def _normalize_name_key(name):
    text = str(name or "").strip().lower()
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    # No truncation: avoid collisions between long similar names.
    return text


def build_item_category_keys(row):
    """Стабильные ключи для категорий: только имя (+поставщик), без oid/art."""
    keys = []
    name = str(row.get("Название", "")).strip()
    supplier = str(row.get("Поставщик", "")).strip().lower()
    name_key = _normalize_name_key(name)
    if supplier and name_key:
        keys.append(f"sname:{supplier}:{name_key}")
    if name_key:
        keys.append(f"name:{name_key}")
    # unique keep order
    seen = set()
    out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def build_item_category_key(row):
    keys = build_item_category_keys(row)
    return keys[0] if keys else ""


def infer_category(name):
    """Определить укрупненную категорию из названия товара."""
    text = str(name or "").strip().lower()
    if not text:
        return "Без категории"

    norm = re.sub(r"[^a-zа-я0-9\+\s\-]", " ", text)
    norm = re.sub(r"\s+", " ", norm).strip()

    # Корпуса с формулировкой "без БП" не должны попадать в "Блок питания".
    has_case_words = bool(re.search(r"\bкорпус\b|\bcase\b|midi[\s\-]?tower|mini[\s\-]?tower", norm))
    no_psu_hint = bool(re.search(r"\bбез\s+бп\b|\bбез\s+блока\s+питания\b|\bno\s*psu\b|\bwithout\s+psu\b", norm))
    if has_case_words:
        return "Корпус"

    # Явный приоритет для БП, чтобы бренды типа PcCooler не уводили в "Кулер".
    if re.search(r"\bбп\b|блок питания|power supply|\bpsu\b", norm) and not no_psu_hint:
        return "Блок питания"

    category_rules = [
        # 1. Системный блок / ПЭВМ — до Процессора и Матплаты
        ("Системный блок", [r"системный блок", r"\bпэвм\b", r"\btgpc\b",
                            r"iven\s+(?:office|home|pro|ultra)"]),
        # 2. Сумки/чехлы/аксессуары — до Ноутбука
        ("Аксессуары", [r"\bсумк", r"чехол для ноутбука", r"чехол для планшета",
                        r"laptop bag", r"notebook bag", r"laptop case", r"\bшасси\b",
                        r"подставка для ноутбука"]),
        # 3. Оперативная память — до Ноутбука
        #    (иначе "Оперативная память для ноутбука" -> Ноутбук)
        ("Оперативная память", [r"\bddr[345]\b", r"оперативн", r"\bram\b",
                                r"so[\s\-]?dimm", r"\bdimm\b"]),
        # 4. Охлаждение — до Ноутбука
        #    (иначе "Охлаждение для ноутбука" -> Ноутбук)
        ("Охлаждение", [r"жидкостн", r"\baio\b", r"water[\s\-]?cool",
                        r"система\s+водяного\s+охлаждения", r"водяного\s+охлаждения",
                        r"охлажд", r"термопаст", r"термопроклад",
                        r"водян", r"сжо", r"радиатор", r"вентилятор"]),
        # 5. Ноутбук — до Видеокарты/SSD,
        #    но (?<!для ) — чтобы "SSD для ноутбука" / "Память для ноутбука" НЕ попали сюда
        ("Ноутбук", [r"(?<!для )ноутбук", r"\blaptop\b", r"\bnotebook\b"]),
        # 6. Кулер — до Процессора (иначе «Кулер для процессора …» уходит в CPU из-за «процессора»)
        ("Кулер", [r"\bкулер\b", r"cooler"]),
        # 7. Процессор
        ("Процессор", [r"(?<!для\s)процессор", r"\bcpu\b", r"\bintel core\b", r"\bryzen\b"]),
        # 8. Материнская плата
        ("Материнская плата", [r"материн", r"\bmotherboard\b", r"\bmb\b",
                               r"\bb[34567]\d{2}m?\b", r"\bh[456]\d{2}m?\b",
                               r"\bz[67]\d{2}\b", r"\bx[45667]\d{2}\b",
                               r"\ba[3567]\d{2}\b"]),
        # 9. SSD / HDD
        ("SSD", [r"\bssd\b", r"nvme", r"m\.?2", r"твердотельн"]),
        ("Жесткий диск", [r"\bhdd\b", r"жестк", r"винчестер"]),
        # 10. Видеокарта
        ("Видеокарта", [r"видеокарт", r"\bgpu\b", r"geforce", r"radeon",
                        r"\brtx\b", r"\bgtx\b", r"\brx\s?\d{3,4}\b"]),
        # 11. Корпус / БП / Монитор
        ("Корпус", [r"\bкорпус\b", r"midi[\s\-]?tower", r"mini[\s\-]?tower",
                    r"full[\s\-]?tower"]),
        ("Блок питания", [r"\bбп\b", r"блок питания", r"power supply", r"\bpsu\b"]),
        ("Монитор", [r"монитор", r"display"]),
        ("Принтер и МФУ", [r"\bпринтер\b", r"\bпринтеры\b", r"\bмфу\b", r"\bmfp\b"]),
        # 12. Коврики — до Мыши
        #    (иначе "Коврик для мыши" -> Мышь из-за слова "мыши")
        ("Аксессуары", [r"коврик", r"mouse[\s\-]?pad", r"mousepad"]),
        # 13. Периферия
        ("Клавиатура", [r"клавиатур"]),
        ("Мышь", [r"\bмышь\b", r"\bмыши\b", r"\bmouse\b",
                  r"игровая мышь", r"беспроводная мышь"]),
        ("Наушники", [r"наушник", r"гарнитур"]),
        ("Акустика", [r"колонк", r"акустик", r"soundbar"]),
        # 14. Сеть / периферия
        ("Сеть", [r"роутер", r"маршрутизатор", r"коммутатор",
                  r"точка доступа", r"wifi", r"wi[\s\-]fi"]),
        ("Накопители USB", [r"\busb\b", r"flash", r"флеш", r"накопител"]),
        ("Кабели и переходники", [r"кабель", r"переходник", r"адаптер",
                                  r"патч[\s\-]?корд"]),
    ]

    for category_name, patterns in category_rules:
        for pattern in patterns:
            if re.search(pattern, norm):
                return category_name

    tokens = re.findall(r"[a-zа-я0-9\+\-]+", norm)
    if not tokens:
        return "Без категории"
    return tokens[0].upper()


def get_effective_category(row, overrides=None):
    if overrides is None:
        overrides = load_category_overrides()
    for key in build_item_category_keys(row):
        manual = str(overrides.get(key, "")).strip()
        if manual:
            return manual
    return infer_category(row.get("Название", ""))


def row_category(row, overrides=None):
    existing = str(row.get("Категория", "")).strip()
    if existing:
        return existing
    return get_effective_category(row, overrides)


def normalize_catalog_category_name(raw_name, available_categories=None):
    """
    Нормализация категории из All_Catalog (колонка A) к внутренним именам.
    """
    text = str(raw_name or "").strip()
    if not text:
        return ""
    available_categories = set(available_categories or [])
    low_to_real = {str(c).strip().lower(): str(c).strip() for c in available_categories if str(c).strip()}
    direct = low_to_real.get(text.lower())
    if direct:
        return direct

    aliases = {
        "процессоры": "Процессор",
        "процессор": "Процессор",
        "cpu": "Процессор",
        "кулеры": "Кулер",
        "кулер": "Кулер",
        "охлаждение": "Охлаждение",
        "сжо": "Охлаждение",
        "материнские платы": "Материнская плата",
        "материнская плата": "Материнская плата",
        "mb": "Материнская плата",
        "оперативная память": "Оперативная память",
        "ram": "Оперативная память",
        "ssd": "SSD",
        "жесткие диски": "Жесткий диск",
        "жесткий диск": "Жесткий диск",
        "hdd": "Жесткий диск",
        "видеокарты": "Видеокарта",
        "видеокарта": "Видеокарта",
        "gpu": "Видеокарта",
        "блоки питания": "Блок питания",
        "блок питания": "Блок питания",
        "бп": "Блок питания",
        "корпуса": "Корпус",
        "корпус": "Корпус",
        "мониторы": "Монитор",
        "монитор": "Монитор",
        "принтеры и мфу": "Принтер и МФУ",
        "принтеры": "Принтер и МФУ",
        "принтер": "Принтер и МФУ",
        "мфу": "Принтер и МФУ",
        "ноутбуки": "Ноутбук",
        "ноутбук": "Ноутбук",
        "системные блоки": "Системный блок",
        "системный блок": "Системный блок",
    }
    alias = aliases.get(text.lower(), "")
    if alias:
        if alias.lower() in low_to_real:
            return low_to_real.get(alias.lower(), alias)
        return alias

    inferred = infer_category(text)
    if inferred and inferred != "Без категории":
        if inferred.lower() in low_to_real:
            return low_to_real.get(inferred.lower(), inferred)
        return inferred
    return ""


def ensure_category_column(df, overrides=None):
    if overrides is None:
        overrides = load_category_overrides()
    df = df.copy()
    df["Категория"] = df.apply(lambda row: row_category(row, overrides), axis=1)
    return df


def normalize_consolidated_columns(df):
    if df is None or df.empty:
        return df
    rename_map = {}
    for col in df.columns:
        text = str(col)
        compact = text.replace("\xa0", "").strip()
        if text == "РќР°Р·РІР°РЅРёРµ":
            rename_map[col] = "Название"
        elif text == "Р¦РµРЅР°":
            rename_map[col] = "Цена"
        elif text == "РџРѕСЃС‚Р°РІС‰РёРє":
            rename_map[col] = "Поставщик"
        elif text == "Р“Р°СЂР°РЅС‚РёСЏ":
            rename_map[col] = "Гарантия"
        elif compact in {"РРЦ", "Р Р Р¦"} or text == "Р\xa0Р\xa0Р¦":
            rename_map[col] = "РРЦ"
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def round_price_to_90(value):
    """
    Округлить цену до ближайшего десятка.
    Последняя цифра 1-4 округляется вниз, 5-9 — вверх.
    Примеры: 302 -> 300, 441 -> 440, 583 -> 580, 1311 -> 1310
    """
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return np.nan
    v = float(v)
    if v <= 0:
        return 0.0
    whole = int(math.floor(v))
    last_digit = whole % 10
    if last_digit <= 4:
        rounded = whole - last_digit
    else:
        rounded = whole + (10 - last_digit)
    return float(rounded)


def load_visibility_map(session_dir):
    _ = session_dir  # compatibility: visibility now global, not per-session
    if not CATEGORY_VISIBILITY_FILE.exists():
        return {}
    try:
        with open(CATEGORY_VISIBILITY_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_visibility_map(session_dir, visibility_map):
    _ = session_dir  # compatibility: visibility now global, not per-session
    with open(CATEGORY_VISIBILITY_FILE, "w", encoding="utf-8") as f:
        json.dump(visibility_map, f, ensure_ascii=False, indent=2)


def apply_saved_markups_to_df(df):
    if df.empty:
        return df
    markups = load_category_markups()
    if not markups:
        return df
    if "РРЦ" not in df.columns:
        df["РРЦ"] = ""
    if "Цена без скидки" not in df.columns:
        df["Цена без скидки"] = ""
    # Allow writing numeric RRC values regardless of source column dtype (str/string).
    df["РРЦ"] = df["РРЦ"].astype("object")
    df["Цена без скидки"] = df["Цена без скидки"].astype("object")
    overrides = load_category_overrides()
    for i, row in df.iterrows():
        category = row_category(row, overrides)
        if category not in markups:
            continue
        base_price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        if pd.isna(base_price):
            continue
        cfg = get_category_markup_config(markups, category)
        percent = cfg["percent"]
        threshold = cfg.get("threshold", 0.0)
        min_profit = cfg.get("min_profit", 0.0)
        calc_base = float(base_price)
        if cfg["base_mode"] in {"onliner_min", "onliner_avg", "onliner_max"}:
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            stats = get_onliner_market_stats_from_cache_only(oid) if oid else {}
            market_price = None
            if cfg["base_mode"] == "onliner_min":
                market_price = stats.get("min")
            elif cfg["base_mode"] == "onliner_avg":
                market_price = stats.get("avg")
            else:
                market_price = stats.get("max")
            if market_price is not None:
                calc_base = float(market_price)
        rrc, no_discount_price = calc_rrc_and_no_discount(
            calc_base,
            percent,
            threshold=threshold,
            min_profit=min_profit,
            no_discount_percent=cfg.get("no_discount_percent", 0.0),
        )
        df.at[i, "РРЦ"] = rrc
        df.at[i, "Цена без скидки"] = no_discount_price
    return df


def apply_visibility_filter(df, session_dir):
    if df.empty or "Поставщик" not in df.columns or "Название" not in df.columns:
        return df
    visibility_map = load_visibility_map(session_dir)
    if not visibility_map:
        return df

    overrides = load_category_overrides()
    mask = []
    for _, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip()
        category = row_category(row, overrides)
        hidden_for_supplier = set(visibility_map.get(supplier, []))
        mask.append(category not in hidden_for_supplier)
    return df[pd.Series(mask, index=df.index)].copy()


def _safe_json_value(value):
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


def _delivery_days_from_row(row):
    value = row.get("\u0414\u043d\u0435\u0439 \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0438", row.get("\u041f\u043e\u0434 \u0437\u0430\u043a\u0430\u0437", "2"))
    value = _safe_json_value(value)
    text = str(value).strip()
    if not text:
        return "2"
    match = re.search(r"(\d+)", text)
    if match:
        return match.group(1)
    return text


def write_consolidated_json(df, json_path):

    cons_data = []
    for _, row in df.iterrows():
        cons_data.append([
            _safe_json_value(row.get("OnlinerID", "")),
            _safe_json_value(row.get("Название", "")),
            _safe_json_value(row.get("Цена", 0)),
            _safe_json_value(row.get("Поставщик", "")),
            _safe_json_value(row.get("Гарантия", "")),
            _delivery_days_from_row(row),
            _safe_json_value(row.get("РРЦ", "")),
            _safe_json_value(row.get("Цена без скидки", "")),
        ])
    with open(str(json_path), "w", encoding="utf-8") as f:
        json.dump({"data": cons_data}, f, ensure_ascii=False, allow_nan=False)


_cons_df_cache = {}  # {path_str: (mtime, df)}

def read_consolidated_df(session_dir):
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    with CONSOLIDATED_IO_LOCK:
        try:
            mtime = cons_path.stat().st_mtime
        except OSError:
            mtime = None
        cached = _cons_df_cache.get(str(cons_path))
        if cached and cached[0] == mtime and mtime is not None:
            return cached[1].copy()
        df = pd.read_excel(cons_path)
        _cons_df_cache[str(cons_path)] = (mtime, df)
        return df.copy()


def write_consolidated_df(session_dir, df):
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    tmp_path = Path(session_dir) / "consolidated_price.tmp.xlsx"
    with CONSOLIDATED_IO_LOCK:
        df.to_excel(tmp_path, index=False)
        os.replace(tmp_path, cons_path)
        _cons_df_cache.pop(str(cons_path), None)  # invalidate cache


def _create_session_dir():
    session_id = str(uuid.uuid4())[:8]
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(exist_ok=True)
    return session_id, session_dir


def _finalize_processed_session(session_id, session_dir, output_path):
    global LAST_ACTIVE_SESSION_DIR
    session["session_id"] = session_id
    session["output_path"] = str(output_path)
    session["session_dir"] = str(session_dir)
    LAST_ACTIVE_SESSION_DIR = str(session_dir)


def _process_supplier_files(file_entries, session_id=None, session_dir=None):
    app_settings = load_app_settings()
    if session_id and session_dir:
        session_id = str(session_id)
        session_dir = Path(session_dir)
        session_dir.mkdir(exist_ok=True)
    else:
        session_id, session_dir = _create_session_dir()
    all_frames = []
    supplier_names = set()

    for entry in file_entries:
        filepath = Path(entry.get("filepath", ""))
        if not filepath.exists():
            continue
        display_name = str(entry.get("display_name", filepath.name) or filepath.name)
        supplier_name = str(entry.get("supplier_name", "") or "").strip() or "Unknown"
        try:
            df = parse_generic_excel(filepath, supplier_name)
            if not df.empty:
                all_frames.append(df)
                supplier_names.add(supplier_name)
                print(f"Загружен {display_name}: {len(df)} товаров, поставщик: {supplier_name}")
        except Exception as e:
            print(f"Ошибка парсинга {display_name}: {e}")
            import traceback
            traceback.print_exc()

    if not all_frames:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise ValueError("Не удалось обработать файлы")

    all_data = pd.concat(all_frames, ignore_index=True)
    print(f"Всего загружено: {len(all_data)} товаров")
    print(f"Колонки: {list(all_data.columns)}")
    if "onliner_id" in all_data.columns:
        print(f"С OnlinerID: {all_data['onliner_id'].notna().sum()}")

    consolidated_df = consolidate_simple(all_data)
    consolidated_df = normalize_consolidated_columns(consolidated_df)
    consolidated_df = ensure_category_column(consolidated_df)
    consolidated_df = apply_saved_markups_to_df(consolidated_df)

    manual_bindings = load_manual_id_bindings()
    id_cache, id_cache_changed = _sanitize_id_cache(load_id_cache())
    if id_cache_changed:
        save_id_cache(id_cache)
    id_fanout = build_id_fanout_map(id_cache)
    if "Ссылка" not in consolidated_df.columns:
        consolidated_df["Ссылка"] = ""
    for i, row in consolidated_df.iterrows():
        name = row.get("Название", "")
        name_key = _normalize_name_key(name)
        supplier_name = str(row.get("Поставщик", "") or "").strip().upper()
        is_iven_supplier = supplier_name in {"IVEN"}
        is_ntech_supplier = supplier_name in {"N-TECH", "NTECH"}

        # manual_bindings — ручные правки пользователя — всегда имеют приоритет,
        # даже если поставщик прислал свой (возможно неверный) ID в Excel.
        if not is_iven_supplier:
            manual = manual_bindings.get(name_key) if name_key else None
            if isinstance(manual, dict):
                if bool(manual.get("blocked", False)):
                    consolidated_df.at[i, "OnlinerID"] = ""
                    consolidated_df.at[i, "Ссылка"] = ""
                    continue
                mid = normalize_onliner_id(manual.get("id", ""))
                if mid:
                    consolidated_df.at[i, "OnlinerID"] = mid
                    murl = str(manual.get("url", "")).strip()
                    if murl:
                        consolidated_df.at[i, "Ссылка"] = murl
                    continue

        # id_cache — автоматический кэш — применяем только если ID ещё нет
        if not is_iven_supplier and not is_ntech_supplier:
            oid = row.get("OnlinerID")
            if not oid or str(oid).strip() == "" or str(oid) == "nan":
                cache_key = _get_id_cache_key_for_name(name)
                if cache_key in id_cache:
                    cached = id_cache[cache_key]
                    if is_trusted_cached_id(cache_key, cached, id_fanout=id_fanout):
                        cached_id = normalize_onliner_id(cached.get("id", ""))
                        if cached_id:
                            consolidated_df.at[i, "OnlinerID"] = cached_id

    output_path = session_dir / "consolidated_price.xlsx"
    consolidated_df.to_excel(output_path, index=False)
    write_consolidated_json(consolidated_df, session_dir / "consolidated.json")

    # Пополняем локальную БД из свежего прайса (всё кроме N-Tech / TGPC)
    threading.Thread(
        target=db_populate_from_df,
        args=(consolidated_df, "price_load"),
        kwargs={"skip_suppliers": ["N-Tech", "TGPC", "N-TECH", "NTECH"]},
        daemon=True,
    ).start()

    snapshot_diff = {}
    if len(supplier_names) == 1:
        supplier_name = list(supplier_names)[0]
        snapshots = load_supplier_snapshots()
        previous_snapshot = (((snapshots or {}).get("suppliers") or {}).get(supplier_name) or {})
        current_snapshot = build_supplier_snapshot(consolidated_df, supplier_name)
        if previous_snapshot:
            snapshot_diff = compare_supplier_snapshot(previous_snapshot, current_snapshot)
            snapshot_diff["supplier"] = supplier_name
        save_session_supplier_diff(session_dir, snapshot_diff)
        snapshots.setdefault("suppliers", {})[supplier_name] = current_snapshot
        save_supplier_snapshots(snapshots)
    else:
        save_session_supplier_diff(session_dir, {})

    stats = {
        "total": len(all_data),
        "suppliers": len(supplier_names),
        "consolidated": len(consolidated_df),
        "matched": int(all_data["onliner_id"].notna().sum()) if "onliner_id" in all_data.columns else 0,
        "without_id": _count_rows_without_onliner_id(consolidated_df),
        "duplicate_id_rows": _count_rows_with_duplicate_onliner_id(consolidated_df),
        "show_checks_block": _coerce_bool((((app_settings or {}).get("ui") or {}).get("show_checks_block", True)), default=True),
        "snapshot_diff": snapshot_diff,
    }

    try:
        _maybe_cleanup_old_uploads(exclude_dirs=[session_dir, LAST_ACTIVE_SESSION_DIR], min_interval_sec=60)
    except Exception:
        pass

    return {
        "session_id": session_id,
        "session_dir": session_dir,
        "output_path": output_path,
        "stats": stats,
    }


@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return redirect(url_for("index", error="Не загружено ни одного файла"))

    session_id, session_dir = _create_session_dir()
    supplier_mapping = {}
    for key in request.form:
        if key.startswith("supplier_"):
            fname = key.replace("supplier_", "")
            supplier_mapping[fname] = request.form[key].strip()

    file_entries = []
    for file in files:
        if not file.filename:
            continue
        fname_enc = file.filename
        from urllib.parse import unquote
        for enc_fname, sup_name in supplier_mapping.items():
            if unquote(enc_fname) == fname_enc or enc_fname == fname_enc:
                supplier_name = sup_name
                break
        else:
            supplier_name = "Unknown"

        if not supplier_name:
            supplier_name = "Unknown"

        # Сохраняем с UUID-именем + оригинальным расширением
        # (secure_filename убивает кириллицу и может удалить расширение)
        _orig_ext = Path(file.filename).suffix.lower()
        if _orig_ext not in {".xls", ".xlsx", ".xlsb", ".xlsm", ".csv"}:
            _orig_ext = ".xlsx"
        safe_fname = str(uuid.uuid4())[:8] + _orig_ext
        filepath = session_dir / safe_fname
        file.save(str(filepath))

        file_entries.append({
            "filepath": filepath,
            "display_name": file.filename,
            "supplier_name": supplier_name,
        })

    try:
        result = _process_supplier_files(file_entries, session_id=session_id, session_dir=session_dir)
    except Exception as _upload_err:
        import traceback as _tb_mod
        _tb = _tb_mod.format_exc()
        print("[UPLOAD ERROR] " + str(_upload_err) + "\n" + _tb, flush=True)
        try:
            import datetime
            with open("upload_error.log", "a", encoding="utf-8") as _ef:
                _ef.write("--- " + str(datetime.datetime.now()) + " ---\n" + str(_upload_err) + "\n" + _tb + "\n")
        except Exception:
            pass
        return redirect(url_for("index", error="Не удалось обработать файлы: " + str(_upload_err)[:120]))

    _finalize_processed_session(result["session_id"], result["session_dir"], result["output_path"])
    return render_template("result.html", stats=result["stats"])


@app.route("/api/consolidated")
def api_consolidated():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"data": []})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"data": []})
    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)
    cons_data = []
    for i, row in df.iterrows():
        cons_data.append([
            _safe_json_value(row.get("OnlinerID", "")),
            _safe_json_value(row.get("Название", "")),
            _safe_json_value(row.get("Цена", 0)),
            _safe_json_value(row.get("Поставщик", "")),
            _safe_json_value(row.get("Гарантия", "")),
            _delivery_days_from_row(row),
            _safe_json_value(row.get("РРЦ", "")),
            _safe_json_value(row.get("Цена без скидки", "")),
            int(i),
            _safe_json_value(row_category(row)),
        ])
    response = jsonify({"data": cons_data})
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/stats")
def api_stats():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"without_id": 0, "duplicate_id_rows": 0})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"without_id": 0, "duplicate_id_rows": 0})
    df = read_consolidated_df(session_dir)
    return jsonify({
        "without_id": _count_rows_without_onliner_id(df),
        "duplicate_id_rows": _count_rows_with_duplicate_onliner_id(df),
    })


@app.route("/api/manual-id-confirm-batch", methods=["POST"])
def api_manual_id_confirm_batch():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400

    payload = request.get_json(silent=True) or {}
    source = str(payload.get("source", "ui")).strip() or "ui"
    items_raw = payload.get("items", [])
    if not isinstance(items_raw, list) or not items_raw:
        return jsonify({"status": "error", "message": "Нет выбранных строк"}), 400

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return jsonify({"status": "error", "message": "В прайсе нет колонки OnlinerID"}), 400
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    df["Ссылка"] = df["Ссылка"].astype("object")

    id_cache, id_cache_changed = _sanitize_id_cache(load_id_cache())
    manual_bindings = load_manual_id_bindings()
    # Strict anti-duplicate mode: one OnlinerID cannot be assigned to different product names.
    max_distinct_name_keys_per_id = 1
    id_to_name_keys = {}
    if "Название" in df.columns:
        for _, row in df.iterrows():
            existing_oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not existing_oid:
                continue
            existing_name_key = _normalize_name_key(row.get("Название", ""))
            if not existing_name_key:
                continue
            bucket = id_to_name_keys.setdefault(existing_oid, set())
            bucket.add(existing_name_key)
    updated = 0
    blocked_duplicates = []
    touched_queue_keys = set()
    journal_entry = {
        "ts": int(time.time()),
        "action": "manual_id_confirm_batch",
        "session_dir": str(session_dir),
        "source": source,
        "changes": [],
    }

    for raw in items_raw[:1000]:
        if not isinstance(raw, dict):
            continue
        item_name = str(raw.get("name", "")).strip()
        oid = normalize_onliner_id(raw.get("onliner_id", ""))
        final_url = str(raw.get("url", "")).strip()
        row_idx = raw.get("row_idx", None)
        allow_duplicate_id = _coerce_bool(raw.get("allow_duplicate_id"), False)
        if not item_name or not oid:
            continue

        target_name_key = _normalize_name_key(item_name)
        existing_name_keys = set(id_to_name_keys.get(oid, set()))
        if target_name_key:
            existing_name_keys.discard(target_name_key)
        if len(existing_name_keys) >= max_distinct_name_keys_per_id and not allow_duplicate_id:
            blocked_duplicates.append({
                "name": item_name,
                "onliner_id": oid,
                "known_items_with_same_id": int(len(existing_name_keys) + (1 if target_name_key else 0)),
            })
            continue

        if not final_url:
            try:
                info = fetch_onliner_product_info(
                    oid,
                    force_refresh=False,
                    use_cache_on_error=True,
                    product_name_hint=item_name,
                )
                final_url = str((info or {}).get("url", "")).strip()
            except Exception:
                final_url = ""

        # Manual confirmation should be exact-name only.
        # Do not push manual decisions into broad id_cache keys,
        # otherwise similar models may receive phantom duplicate IDs.
        item_cache_key = ""

        if target_name_key:
            manual_bindings[target_name_key] = {"id": oid, "url": final_url}
            touched_queue_keys.add(target_name_key)
            id_to_name_keys.setdefault(oid, set()).add(target_name_key)

        try:
            if row_idx is not None and str(row_idx).strip() != "":
                row_idx_int = int(row_idx)
                if row_idx_int in df.index:
                    old_id = normalize_onliner_id(df.at[row_idx_int, "OnlinerID"])
                    old_url = str(df.at[row_idx_int, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                    df.at[row_idx_int, "OnlinerID"] = oid
                    if final_url:
                        df.at[row_idx_int, "Ссылка"] = final_url
                    journal_entry["changes"].append({
                        "row_idx": int(row_idx_int),
                        "name": item_name,
                        "old_onliner_id": old_id,
                        "old_url": old_url,
                        "new_onliner_id": oid,
                        "new_url": final_url,
                    })
                    updated += 1
        except Exception:
            continue

    if touched_queue_keys:
        review_queue = load_review_queue()
        queue_changed = False
        for name_key in list(touched_queue_keys):
            if name_key in review_queue:
                review_queue.pop(name_key, None)
                queue_changed = True
        if queue_changed:
            save_review_queue(review_queue)
    if id_cache_changed:
        save_id_cache(id_cache)
    save_manual_id_bindings(manual_bindings)
    if journal_entry["changes"]:
        append_id_change_journal(journal_entry)
    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    if blocked_duplicates and updated <= 0:
        sample = blocked_duplicates[0]
        return jsonify({
            "status": "error",
            "code": "duplicate_id_protection",
            "updated": 0,
            "blocked": blocked_duplicates[:20],
            "message": (
                f"Защита от дублей: ID {sample.get('onliner_id', '')} уже связан с несколькими товарами. "
                "Сохранение остановлено."
            ),
        }), 409
    if blocked_duplicates:
        return jsonify({
            "status": "ok",
            "updated": updated,
            "blocked": blocked_duplicates[:20],
            "message": (
                f"Сохранено: {updated}. Защита от дублей отклонила ещё {len(blocked_duplicates)} "
                "назначений с повторяющимися OnlinerID."
            ),
        })
    return jsonify({"status": "ok", "updated": updated})


@app.route("/api/manual-id-clear", methods=["POST"])
def api_manual_id_clear():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400

    payload = request.get_json(silent=True) or {}
    source = str(payload.get("source", "ui")).strip() or "ui"
    item = payload.get("item", {})
    if not isinstance(item, dict):
        return jsonify({"status": "error", "message": "Некорректный payload"}), 400
    item_name = str(item.get("name", "")).strip()
    row_idx = item.get("row_idx", None)
    if not item_name or row_idx is None or str(row_idx).strip() == "":
        return jsonify({"status": "error", "message": "Нужно имя товара и row_idx"}), 400

    try:
        row_idx_int = int(row_idx)
    except Exception:
        return jsonify({"status": "error", "message": "Некорректный row_idx"}), 400

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return jsonify({"status": "error", "message": "В прайсе нет колонки OnlinerID"}), 400
    if row_idx_int not in df.index:
        return jsonify({"status": "error", "message": "Строка не найдена"}), 404
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    df["Ссылка"] = df["Ссылка"].astype("object")

    old_id = normalize_onliner_id(df.at[row_idx_int, "OnlinerID"])
    old_url = str(df.at[row_idx_int, "Ссылка"]).strip()
    df.at[row_idx_int, "OnlinerID"] = ""
    df.at[row_idx_int, "Ссылка"] = ""

    id_cache, _ = _sanitize_id_cache(load_id_cache())
    cache_key = _get_id_cache_key_for_name(item_name)
    if cache_key and cache_key in id_cache:
        id_cache.pop(cache_key, None)
    save_id_cache(id_cache)

    manual_bindings = load_manual_id_bindings()
    name_key = _normalize_name_key(item_name)
    if name_key:
        # blocked=True prevents future auto-restore from stale cache for this name.
        manual_bindings[name_key] = {"id": "", "url": "", "blocked": True}
        save_manual_id_bindings(manual_bindings)
        review_queue = load_review_queue()
        if name_key in review_queue:
            review_queue.pop(name_key, None)
            save_review_queue(review_queue)

    append_id_change_journal({
        "ts": int(time.time()),
        "action": "manual_id_clear",
        "session_dir": str(session_dir),
        "source": source,
        "changes": [{
            "row_idx": int(row_idx_int),
            "name": item_name,
            "old_onliner_id": old_id,
            "old_url": old_url,
            "new_onliner_id": "",
            "new_url": "",
        }],
    })

    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    return jsonify({"status": "ok", "cleared": 1})


def build_iven_id_index(df):
    """Строит индекс name_key → {id, name, url} из ВСЕХ строк прайса, у которых есть OnlinerID.
    Используется как источник ID для N-Tech и других поставщиков без ID.
    Исключает N-Tech и TGPC (они сами являются целью поиска ID).
    """
    index = {}
    if df is None or df.empty:
        return index
    # Исключаем поставщиков, которые сами являются целью подбора
    SKIP_SUPPLIERS = {"N-TECH", "NTECH", "TGPC"}
    supplier_col = "Поставщик" if "Поставщик" in df.columns else None
    total_added = 0
    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        name = str(row.get("Название", "")).strip()
        if not name:
            continue
        if supplier_col:
            sup = str(row.get(supplier_col, "")).strip().upper()
            if sup in SKIP_SUPPLIERS:
                continue
        url = str(row.get("Ссылка", "")).strip()
        key = _normalize_name_key(name)
        if key and key not in index:
            index[key] = {"id": oid, "name": name, "url": url}
            total_added += 1
    return index


def lookup_iven_match(product_name, iven_index, threshold=0.85):
    """Ищет лучшее совпадение для product_name в iven_index.
    Возвращает dict {id, name, url, score} или None если score < threshold.
    """
    if not product_name or not iven_index:
        return None
    best_score = 0.0
    best_rec   = None
    for key, rec in iven_index.items():
        cmp = calc_name_match(product_name, rec["name"])
        sc  = float(cmp.get("score", 0.0) or 0.0)
        if sc > best_score:
            best_score = sc
            best_rec   = rec
    if best_score >= threshold and best_rec:
        return {**best_rec, "score": round(best_score, 3)}
    return None


def _autofill_iven_bridge_worker(session_dir, ignore_manual_cache=False, prefer_b2b=False):
    """Автоподбор ID для N-Tech через локальную SQLite БД.
    Автоприменяет только точные совпадения из индекса базы (source == db_exact).
    Все остальные кандидаты отправляет на ручную модерацию.
    БД пополняется автоматически при загрузке каждого прайса (IVEN, BN, Tradex).
    """
    global autofill_iven_status
    try:
        db_st = db_stats()
        db_total = db_st.get("total_products", 0)
        print(f"[iven_bridge] БД: {db_total} товаров, {db_st.get('total_names', 0)} имён", flush=True)

        df = read_consolidated_df(session_dir)
        if df.empty:
            with AUTOFILL_IVEN_LOCK:
                autofill_iven_status.update({"running": False, "message": "Нет данных", "finished_at": int(time.time())})
            return

        if "OnlinerID" not in df.columns:
            df["OnlinerID"] = ""
        if "Ссылка" not in df.columns:
            df["Ссылка"] = ""
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        df["Ссылка"]    = df["Ссылка"].astype("object")

        # Если БД пустая — сначала заполняем из текущего прайса
        if db_total == 0:
            print("[iven_bridge] БД пустая, пополняю из текущего прайса...", flush=True)
            db_populate_from_df(df, "price_load", skip_suppliers=["N-Tech", "TGPC"])
            db_st = db_stats()
            db_total = db_st.get("total_products", 0)
            if db_total == 0:
                with AUTOFILL_IVEN_LOCK:
                    autofill_iven_status.update({
                        "running": False,
                        "message": "БД пуста. Загрузи прайс IVEN/BN чтобы заполнить базу.",
                        "finished_at": int(time.time()),
                    })
                return

        # Собираем задачи: все товары без OnlinerID, не TGPC ПК.
        # После API-очистки значение может быть NaN, поэтому опираемся только
        # на normalize_onliner_id, а не на truthy-проверки и не на поставщика.
        tasks = []
        for row_idx, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if oid:
                continue
            name = str(row.get("Название", "")).strip()
            if not name or _is_tgpc_pc_name(name):
                continue
            tasks.append((int(row_idx), name))

        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "total": len(tasks), "done": 0, "applied": 0, "skipped": 0, "percent": 0,
                "message": (
                    f"Найдено {len(tasks)} товаров без ID. БД: {db_total} позиций..."
                    + (" Режим: B2B без кеша." if prefer_b2b else "")
                ),
            })

        if not tasks:
            with AUTOFILL_IVEN_LOCK:
                autofill_iven_status.update({
                    "running": False,
                    "message": "Все товары уже имеют OnlinerID.",
                    "finished_at": int(time.time()),
                })
            return

        manual_bindings = load_manual_id_bindings()
        id_cache        = load_id_cache()
        applied = 0
        skipped = 0
        journal_changes = []
        matches_log  = []   # для отчёта в UI
        no_match_log = []

        for done_idx, (row_idx, name) in enumerate(tasks, start=1):
            pct = max(1, int(round(done_idx / len(tasks) * 100)))
            with AUTOFILL_IVEN_LOCK:
                autofill_iven_status.update({
                    "done": done_idx - 1, "applied": applied, "skipped": skipped, "percent": pct,
                    "message": f"Ищу {done_idx}/{len(tasks)}: {name[:60]}",
                })

            name_key = _normalize_name_key(name)
            if (not ignore_manual_cache) and name_key and name_key in manual_bindings:
                cached_manual = manual_bindings.get(name_key) or {}
                manual_id = normalize_onliner_id(cached_manual.get("id", ""))
                manual_url = str(cached_manual.get("url", "")).strip()
                if manual_id:
                    old_id = normalize_onliner_id(df.at[row_idx, "OnlinerID"])
                    old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                    df.at[row_idx, "OnlinerID"] = manual_id
                    df.at[row_idx, "Ссылка"] = manual_url
                    journal_changes.append({
                        "row_idx": row_idx, "name": name,
                        "old_onliner_id": old_id, "old_url": old_url,
                        "new_onliner_id": manual_id, "new_url": manual_url,
                        "matched_name": "manual_cache",
                        "reason": "db_bridge manual_cache",
                    })
                    matches_log.append({
                        "name": name,
                        "row_idx": row_idx,
                        "matched_name": "Ручная привязка из вечного кеша",
                        "score": 1.0,
                        "id": manual_id,
                        "url": manual_url,
                        "source": "manual_cache",
                    })
                    applied += 1
                    continue
                skipped += 1
                continue

            match = db_find_id_for_name(name, threshold=0.40, allow_b2b=prefer_b2b)
            top_cands = db_find_top_candidates(name, top_n=3, min_score=0.40, allow_b2b=prefer_b2b)

            if not match:
                skipped += 1
                no_match_log.append({
                    "name": name,
                    "row_idx": row_idx,
                    "candidates": top_cands,
                })
                continue

            oid = match["id"]
            url = match["url"]
            sc  = float(match["score"] or 0.0)
            match_source = str(match.get("source", "") or "").strip()
            matched_name = match.get("name", "")

            if match_source == "db_exact":
                print(f"[iven_bridge] ✓ auto exact {name[:55]} → {matched_name[:45]} | id={oid} score={sc}", flush=True)

                if name_key:
                    manual_bindings[name_key] = {"id": oid, "url": url}
                art = _get_id_cache_key_for_name(name)
                if art:
                    id_cache[art] = {"id": oid, "url": url}

                old_id  = normalize_onliner_id(df.at[row_idx, "OnlinerID"])
                old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                df.at[row_idx, "OnlinerID"] = oid
                df.at[row_idx, "Ссылка"]    = url
                journal_changes.append({
                    "row_idx": row_idx, "name": name,
                    "old_onliner_id": old_id, "old_url": old_url,
                    "new_onliner_id": oid, "new_url": url,
                    "matched_name": matched_name,
                    "reason": f"db_bridge {match_source or 'exact'} score={round(sc, 3)}",
                })
                matches_log.append({
                    "name": name,
                    "row_idx": row_idx,
                    "matched_name": matched_name,
                    "score": round(sc, 3),
                    "id": oid,
                    "url": url,
                    "source": match_source,
                })
                applied += 1
                continue

            merged_candidates = []
            seen_candidate_ids = set()

            def _push_candidate(cid, cname, curl, cscore):
                cid = normalize_onliner_id(cid)
                if not cid or cid in seen_candidate_ids:
                    return
                seen_candidate_ids.add(cid)
                merged_candidates.append({
                    "id": cid,
                    "name": str(cname or "").strip(),
                    "url": str(curl or "").strip(),
                    "score": round(float(cscore or 0.0), 3),
                })

            _push_candidate(oid, matched_name, url, sc)
            for cand in top_cands:
                _push_candidate(cand.get("id", ""), cand.get("name", ""), cand.get("url", ""), cand.get("score", 0.0))

            skipped += 1
            no_match_log.append({
                "name": name,
                "row_idx": row_idx,
                "best_score": round(sc, 3),
                "best_id": oid,
                "best_name": matched_name,
                "best_source": match_source,
                "needs_manual": True,
                "candidates": merged_candidates[:5],
            })
            print(f"[iven_bridge] ? review {name[:55]} → {matched_name[:45]} | id={oid} source={match_source} score={sc}", flush=True)

        save_manual_id_bindings(manual_bindings)
        save_id_cache(id_cache)
        if journal_changes:
            append_id_change_journal({
                "ts": int(time.time()),
                "action": "autofill_iven_bridge",
                "session_dir": str(session_dir),
                "source": "api_autofill_iven_bridge",
                "changes": journal_changes,
            })
        if applied > 0:
            write_consolidated_df(session_dir, df)
            write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        mode_suffix = " Режим: B2B без кеша." if prefer_b2b else ""
        msg = f"Готово. Автоподобрано 100%: {applied}, на ручную проверку: {len(no_match_log)}.{mode_suffix}"
        print(f"[iven_bridge] {msg}", flush=True)
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "done": len(tasks), "applied": applied, "skipped": skipped, "percent": 100,
                "message": msg,
                "finished_at": int(time.time()),
                "matches": matches_log,
                "no_match": no_match_log,
            })
    except Exception as e:
        import traceback
        print(f"[iven_bridge] ОШИБКА: {e}", flush=True)
        traceback.print_exc()
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "message": f"Ошибка IVEN-бриджа: {str(e)[:180]}",
                "finished_at": int(time.time()),
            })


def _autofill_tgpc_pc_worker(session_dir, max_items=0):
    global autofill_tgpc_pc_status
    df = read_consolidated_df(session_dir)
    report_items = []
    try:
        if df.empty:
            with AUTOFILL_TGPC_PC_LOCK:
                autofill_tgpc_pc_status.update({
                    "running": False,
                    "message": "Нет данных для обработки",
                    "finished_at": int(time.time()),
                })
            return
        if "OnlinerID" not in df.columns:
            df["OnlinerID"] = ""
        if "Ссылка" not in df.columns:
            df["Ссылка"] = ""
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        df["Ссылка"] = df["Ссылка"].astype("object")

        settings = load_app_settings()
        no_id_cfg = (settings.get("no_id_search") or {})
        limit = max(10, min(int(no_id_cfg.get("max_candidates", 80) or 80), 80))

        tasks = []
        for row_idx, row in df.iterrows():
            current_id = normalize_onliner_id(row.get("OnlinerID", ""))
            if current_id:
                continue
            name = str(row.get("Название", "")).strip()
            if not name or not _is_tgpc_pc_name(name):
                continue
            tasks.append((int(row_idx), str(name), str(row_category(row) or "").strip()))

        if max_items and len(tasks) > int(max_items):
            tasks = tasks[:int(max_items)]

        with AUTOFILL_TGPC_PC_LOCK:
            autofill_tgpc_pc_status.update({
                "total": int(len(tasks)),
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 0,
                "items": [],
                "message": f"Найдено TGPC ПЭВМ без ID: {len(tasks)}. Начинаю подбор...",
            })

        id_cache = load_id_cache()
        manual_bindings = load_manual_id_bindings()
        journal_entry = {
            "ts": int(time.time()),
            "action": "autofill_tgpc_pc_ids",
            "session_dir": str(session_dir),
            "source": "db_autofill_tgpc_pc_ids",
            "changes": [],
        }

        applied = 0
        skipped = 0
        for done_idx, (row_idx, name, category) in enumerate(tasks, start=1):
            in_progress_percent = max(1, int(round(((done_idx - 1) / len(tasks)) * 100))) if tasks else 100
            with AUTOFILL_TGPC_PC_LOCK:
                autofill_tgpc_pc_status.update({
                    "done": int(done_idx - 1),
                    "applied": int(applied),
                    "skipped": int(skipped),
                    "percent": int(in_progress_percent),
                    "message": f"Проверяю {done_idx} из {len(tasks)}: {name[:72]}",
                })
            try:
                candidates = db_search_tgpc_pc_candidates(name, limit=min(limit, 24))
            except Exception:
                skipped += 1
                candidates = []

            if candidates:
                top = candidates[0] if isinstance(candidates[0], dict) else {}
                top_id = normalize_onliner_id(top.get("id", ""))
                top_url = str(top.get("url", "")).strip()
                top_score = float(top.get("score", 0) or 0)
                second_score = 0.0
                if len(candidates) > 1 and isinstance(candidates[1], dict):
                    try:
                        second_score = float(candidates[1].get("score", 0) or 0)
                    except Exception:
                        second_score = 0.0

                confident = bool(
                    top_id and (
                        top_score >= 0.95
                        or (top_score >= 0.92 and (top_score - second_score) >= 0.05)
                    )
                )
                if confident:
                    item_cache_key = _get_id_cache_key_for_name(name)
                    if item_cache_key:
                        id_cache[item_cache_key] = {"id": top_id, "url": top_url}
                    target_name_key = _normalize_name_key(name)
                    if target_name_key:
                        manual_bindings[target_name_key] = {"id": top_id, "url": top_url}

                    old_id = normalize_onliner_id(df.at[row_idx, "OnlinerID"])
                    old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                    df.at[row_idx, "OnlinerID"] = top_id
                    if top_url:
                        df.at[row_idx, "Ссылка"] = top_url
                    journal_entry["changes"].append({
                        "row_idx": int(row_idx),
                        "name": name,
                        "old_onliner_id": old_id,
                        "old_url": old_url,
                        "new_onliner_id": top_id,
                        "new_url": top_url,
                        "score": round(top_score, 4),
                    })
                    applied += 1
                    report_items.append({
                        "row_idx": int(row_idx),
                        "name": name,
                        "status": "matched",
                        "onliner_id": top_id,
                        "onliner_name": str(top.get("name", "")).strip(),
                        "score": round(top_score, 3),
                    })
                else:
                    skipped += 1
                    report_items.append({
                        "row_idx": int(row_idx),
                        "name": name,
                        "status": "skipped",
                        "onliner_id": top_id,
                        "onliner_name": str(top.get("name", "")).strip(),
                        "score": round(top_score, 3),
                    })
            else:
                skipped += 1
                report_items.append({
                    "row_idx": int(row_idx),
                    "name": name,
                    "status": "not_found",
                    "onliner_id": "",
                    "onliner_name": "",
                    "score": 0.0,
                })

            percent = int(round((done_idx / len(tasks)) * 100)) if tasks else 100
            with AUTOFILL_TGPC_PC_LOCK:
                autofill_tgpc_pc_status.update({
                    "done": int(done_idx),
                    "applied": int(applied),
                    "skipped": int(skipped),
                    "percent": int(percent),
                    "items": report_items[-20:],
                    "message": f"Обработано {done_idx} из {len(tasks)}. Подставлено: {applied}.",
                })

        save_id_cache(id_cache)
        save_manual_id_bindings(manual_bindings)
        if journal_entry["changes"]:
            append_id_change_journal(journal_entry)
        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")
        with AUTOFILL_TGPC_PC_LOCK:
            autofill_tgpc_pc_status.update({
                "running": False,
                "done": int(len(tasks)),
                "applied": int(applied),
                "skipped": int(skipped),
                "percent": 100 if tasks else 0,
                "items": report_items[-50:],
                "finished_at": int(time.time()),
                "message": f"Автоподбор завершён: подставлено {applied} из {len(tasks)} TGPC ПЭВМ.",
            })
    except Exception as e:
        with AUTOFILL_TGPC_PC_LOCK:
            autofill_tgpc_pc_status.update({
                "running": False,
                "items": report_items[-50:],
                "done": int(len(report_items)),
                "finished_at": int(time.time()),
                "message": "Ошибка автоподбора TGPC ПЭВМ: " + str(e)[:180],
            })


@app.route("/api/autofill-tgpc-pc-ids", methods=["POST"])
def api_autofill_tgpc_pc_ids():
    global autofill_tgpc_pc_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных для обработки"}), 400
    payload = request.get_json(silent=True) or {}
    try:
        max_items = int(payload.get("limit", 0) or 0)
    except Exception:
        max_items = 0
    max_items = max(0, min(max_items, 200))

    with AUTOFILL_TGPC_PC_LOCK:
        if autofill_tgpc_pc_status.get("running"):
            return jsonify({"status": "already_running"})
        autofill_tgpc_pc_status = {
            "running": True,
            "total": 0,
            "done": 0,
            "applied": 0,
            "skipped": 0,
            "percent": 0,
            "items": [],
            "started_at": int(time.time()),
            "finished_at": 0,
            "message": "Подготовка автоподбора TGPC ПЭВМ...",
        }

    threading.Thread(target=_autofill_tgpc_pc_worker, args=(str(session_dir), max_items), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/autofill-tgpc-pc-status")
def api_autofill_tgpc_pc_status():
    with AUTOFILL_TGPC_PC_LOCK:
        payload = dict(autofill_tgpc_pc_status)
        payload["items"] = list(payload.get("items", []) or [])
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


@app.route("/api/autofill-iven-bridge", methods=["POST"])
def api_autofill_iven_bridge():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных для обработки"}), 400
    payload = request.get_json(silent=True) or {}
    ignore_manual_cache = _coerce_bool(payload.get("ignore_manual_cache", False), default=False)
    prefer_b2b = _coerce_bool(payload.get("prefer_b2b", False), default=False)
    with AUTOFILL_IVEN_LOCK:
        if autofill_iven_status.get("running"):
            return jsonify({"status": "already_running"})
        autofill_iven_status = {
            "running": True,
            "total": 0, "done": 0, "applied": 0, "skipped": 0, "percent": 0,
            "started_at": int(time.time()), "finished_at": 0,
            "message": "Подготовка IVEN-бриджа..." + (" Режим: B2B без кеша." if prefer_b2b else ""),
            "matches": [],
            "no_match": [],
            "report_mode": "iven",
            "report_title": "Отчёт подбора IVEN-бридж",
            "report_subtitle": "Сопоставление N-Tech товаров с базой Onliner ID",
        }
    threading.Thread(
        target=_autofill_iven_bridge_worker,
        args=(str(session_dir), ignore_manual_cache, prefer_b2b),
        daemon=True,
    ).start()
    return jsonify({"status": "started"})


@app.route("/api/autofill-iven-status")
def api_autofill_iven_status():
    with AUTOFILL_IVEN_LOCK:
        payload = dict(autofill_iven_status)
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/iven-reject-match", methods=["POST"])
def api_iven_reject_match():
    """Удалить OnlinerID у товара N-Tech (из отчёта IVEN-бридж).
    Body: {"name": "...", "row_idx": 123}
    """
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    payload = request.get_json(silent=True) or {}
    item_name = str(payload.get("name", "")).strip()
    row_idx = payload.get("row_idx")
    if not item_name:
        return jsonify({"status": "error", "message": "name required"}), 400
    try:
        df = read_consolidated_df(session_dir)
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        if "Ссылка" in df.columns:
            df["Ссылка"] = df["Ссылка"].astype("object")
        cleared = 0
        if row_idx is not None:
            try:
                ri = int(row_idx)
                if ri in df.index:
                    df.at[ri, "OnlinerID"] = np.nan
                    if "Ссылка" in df.columns:
                        df.at[ri, "Ссылка"] = ""
                    cleared = 1
            except Exception:
                pass
        # Also clear by name match if row_idx not found
        if cleared == 0 and item_name:
            name_key = _normalize_name_key(item_name)
            if "Название" in df.columns:
                for idx, row in df.iterrows():
                    if _normalize_name_key(str(row.get("Название", ""))) == name_key:
                        df.at[idx, "OnlinerID"] = np.nan
                        if "Ссылка" in df.columns:
                            df.at[idx, "Ссылка"] = ""
                        cleared += 1
                        break
        # Remove from manual bindings if present
        name_key = _normalize_name_key(item_name)
        manual_bindings = load_manual_id_bindings()
        if name_key and name_key in manual_bindings:
            del manual_bindings[name_key]
            save_manual_id_bindings(manual_bindings)
        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")
        return jsonify({"status": "ok", "cleared": cleared})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/onliner-db-stats")
def api_onliner_db_stats():
    stats = db_stats()
    resp = jsonify(stats)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/onliner-db-search")
def api_onliner_db_search():
    query = str(request.args.get("q", "") or "").strip()
    if not query:
        return jsonify({"items": []})
    items = []
    seen = set()
    query_lower = query.lower()
    compact = re.sub(r"[^a-z0-9]+", "", query_lower)
    try:
        with _db_connection() as conn:
            rows = []
            if query.isdigit():
                rows.extend(conn.execute(
                    "SELECT oc.onliner_id, oc.name, oc.url, oc.source "
                    "FROM onliner_catalog oc WHERE oc.onliner_id = ? LIMIT 20",
                    (query,),
                ).fetchall())
            rows.extend(conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url, oc.source "
                "FROM name_index ni "
                "LEFT JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE lower(ni.raw_name) LIKE ? LIMIT 40",
                (f"%{query_lower}%",),
            ).fetchall())
            if compact and compact != query_lower:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url, oc.source "
                    "FROM name_index ni "
                    "LEFT JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '\"', '') LIKE ? LIMIT 40",
                    (f"%{compact}%",),
                ).fetchall())
            for row in rows:
                oid = normalize_onliner_id(row[0] if not isinstance(row, sqlite3.Row) else row["onliner_id"])
                raw_name = str((row[1] if not isinstance(row, sqlite3.Row) else row["raw_name"]) or "").strip()
                if not oid or not raw_name or oid in seen:
                    continue
                seen.add(oid)
                items.append({
                    "id": oid,
                    "name": raw_name,
                    "url": str((row[2] if not isinstance(row, sqlite3.Row) else row["url"]) or "").strip(),
                    "source": str((row[3] if not isinstance(row, sqlite3.Row) else row["source"]) or "").strip(),
                })
    except Exception as e:
        return jsonify({"items": [], "message": str(e)}), 500
    items.sort(key=lambda item: (
        0 if query_lower in str(item.get("name", "")).lower() else 1,
        len(str(item.get("name", ""))),
        str(item.get("name", "")).lower(),
    ))
    return jsonify({"items": items[:30]})


@app.route("/api/onliner-db-rebuild", methods=["POST"])
def api_onliner_db_rebuild():
    """Пересоздаёт БД из текущего сессионного прайса."""
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    try:
        df = read_consolidated_df(session_dir)
        products, names = db_populate_from_df(
            df, "price_load", skip_suppliers=["N-Tech", "TGPC"]
        )
        return jsonify({"status": "ok", "products": products, "names": names})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/onliner-db-import-gsheet", methods=["POST"])
def api_onliner_db_import_gsheet():
    """Скачивает CSV из Google Sheets и импортирует в SQLite.
    Body: {"sheet_id": "...", "sheet_name": "..."}
    """
    with _CATALOG_IMPORT_LOCK:
        if _catalog_import_status.get("running"):
            return jsonify({"status": "already_running", "message": "Импорт уже запущен"}), 409

    payload = request.get_json(silent=True) or {}
    sheet_id   = str(payload.get("sheet_id", "")).strip()
    sheet_name = str(payload.get("sheet_name", "All_Catalog")).strip() or "All_Catalog"
    force_refresh = bool(payload.get("force_refresh", False))
    if not sheet_id:
        return jsonify({"status": "error", "message": "sheet_id required"}), 400

    def _download_and_import():
        import tempfile
        import urllib.error
        # Try primary export URL; fall back to gviz/tq if it fails
        urls = [
            (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
             f"/export?format=csv&sheet={urllib.parse.quote(sheet_name)}"),
            (f"https://docs.google.com/spreadsheets/d/{sheet_id}"
             f"/gviz/tq?tqx=out:csv&sheet={urllib.parse.quote(sheet_name)}"),
        ]
        safe_sheet = re.sub(r"[^a-zA-Z0-9._-]+", "_", sheet_name).strip("._-") or "sheet"
        cache_name = f"{sheet_id}_{safe_sheet}.csv"
        cache_path = ONLINER_DB_GSHEET_CACHE_DIR / cache_name
        with _CATALOG_IMPORT_LOCK:
            _catalog_import_status.update({
                "running": True, "total": 0, "done": 0, "inserted": 0,
                "skipped": 0, "percent": 0, "finished_at": None,
                "message": "Подключаюсь к Google Sheets…",
            })
        try:
            ONLINER_DB_GSHEET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            now_ts = int(time.time())
            cache_fresh = False
            if cache_path.exists():
                try:
                    age_sec = max(0, now_ts - int(cache_path.stat().st_mtime))
                    cache_fresh = (age_sec <= ONLINER_DB_GSHEET_CACHE_TTL_SEC) and (cache_path.stat().st_size > 0)
                except Exception:
                    cache_fresh = False

            if cache_fresh and not force_refresh:
                with _CATALOG_IMPORT_LOCK:
                    _catalog_import_status.update({
                        "message": "Использую локальный кэш Google Sheets (без повторного скачивания)…",
                        "percent": 5,
                    })
            else:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
                tmp.close()
                downloaded = False
                last_err = None
                for url in urls:
                    try:
                        req = urllib.request.Request(
                            url,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; PriceMixer/1.0)"},
                        )
                        # Stream download in 128 KB chunks — shows download progress
                        CHUNK = 131072
                        with urllib.request.urlopen(req, timeout=300) as resp:
                            total_size = int(resp.headers.get("Content-Length") or 0)
                            received = 0
                            with open(tmp.name, "wb") as f:
                                while True:
                                    chunk = resp.read(CHUNK)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    received += len(chunk)
                                    mb = received / 1024 / 1024
                                    total_mb = total_size / 1024 / 1024 if total_size else 0
                                    msg = (
                                        f"Скачано {mb:.1f} / {total_mb:.1f} МБ…"
                                        if total_size else f"Скачано {mb:.1f} МБ…"
                                    )
                                    pct = int(received / total_size * 15) if total_size else 5
                                    with _CATALOG_IMPORT_LOCK:
                                        _catalog_import_status.update({
                                            "message": msg, "percent": pct
                                        })
                        downloaded = True
                        break
                    except Exception as e:
                        last_err = e
                        continue

                if not downloaded:
                    raise Exception(f"Не удалось скачать файл: {last_err}")
                try:
                    import shutil
                    shutil.move(tmp.name, str(cache_path))
                except Exception:
                    # If move failed, keep temp path as fallback import source
                    cache_path = Path(tmp.name)
                with _CATALOG_IMPORT_LOCK:
                    _catalog_import_status.update({
                        "message": "Файл скачан и сохранен в кэш. Начинаю импорт…",
                        "percent": 16,
                    })

            _catalog_import_worker(str(cache_path), ".csv", cleanup_file=False)
        except Exception as e:
            with _CATALOG_IMPORT_LOCK:
                _catalog_import_status.update({
                    "running": False,
                    "message": f"Ошибка скачивания: {e}",
                    "finished_at": int(time.time()),
                })

    threading.Thread(target=_download_and_import, daemon=True).start()
    return jsonify({"status": "started", "message": "Скачиваю и импортирую…"})


@app.route("/api/onliner-db-import-csv", methods=["POST"])
def api_onliner_db_import_csv():
    """Принимает CSV или XLSX с каталогом Onliner и импортирует в SQLite БД.
    Ожидаемые колонки (0-based): A(0)=Category, C(2)=Model, E(4)=onliner_id, H(7)=FullName.
    """
    with _CATALOG_IMPORT_LOCK:
        if _catalog_import_status.get("running"):
            return jsonify({"status": "already_running",
                            "message": "Импорт уже запущен"}), 409

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "Файл не передан"}), 400

    filename = file.filename.lower()
    if filename.endswith(".xlsx"):
        ext = ".xlsx"
    elif filename.endswith(".xls"):
        ext = ".xls"
    elif filename.endswith(".csv"):
        ext = ".csv"
    else:
        return jsonify({"status": "error",
                        "message": "Поддерживаются только CSV и XLSX"}), 400

    import tempfile
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    file.save(tmp.name)
    tmp.close()

    t = threading.Thread(
        target=_catalog_import_worker,
        args=(tmp.name, ext),
        daemon=True,
    )
    t.start()
    return jsonify({"status": "started", "message": "Импорт запущен"})


@app.route("/api/onliner-db-import-status")
def api_onliner_db_import_status():
    with _CATALOG_IMPORT_LOCK:
        payload = dict(_catalog_import_status)
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/api/manual-id-rollback-last", methods=["POST"])
def api_manual_id_rollback_last():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400

    rows = load_id_change_journal()
    if not rows:
        return jsonify({"status": "error", "message": "Журнал замен пуст"}), 400

    last_idx = -1
    for i in range(len(rows) - 1, -1, -1):
        rec = rows[i]
        if str(rec.get("session_dir", "")).strip() == str(session_dir):
            last_idx = i
            break
    if last_idx < 0:
        return jsonify({"status": "error", "message": "Для текущей сессии нет записей отката"}), 400

    rec = rows.pop(last_idx)
    changes = rec.get("changes", []) if isinstance(rec, dict) else []
    if not isinstance(changes, list) or not changes:
        save_id_change_journal(rows)
        return jsonify({"status": "error", "message": "В записи нет изменений для отката"}), 400

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return jsonify({"status": "error", "message": "В прайсе нет OnlinerID"}), 400
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    df["Ссылка"] = df["Ссылка"].astype("object")

    restored = 0
    for ch in changes:
        try:
            row_idx = int(ch.get("row_idx"))
        except Exception:
            continue
        if row_idx not in df.index:
            continue
        old_id = normalize_onliner_id(ch.get("old_onliner_id", ""))
        old_url = str(ch.get("old_url", "")).strip()
        df.at[row_idx, "OnlinerID"] = old_id
        df.at[row_idx, "Ссылка"] = old_url
        restored += 1

    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    save_id_change_journal(rows)
    return jsonify({"status": "ok", "restored": restored})


@app.route("/api/clear-invalid-onliner-ids", methods=["POST"])
def api_clear_invalid_onliner_ids():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        return jsonify({"status": "ok", "cleared": 0})

    keys_to_clear = set()
    ids_to_clear = set()
    for it in items[:2000]:
        key = str((it or {}).get("key", "")).strip()
        oid = normalize_onliner_id((it or {}).get("onliner_id", ""))
        if key:
            keys_to_clear.add(key)
        if oid:
            ids_to_clear.add(oid)

    if not keys_to_clear and not ids_to_clear:
        return jsonify({"status": "ok", "cleared": 0})

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return jsonify({"status": "ok", "cleared": 0})
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")

    cleared = 0
    touched_name_keys = []
    touched_articles = []
    for i, row in df.iterrows():
        row_key = build_item_category_key(row)
        row_oid = normalize_onliner_id(row.get("OnlinerID", ""))
        should_clear = False
        if row_key and row_key in keys_to_clear or row_oid and row_oid in ids_to_clear:
            should_clear = True
        if not should_clear:
            continue
        if row_oid:
            name = str(row.get("Название", "")).strip()
            touched_name_keys.append(_normalize_name_key(name))
            touched_articles.append(_get_id_cache_key_for_name(name))
        df.at[i, "OnlinerID"] = ""
        df.at[i, "Ссылка"] = ""
        cleared += 1

    if cleared > 0:
        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        # Чистим кэши ручных/артикульных привязок для этих товаров, чтобы старый ID не возвращался.
        id_cache = load_id_cache()
        changed_id_cache = False
        for art in touched_articles:
            a = str(art or "").strip()
            if not a:
                continue
            rec = id_cache.get(a)
            if isinstance(rec, dict):
                rid = normalize_onliner_id(rec.get("id", ""))
                if rid and rid in ids_to_clear:
                    id_cache.pop(a, None)
                    changed_id_cache = True
        if changed_id_cache:
            save_id_cache(id_cache)

        bindings = load_manual_id_bindings()
        changed_bindings = False
        for nk in touched_name_keys:
            k = str(nk or "").strip()
            if not k:
                continue
            rec = bindings.get(k)
            if isinstance(rec, dict):
                rid = normalize_onliner_id(rec.get("id", ""))
                if rid and rid in ids_to_clear:
                    bindings.pop(k, None)
                    changed_bindings = True
        if changed_bindings:
            save_manual_id_bindings(bindings)

    return jsonify({"status": "ok", "cleared": int(cleared)})


@app.route("/api/clear-all-nonpc-onliner-ids", methods=["POST"])
def api_clear_all_nonpc_onliner_ids():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных для обработки"}), 400

    try:
        df = read_consolidated_df(session_dir)
        if "OnlinerID" not in df.columns:
            return jsonify({"status": "ok", "cleared": 0, "kept_pc": 0, "message": "В прайсе нет OnlinerID."})
        if "Ссылка" not in df.columns:
            df["Ссылка"] = ""
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        df["Ссылка"] = df["Ссылка"].astype("object")

        cleared = 0
        kept_pc = 0
        skipped_other_suppliers = 0
        journal_changes = []
        affected_name_keys = set()
        affected_articles = set()
        ntech_supplier_names = {"N-TECH", "NTECH"}

        for idx, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            supplier = str(row.get("Поставщик", "")).strip().upper()
            if supplier not in ntech_supplier_names:
                skipped_other_suppliers += 1
                continue
            name = str(row.get("Название", "")).strip()
            if _is_tgpc_pc_name(name):
                kept_pc += 1
                continue
            old_url = str(row.get("Ссылка", "")).strip()
            df.at[idx, "OnlinerID"] = np.nan
            df.at[idx, "Ссылка"] = ""
            cleared += 1
            name_key = _normalize_name_key(name)
            if name_key:
                affected_name_keys.add(name_key)
            article_key = str(_get_id_cache_key_for_name(name) or "").strip()
            if article_key:
                affected_articles.add(article_key)
            journal_changes.append({
                "row_idx": int(idx),
                "name": name,
                "old_onliner_id": oid,
                "old_url": old_url,
                "new_onliner_id": "",
                "new_url": "",
                "reason": "bulk_clear_nonpc_before_rematch",
            })

        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        if journal_changes:
            append_id_change_journal({
                "ts": int(time.time()),
                "action": "clear_all_nonpc_onliner_ids",
                "session_dir": str(session_dir),
                "source": "api_clear_all_nonpc_onliner_ids",
                "changes": journal_changes,
            })

        queue = load_review_queue()
        changed_queue = False
        for name_key in list(affected_name_keys):
            if name_key in queue:
                queue.pop(name_key, None)
                changed_queue = True
        if changed_queue:
            save_review_queue(queue)

        bindings = load_manual_id_bindings()
        changed_bindings = False
        cleared_manual_bindings = 0
        for name_key in list(affected_name_keys):
            if name_key in bindings:
                bindings.pop(name_key, None)
                changed_bindings = True
                cleared_manual_bindings += 1
        if changed_bindings:
            save_manual_id_bindings(bindings)

        id_cache = load_id_cache()
        changed_id_cache = False
        cleared_id_cache = 0
        for article_key in list(affected_articles):
            if article_key in id_cache:
                id_cache.pop(article_key, None)
                changed_id_cache = True
                cleared_id_cache += 1
        if changed_id_cache:
            save_id_cache(id_cache)

        return jsonify({
            "status": "ok",
            "cleared": int(cleared),
            "kept_pc": int(kept_pc),
            "skipped_other_suppliers": int(skipped_other_suppliers),
            "cleared_manual_bindings": int(cleared_manual_bindings),
            "cleared_id_cache": int(cleared_id_cache),
            "message": f"N-Tech: очищено ID {cleared}. ПЭВМ сохранено: {kept_pc}. Кэш N-Tech тоже очищен. Остальные поставщики не тронуты.",
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:220]}), 500


@app.route("/api/clear-ntech-duplicate-onliner-ids", methods=["POST"])
def api_clear_ntech_duplicate_onliner_ids():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных для обработки"}), 400

    try:
        df = read_consolidated_df(session_dir)
        if "OnlinerID" not in df.columns:
            return jsonify({"status": "ok", "cleared": 0, "duplicate_ids": 0, "message": "В прайсе нет OnlinerID."})
        if "Ссылка" not in df.columns:
            df["Ссылка"] = ""
        df["OnlinerID"] = df["OnlinerID"].astype("object")
        df["Ссылка"] = df["Ссылка"].astype("object")

        ntech_supplier_names = {"N-TECH", "NTECH"}
        ntech_rows = []
        id_counts = {}
        for idx, row in df.iterrows():
            supplier = str(row.get("Поставщик", "")).strip().upper()
            if supplier not in ntech_supplier_names:
                continue
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            ntech_rows.append((idx, row, oid))
            id_counts[oid] = int(id_counts.get(oid, 0)) + 1

        duplicate_ids = {oid for oid, cnt in id_counts.items() if cnt > 1}
        if not duplicate_ids:
            return jsonify({
                "status": "ok",
                "cleared": 0,
                "duplicate_ids": 0,
                "message": "У N-Tech не найдено дублирующихся OnlinerID.",
            })

        cleared = 0
        journal_changes = []
        affected_name_keys = set()
        affected_articles = set()

        for idx, row, oid in ntech_rows:
            if oid not in duplicate_ids:
                continue
            name = str(row.get("Название", "")).strip()
            old_url = str(row.get("Ссылка", "")).strip()
            df.at[idx, "OnlinerID"] = np.nan
            df.at[idx, "Ссылка"] = ""
            cleared += 1
            name_key = _normalize_name_key(name)
            if name_key:
                affected_name_keys.add(name_key)
            article_key = str(_get_id_cache_key_for_name(name) or "").strip()
            if article_key:
                affected_articles.add(article_key)
            journal_changes.append({
                "row_idx": int(idx),
                "name": name,
                "old_onliner_id": oid,
                "old_url": old_url,
                "new_onliner_id": "",
                "new_url": "",
                "reason": "bulk_clear_ntech_duplicate_ids",
            })

        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        append_id_change_journal({
            "ts": int(time.time()),
            "action": "clear_ntech_duplicate_onliner_ids",
            "session_dir": str(session_dir),
            "source": "api_clear_ntech_duplicate_onliner_ids",
            "changes": journal_changes,
        })

        queue = load_review_queue()
        queue_changed = False
        for name_key in list(affected_name_keys):
            if name_key in queue:
                queue.pop(name_key, None)
                queue_changed = True
        if queue_changed:
            save_review_queue(queue)

        bindings = load_manual_id_bindings()
        changed_bindings = False
        cleared_manual_bindings = 0
        for name_key in list(affected_name_keys):
            if name_key in bindings:
                bindings.pop(name_key, None)
                changed_bindings = True
                cleared_manual_bindings += 1
        if changed_bindings:
            save_manual_id_bindings(bindings)

        id_cache = load_id_cache()
        changed_id_cache = False
        cleared_id_cache = 0
        for article_key in list(affected_articles):
            if article_key in id_cache:
                id_cache.pop(article_key, None)
                changed_id_cache = True
                cleared_id_cache += 1
        if changed_id_cache:
            save_id_cache(id_cache)

        return jsonify({
            "status": "ok",
            "cleared": int(cleared),
            "duplicate_ids": int(len(duplicate_ids)),
            "cleared_manual_bindings": int(cleared_manual_bindings),
            "cleared_id_cache": int(cleared_id_cache),
            "message": (
                f"N-Tech: очищено строк-дублей {cleared} "
                f"(уникальных ID: {len(duplicate_ids)})."
            ),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:220]}), 500


def _verify_all_ids_one(row_idx, row):
    app_settings = load_app_settings()
    verify_cfg = (app_settings.get("verify_id") or {})
    local_name = str(row.get("Название", "")).strip()
    oid = normalize_onliner_id(row.get("OnlinerID", ""))
    supplier = str(row.get("Поставщик", "")).strip()
    category = str(row_category(row)).strip()
    if not oid:
        return None

    info = fetch_onliner_product_info(
        oid,
        force_refresh=_coerce_bool(verify_cfg.get("force_refresh_api", True), default=True),
        use_cache_on_error=True,
        product_name_hint=local_name,
    )
    api_name = str(info.get("name", "")).strip()
    api_url = str(info.get("url", "")).strip()
    source = str(info.get("source", "")).strip()
    manual_ok = _coerce_bool(verify_cfg.get("trust_manual_confirmed", True), default=True) and is_manually_confirmed_id(local_name, oid)

    if manual_ok:
        return {
            "row_idx": int(row_idx),
            "onliner_id": oid,
            "name": local_name,
            "supplier": supplier,
            "category": category,
            "api_name": api_name,
            "api_url": api_url,
            "score": 1.0,
            "reason": "manual_confirmed",
            "reason_label": "ID подтвержден вручную и сохранен в постоянный кеш",
            "status": "match",
            "status_label": "OK",
            "source": (source + "|manual_confirmed").strip("|"),
            "needs_review": False,
        }

    if not api_name:
        api_no_name_status = str(verify_cfg.get("api_no_name_status", "review")).strip().lower()
        is_mismatch = api_no_name_status == "mismatch"
        return {
            "row_idx": int(row_idx),
            "onliner_id": oid,
            "name": local_name,
            "supplier": supplier,
            "category": category,
            "api_name": "",
            "api_url": api_url,
            "score": 0.0,
            "reason": "api_no_name",
            "reason_label": "API не вернул название товара по текущему ID",
            "status": "mismatch" if is_mismatch else "review",
            "status_label": "Проверить",
            "source": source,
            "needs_review": True,
        }

    cmp = calc_name_match(local_name, api_name)
    score = round(float(cmp.get("score", 0.0) or 0.0), 3)
    is_match = bool(cmp.get("match"))
    threshold = _coerce_float(verify_cfg.get("match_threshold", 0.74), 0.74, min_value=0.1, max_value=0.99)
    if score >= threshold:
        is_match = True
    if _coerce_bool(verify_cfg.get("require_article_or_model_priority", False), default=False):
        if str(cmp.get("reason", "") or "") not in {"article", "article_like", "paren_model", "model_token"}:
            is_match = False
    return {
        "row_idx": int(row_idx),
        "onliner_id": oid,
        "name": local_name,
        "supplier": supplier,
        "category": category,
        "api_name": api_name,
        "api_url": api_url,
        "score": score,
        "reason": str(cmp.get("reason", "") or ""),
        "reason_label": "Совпало" if is_match else "Название товара не совпало с Onliner по текущему ID",
        "status": "match" if is_match else "mismatch",
        "status_label": "OK" if is_match else "Несовпадение",
        "source": source,
        "needs_review": not is_match,
    }


def _verify_all_ids_worker(session_dir):
    global verify_all_ids_status
    try:
        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df)
        df = apply_visibility_filter(df, session_dir)
        if "OnlinerID" not in df.columns:
            with VERIFY_ALL_IDS_LOCK:
                verify_all_ids_status.update({
                    "running": False,
                    "total": 0,
                    "done": 0,
                    "matched": 0,
                    "mismatched": 0,
                    "errors": 0,
                    "items": [],
                    "report_items": [],
                    "finished_at": int(time.time()),
                    "message": "В текущем прайсе нет колонки OnlinerID.",
                })
            return

        tasks = []
        skipped_tgpc_pc = 0
        for i, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            # TGPC ПЭВМ верифицируются отдельной функцией автоподбора — пропускаем
            name = str(row.get("Название", "")).strip()
            if _is_tgpc_pc_name(name):
                skipped_tgpc_pc += 1
                continue
            tasks.append((int(i), row.copy()))

        skip_note = f" (TGPC ПЭВМ пропущено: {skipped_tgpc_pc})" if skipped_tgpc_pc else ""
        with VERIFY_ALL_IDS_LOCK:
            verify_all_ids_status.update({
                "total": len(tasks),
                "done": 0,
                "matched": 0,
                "mismatched": 0,
                "errors": 0,
                "items": [],
                "report_items": [],
                "message": f"Проверка ID запущена{skip_note}.",
            })

        if not tasks:
            with VERIFY_ALL_IDS_LOCK:
                verify_all_ids_status.update({
                    "running": False,
                    "finished_at": int(time.time()),
                    "message": "В текущем прайсе нет товаров с OnlinerID.",
                })
            return

        result_items = []
        report_items = []
        matched = 0
        mismatched = 0
        errors = 0
        workers = max(1, min(get_onliner_api_max_workers(default=8), 10, len(tasks)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_verify_all_ids_one, row_idx, row): row_idx for row_idx, row in tasks}
            for fut in as_completed(futures):
                try:
                    item = fut.result()
                except Exception:
                    item = None
                    errors += 1
                else:
                    if item is None:
                        pass
                    else:
                        report_items.append(item)
                        if item.get("needs_review"):
                            mismatched += 1
                            result_items.append(item)
                        else:
                            matched += 1
                finally:
                    with VERIFY_ALL_IDS_LOCK:
                        verify_all_ids_status["done"] = int(verify_all_ids_status.get("done", 0) or 0) + 1
                        verify_all_ids_status["matched"] = int(matched)
                        verify_all_ids_status["mismatched"] = int(mismatched)
                        verify_all_ids_status["errors"] = int(errors)

        result_items.sort(key=lambda x: (float(x.get("score", 0.0) or 0.0), str(x.get("name", "")).lower()))
        report_items.sort(key=lambda x: (
            0 if str(x.get("status", "")).strip().lower() == "mismatch" else 1,
            0 if str(x.get("status", "")).strip().lower() == "review" else 1,
            str(x.get("name", "")).lower(),
        ))
        with VERIFY_ALL_IDS_LOCK:
            verify_all_ids_status.update({
                "running": False,
                "matched": int(matched),
                "mismatched": int(mismatched),
                "errors": int(errors),
                "items": result_items,
                "report_items": report_items,
                "finished_at": int(time.time()),
                "message": f"Проверено ID: {len(tasks)}. Несовпадений: {mismatched}.{skip_note}",
            })
    except Exception as e:
        with VERIFY_ALL_IDS_LOCK:
            verify_all_ids_status.update({
                "running": False,
                "finished_at": int(time.time()),
                "message": "Ошибка проверки ID: " + str(e)[:180],
            })


def _validate_clean_ids_worker(session_dir):
    """Валидация + очистка ID:
    Фаза 1 (параллельно): проверяет соответствие каждого OnlinerID по Onliner API.
      - score >= 0.65  → подтверждает в manual_bindings
      - score < 0.65   → очищает ID, ставит в список на поиск кандидатов
    Фаза 2 (последовательно): для очищенных ищет топ-3 кандидата → очередь проверки.
    """
    global validate_clean_ids_status
    CLEAR_THRESHOLD = 0.65
    try:
        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df)
        if "OnlinerID" not in df.columns:
            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "running": False, "finished_at": int(time.time()),
                    "message": "В текущем прайсе нет колонки OnlinerID.",
                })
            return

        manual_bindings = load_manual_id_bindings()
        review_queue = load_review_queue()
        app_settings = load_app_settings()
        no_id_cfg = (app_settings.get("no_id_search") or {})
        limit_cands = max(10, min(int(no_id_cfg.get("max_candidates", 80) or 80), 80))

        # Собираем задачи: только товары с ID и не TGPC ПК
        tasks = []
        for i, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            name = str(row.get("Название", "")).strip()
            if not name:
                continue
            if _is_tgpc_pc_name(name):
                continue
            tasks.append((int(i), row.copy()))

        with VALIDATE_CLEAN_IDS_LOCK:
            validate_clean_ids_status.update({
                "total": len(tasks), "done": 0,
                "confirmed": 0, "cleared": 0, "queued": 0, "errors": 0,
                "message": f"Фаза 1: проверяю {len(tasks)} товаров...",
            })

        if not tasks:
            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "running": False, "finished_at": int(time.time()),
                    "message": "Нет товаров с OnlinerID для проверки (или все TGPC ПЭВМ).",
                })
            return

        confirmed = 0
        cleared_items = []   # list of (row_idx, name, old_id, api_name, score)
        confirmed_rows = []  # for report: {name, api_name, onliner_id, score}
        skipped_rows = []    # API недоступен — ID не трогали
        skipped_api = 0
        errors = 0
        done = 0
        journal_changes = []

        # ─── Фаза 1: параллельная проверка существующих ID ───────────────────
        # Для валидации используем кэш (force_refresh=False) чтобы не перегружать
        # Onliner API 1600+ одновременными запросами.
        # Кэш обновляется не чаще раза в 7 дней (ONLINER_PRODUCT_CACHE_TTL).
        # Загружаем кэш один раз — потоки читают его без доп. запросов к диску
        product_cache = load_onliner_product_cache()

        def _fetch_product_name_hard_timeout(oid, hard_timeout=8):
            """Получает название товара по ID с ЖЕЛЕЗНЫМ таймаутом через отдельный поток.
            Возвращает (name, url, status):
              status == 'ok'            — JSON получен, name непустой
              status == 'not_found'   — HTTP 404 (товара нет — ID неверный)
              status == 'empty_payload' — 200, но без названия (не очищаем ID)
              status == 'http_error'  — другой HTTP-код
              status == 'error'       — сеть/парсинг
              status == 'timeout'     — зависание / очередь
            """
            import urllib.error as _urlerr
            _q = queue.Queue()
            def _fetch_worker():
                try:
                    url = f"https://catalog.api.onliner.by/products/{oid}"
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                    })
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        data = json.loads(resp.read().decode("utf-8", errors="replace")) or {}
                    name_ = str(data.get("full_name") or data.get("name") or "").strip()
                    url_  = str(data.get("html_url") or "").strip()
                    if name_:
                        _q.put((name_, url_, "ok"))
                    else:
                        _q.put(("", url_, "empty_payload"))
                except _urlerr.HTTPError as e:
                    if e.code == 404:
                        _q.put(("", "", "not_found"))
                    else:
                        print(f"[validate] HTTP {e.code} oid={oid}", flush=True)
                        _q.put(("", "", "http_error"))
                except Exception as e:
                    print(f"[validate] fetch_error oid={oid}: {e}", flush=True)
                    _q.put(("", "", "error"))
            t = threading.Thread(target=_fetch_worker, daemon=True)
            t.start()
            try:
                return _q.get(timeout=hard_timeout)
            except queue.Empty:
                print(f"[validate] ТАЙМАУТ {hard_timeout}с для oid={oid}", flush=True)
                return ("", "", "timeout")

        def _validate_one(row_idx, row):
            """Быстрая проверка: сначала кэш, потом один запрос с железным таймаутом.
            Поля record_confirm / mutate_df_clear:
              — mutate_df_clear=True только при явно неверном ID (404) или низком score.
              — при сбое API / таймауте оба False (ID в прайсе НЕ трогаем).
            """
            local_name = str(row.get("Название", "")).strip()
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                return None

            if is_manually_confirmed_id(local_name, oid):
                return {
                    "row_idx": int(row_idx), "onliner_id": oid,
                    "name": local_name, "api_name": "", "api_url": "",
                    "score": 1.0, "reason": "manual_confirmed",
                    "record_confirm": True, "mutate_df_clear": False,
                }

            now_ts = int(time.time())
            api_name = ""
            api_url = ""
            cached = product_cache.get(oid)
            if isinstance(cached, dict) and now_ts - int(cached.get("updated_at", 0)) <= ONLINER_PRODUCT_CACHE_TTL:
                api_name = str(cached.get("name", "")).strip()
                api_url = str(cached.get("url", "")).strip()
                if not api_name:
                    # Устаревший пустой кэш — не считаем это «товар не найден»
                    return {
                        "row_idx": int(row_idx), "onliner_id": oid,
                        "name": local_name, "api_name": "", "api_url": api_url,
                        "score": 0.0, "reason": "api_unreachable_cached_empty",
                        "record_confirm": False, "mutate_df_clear": False,
                    }
            else:
                api_name, api_url, fetch_status = _fetch_product_name_hard_timeout(oid, hard_timeout=9)
                if fetch_status == "not_found":
                    return {
                        "row_idx": int(row_idx), "onliner_id": oid,
                        "name": local_name, "api_name": "", "api_url": "",
                        "score": 0.0, "reason": "api_not_found",
                        "record_confirm": False, "mutate_df_clear": True,
                    }
                if fetch_status in ("timeout", "http_error", "error", "empty_payload"):
                    return {
                        "row_idx": int(row_idx), "onliner_id": oid,
                        "name": local_name, "api_name": "", "api_url": api_url,
                        "score": 0.0, "reason": "api_unreachable_" + fetch_status,
                        "record_confirm": False, "mutate_df_clear": False,
                    }
                if fetch_status == "ok" and api_name:
                    with ONLINER_PRODUCT_CACHE_LOCK:
                        product_cache[oid] = {
                            "updated_at": now_ts, "name": api_name, "url": api_url,
                        }

            if not api_name:
                return {
                    "row_idx": int(row_idx), "onliner_id": oid,
                    "name": local_name, "api_name": "", "api_url": api_url,
                    "score": 0.0, "reason": "api_unreachable_no_name",
                    "record_confirm": False, "mutate_df_clear": False,
                }

            cmp = calc_name_match(local_name, api_name)
            score = round(float(cmp.get("score", 0.0) or 0.0), 3)
            if score >= CLEAR_THRESHOLD:
                return {
                    "row_idx": int(row_idx), "onliner_id": oid,
                    "name": local_name, "api_name": api_name, "api_url": api_url,
                    "score": score, "reason": str(cmp.get("reason", "") or ""),
                    "record_confirm": True, "mutate_df_clear": False,
                }
            return {
                "row_idx": int(row_idx), "onliner_id": oid,
                "name": local_name, "api_name": api_name, "api_url": api_url,
                "score": score, "reason": str(cmp.get("reason", "") or ""),
                "record_confirm": False, "mutate_df_clear": True,
            }

        # ─── Фаза 1: последовательная проверка (без ThreadPoolExecutor) ───────────
        # Параллелизм убран намеренно: на macOS и Windows при 6-8 одновременных
        # daemon-потоков q.get(timeout=N) нестабильно возвращает Empty → вечный зависон.
        # При последовательной обработке каждый _fetch_product_name_hard_timeout
        # гарантированно завершится за ≤9 сек.
        print(f"[validate] Старт Фазы 1: {len(tasks)} товаров", flush=True)
        for task_i, (row_idx, row) in enumerate(tasks):
            name     = str(row.get("Название", "")).strip()
            oid      = normalize_onliner_id(row.get("OnlinerID", ""))
            name_key = _normalize_name_key(name)
            result   = None
            try:
                result = _validate_one(row_idx, row)
            except Exception as exc:
                print(f"[validate] ОШИБКА #{task_i+1}: {name[:50]} | {exc}", flush=True)
                errors += 1

            done += 1
            if done % 50 == 0 or done == 1:
                print(f"[validate] Фаза 1: {done}/{len(tasks)} — {name[:60]}", flush=True)

            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "done": done,
                    "confirmed": confirmed,
                    "cleared": len(cleared_items),
                    "skipped_api": skipped_api,
                    "errors": errors,
                    "message": f"Фаза 1: {done}/{len(tasks)} — {name[:55]}",
                })

            if result is None:
                continue

            score = float(result.get("score", 0.0) or 0.0)
            is_manual = result.get("reason") == "manual_confirmed"
            do_confirm = bool(result.get("record_confirm"))
            do_clear = bool(result.get("mutate_df_clear"))

            if not do_confirm and not do_clear:
                skipped_api += 1
                skipped_rows.append({
                    "name": name, "onliner_id": oid,
                    "reason": str(result.get("reason", "") or "api_unreachable"),
                })
                continue

            if do_confirm:
                if name_key and not is_manual:
                    manual_bindings[name_key] = {
                        "id": oid,
                        "url": str(result.get("api_url", "")).strip(),
                    }
                confirmed += 1
                confirmed_rows.append({
                    "name": name, "onliner_id": oid,
                    "api_name": str(result.get("api_name", "")).strip(),
                    "score": round(score, 3),
                })

            if not do_clear:
                continue

            old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
            # OnlinerID может быть float-колонкой (NaN) — записываем NaN, не ""
            try:
                df.at[row_idx, "OnlinerID"] = np.nan
            except Exception:
                try:
                    df["OnlinerID"] = df["OnlinerID"].astype(object)
                    df.at[row_idx, "OnlinerID"] = ""
                except Exception:
                    pass
            if "Ссылка" in df.columns:
                try:
                    df.at[row_idx, "Ссылка"] = np.nan
                except Exception:
                    try:
                        df["Ссылка"] = df["Ссылка"].astype(object)
                        df.at[row_idx, "Ссылка"] = ""
                    except Exception:
                        pass
            _reason = str(result.get("reason", "") or "")
            if _reason == "api_not_found":
                _jr = "validate_clean api_not_found"
            else:
                _jr = f"validate_clean score={round(score, 3)}"
            journal_changes.append({
                "row_idx": row_idx, "name": name,
                "old_onliner_id": oid, "old_url": old_url,
                "new_onliner_id": "", "new_url": "",
                "reason": _jr,
            })
            cleared_items.append((
                row_idx, name, name_key, oid,
                str(result.get("api_name", "")).strip(),
                round(score, 3),
                _reason,
            ))

        print(
            f"[validate] Фаза 1 завершена: подтверждено={confirmed}, очищено={len(cleared_items)}, "
            f"пропущено (API): {skipped_api}, ошибок={errors}",
            flush=True,
        )

        # ─── Фаза 2: ищем кандидатов для очищенных товаров ──────────────────
        queued = 0
        if cleared_items:
            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "message": f"Фаза 2: ищу кандидатов для {len(cleared_items)} очищенных товаров...",
                })
            for ci_idx, (row_idx, name, name_key, old_id, api_name, score, _clr_reason) in enumerate(cleared_items, 1):
                with VALIDATE_CLEAN_IDS_LOCK:
                    validate_clean_ids_status["message"] = (
                        f"Фаза 2: кандидаты {ci_idx}/{len(cleared_items)} — {name[:50]}"
                    )
                try:
                    candidates = search_onliner_candidates(
                        name, category_name="", query="",
                        limit=min(limit_cands, 10), max_queries=3, timeout_sec=6,
                    )
                    top3 = [
                        {
                            "id": normalize_onliner_id(c.get("id", "")),
                            "name": str(c.get("name", "")).strip(),
                            "score": round(float(c.get("score", 0) or 0), 3),
                            "url": str(c.get("url", "")).strip(),
                        }
                        for c in (candidates[:3] if candidates else [])
                        if normalize_onliner_id(c.get("id", ""))
                    ]
                except Exception:
                    top3 = []

                if name_key:
                    review_queue[name_key] = {
                        "name": name,
                        "cleared_id": old_id,
                        "cleared_score": score,
                        "onliner_name": api_name,
                        "candidates": top3,
                        "added_at": int(time.time()),
                    }
                if top3:
                    queued += 1
                with VALIDATE_CLEAN_IDS_LOCK:
                    validate_clean_ids_status["queued"] = queued

        # ─── Сохраняем результаты ────────────────────────────────────────────
        save_manual_id_bindings(manual_bindings)
        save_review_queue(review_queue)
        if journal_changes:
            append_id_change_journal({
                "ts": int(time.time()),
                "action": "validate_clean_ids",
                "session_dir": str(session_dir),
                "source": "api_validate_clean_ids",
                "changes": journal_changes,
            })
        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        cleared_count = len(cleared_items)
        # Build cleared_rows for UI report
        cleared_rows_report = []
        for tup in cleared_items:
            row_idx, name, name_key, old_id, api_name, score, clr_reason = (
                tup if len(tup) >= 7 else (*tup[:6], "")
            )
            if clr_reason == "api_not_found":
                api_disp = "HTTP 404 — товара с этим ID нет в каталоге Onliner"
            elif api_name:
                api_disp = api_name
            else:
                api_disp = "—"
            cleared_rows_report.append({
                "name": name, "onliner_id": old_id, "api_name": api_disp,
                "score": score, "clear_reason": clr_reason,
            })
        with VALIDATE_CLEAN_IDS_LOCK:
            validate_clean_ids_status.update({
                "running": False,
                "done": len(tasks),
                "confirmed": confirmed,
                "cleared": cleared_count,
                "skipped_api": skipped_api,
                "queued": queued,
                "errors": errors,
                "finished_at": int(time.time()),
                "cleared_rows":    cleared_rows_report,
                "confirmed_rows":  confirmed_rows,
                "skipped_rows":    skipped_rows[:500],
                "message": (
                    f"Готово. Подтверждено: {confirmed}, очищено: {cleared_count}"
                    + (f", пропущено (сбой API, ID сохранён): {skipped_api}" if skipped_api else "")
                    + (f", ошибок: {errors}" if errors else "")
                    + "."
                ),
            })
    except Exception as e:
        with VALIDATE_CLEAN_IDS_LOCK:
            validate_clean_ids_status.update({
                "running": False,
                "finished_at": int(time.time()),
                "message": "Ошибка валидации: " + str(e)[:180],
            })


def _validate_clean_ids_db_worker(session_dir):
    """Быстрая локальная сверка OnlinerID по SQLite-базе без Onliner API.
    Чистит только явные мусорные ID:
      - текущий ID есть в БД, но имя товара плохо совпадает;
      - точный name_key в БД указывает на другой OnlinerID.
    Если ID нет в локальной БД и точного имени нет — строку не трогаем.
    """
    global validate_clean_ids_status
    CLEAR_THRESHOLD = 0.65
    try:
        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df)
        if "OnlinerID" not in df.columns:
            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "running": False,
                    "finished_at": int(time.time()),
                    "message": "В текущем прайсе нет колонки OnlinerID.",
                })
            return

        manual_bindings = load_manual_id_bindings()
        review_queue = load_review_queue()
        app_settings = load_app_settings()
        no_id_cfg = (app_settings.get("no_id_search") or {})
        limit_cands = max(10, min(int(no_id_cfg.get("max_candidates", 80) or 80), 80))

        tasks = []
        for i, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            name = str(row.get("Название", "")).strip()
            if not name or _is_tgpc_pc_name(name):
                continue
            tasks.append((int(i), row.copy()))

        with VALIDATE_CLEAN_IDS_LOCK:
            validate_clean_ids_status.update({
                "total": len(tasks),
                "done": 0,
                "confirmed": 0,
                "cleared": 0,
                "queued": 0,
                "errors": 0,
                "skipped_api": 0,
                "mode": "db",
                "mode_label": "Локальная БД 150k",
                "skipped_label": "Пропуск = ID или имя не найдены в локальной БД, поэтому ID оставили без изменений.",
                "message": f"Локальная сверка: проверяю {len(tasks)} товаров...",
            })

        if not tasks:
            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "running": False,
                    "finished_at": int(time.time()),
                    "message": "Нет товаров с OnlinerID для локальной проверки (или все TGPC ПЭВМ).",
                })
            return

        confirmed = 0
        cleared_items = []
        confirmed_rows = []
        skipped_rows = []
        skipped_local = 0
        errors = 0
        done = 0
        journal_changes = []

        for row_idx, row in tasks:
            name = str(row.get("Название", "")).strip()
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            name_key = _normalize_name_key(name)
            try:
                if is_manually_confirmed_id(name, oid):
                    result = {
                        "status": "confirm",
                        "db_name": "",
                        "score": 1.0,
                        "reason": "manual_confirmed",
                        "exact_match": None,
                    }
                else:
                    current_db = db_get_product_by_id(oid)
                    exact_match = db_find_exact_id_for_name(name)
                    if current_db:
                        db_name = str(current_db.get("name", "")).strip()
                        cmp = calc_name_match(name, db_name)
                        score = round(float(cmp.get("score", 0.0) or 0.0), 3)
                        if score >= CLEAR_THRESHOLD:
                            result = {
                                "status": "confirm",
                                "db_name": db_name,
                                "score": score,
                                "reason": str(cmp.get("reason", "") or ""),
                                "exact_match": exact_match,
                            }
                        else:
                            result = {
                                "status": "clear",
                                "db_name": db_name,
                                "score": score,
                                "reason": "db_id_name_mismatch",
                                "exact_match": exact_match,
                            }
                    elif exact_match and normalize_onliner_id(exact_match.get("id", "")) != oid:
                        result = {
                            "status": "clear",
                            "db_name": str(exact_match.get("name", "")).strip(),
                            "score": 0.0,
                            "reason": "db_exact_points_other_id",
                            "exact_match": exact_match,
                        }
                    else:
                        result = {
                            "status": "skip",
                            "db_name": "",
                            "score": 0.0,
                            "reason": "db_missing_or_uncertain",
                            "exact_match": exact_match,
                        }
            except Exception as exc:
                print(f"[validate-db] ОШИБКА {name[:60]} | {exc}", flush=True)
                errors += 1
                result = None

            done += 1
            if done % 100 == 0 or done == 1:
                print(f"[validate-db] {done}/{len(tasks)} — {name[:60]}", flush=True)

            if result is None:
                with VALIDATE_CLEAN_IDS_LOCK:
                    validate_clean_ids_status.update({
                        "done": done,
                        "confirmed": confirmed,
                        "cleared": len(cleared_items),
                        "skipped_api": skipped_local,
                        "errors": errors,
                        "message": f"Локальная сверка: {done}/{len(tasks)} — {name[:55]}",
                    })
                continue

            status = str(result.get("status", "") or "")
            score = round(float(result.get("score", 0.0) or 0.0), 3)
            db_name = str(result.get("db_name", "") or "").strip()
            reason = str(result.get("reason", "") or "").strip()
            exact_match = result.get("exact_match") if isinstance(result.get("exact_match"), dict) else None

            if status == "skip":
                skipped_local += 1
                skipped_rows.append({
                    "name": name,
                    "onliner_id": oid,
                    "reason": reason,
                })
            elif status == "confirm":
                if name_key and reason != "manual_confirmed":
                    manual_bindings[name_key] = {
                        "id": oid,
                        "url": str((db_get_product_by_id(oid) or {}).get("url", "")).strip(),
                    }
                confirmed += 1
                confirmed_rows.append({
                    "name": name,
                    "onliner_id": oid,
                    "api_name": db_name or "Локальная БД",
                    "score": score,
                })
            elif status == "clear":
                old_url = str(df.at[row_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
                try:
                    df.at[row_idx, "OnlinerID"] = np.nan
                except Exception:
                    df["OnlinerID"] = df["OnlinerID"].astype(object)
                    df.at[row_idx, "OnlinerID"] = ""
                if "Ссылка" in df.columns:
                    try:
                        df.at[row_idx, "Ссылка"] = np.nan
                    except Exception:
                        df["Ссылка"] = df["Ссылка"].astype(object)
                        df.at[row_idx, "Ссылка"] = ""
                journal_changes.append({
                    "row_idx": row_idx,
                    "name": name,
                    "old_onliner_id": oid,
                    "old_url": old_url,
                    "new_onliner_id": "",
                    "new_url": "",
                    "reason": f"validate_clean_db {reason} score={score}",
                })
                cleared_items.append((
                    row_idx,
                    name,
                    name_key,
                    oid,
                    db_name,
                    score,
                    reason,
                    exact_match,
                ))

            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "done": done,
                    "confirmed": confirmed,
                    "cleared": len(cleared_items),
                    "skipped_api": skipped_local,
                    "errors": errors,
                    "message": f"Локальная сверка: {done}/{len(tasks)} — {name[:55]}",
                })

        queued = 0
        if cleared_items:
            with VALIDATE_CLEAN_IDS_LOCK:
                validate_clean_ids_status.update({
                    "message": f"Локальная сверка: ищу кандидатов для {len(cleared_items)} очищенных товаров...",
                })
            for ci_idx, (row_idx, name, name_key, old_id, db_name, score, clr_reason, exact_match) in enumerate(cleared_items, 1):
                with VALIDATE_CLEAN_IDS_LOCK:
                    validate_clean_ids_status["message"] = f"Локальная сверка: кандидаты {ci_idx}/{len(cleared_items)} — {name[:50]}"
                top_cands = []
                seen_ids = set()

                def _append_candidate(cid, cname, curl, cscore, csource):
                    cid = normalize_onliner_id(cid)
                    if not cid or cid in seen_ids:
                        return
                    seen_ids.add(cid)
                    top_cands.append({
                        "id": cid,
                        "name": str(cname or "").strip(),
                        "score": round(float(cscore or 0.0), 3),
                        "url": str(curl or "").strip(),
                        "source": str(csource or "").strip(),
                    })

                if exact_match:
                    _append_candidate(
                        exact_match.get("id", ""),
                        exact_match.get("name", ""),
                        exact_match.get("url", ""),
                        1.0,
                        exact_match.get("source", "db_exact"),
                    )
                for cand in db_find_top_candidates(name, top_n=5, min_score=0.40):
                    _append_candidate(
                        cand.get("id", ""),
                        cand.get("name", ""),
                        cand.get("url", ""),
                        cand.get("score", 0.0),
                        cand.get("source", "db_fuzzy"),
                    )

                if name_key:
                    review_queue[name_key] = {
                        "name": name,
                        "cleared_id": old_id,
                        "cleared_score": score,
                        "onliner_name": db_name,
                        "candidates": top_cands[:5],
                        "added_at": int(time.time()),
                    }
                if top_cands:
                    queued += 1
                with VALIDATE_CLEAN_IDS_LOCK:
                    validate_clean_ids_status["queued"] = queued

        save_manual_id_bindings(manual_bindings)
        save_review_queue(review_queue)
        if journal_changes:
            append_id_change_journal({
                "ts": int(time.time()),
                "action": "validate_clean_ids_db",
                "session_dir": str(session_dir),
                "source": "api_validate_clean_ids_db",
                "changes": journal_changes,
            })
        write_consolidated_df(session_dir, df)
        write_consolidated_json(df, Path(session_dir) / "consolidated.json")

        cleared_rows_report = []
        for row_idx, name, name_key, old_id, db_name, score, clr_reason, exact_match in cleared_items:
            if clr_reason == "db_exact_points_other_id" and exact_match:
                db_disp = f"Локальная БД знает этот товар как ID {normalize_onliner_id(exact_match.get('id', ''))}"
            else:
                db_disp = db_name or "—"
            cleared_rows_report.append({
                "name": name,
                "onliner_id": old_id,
                "api_name": db_disp,
                "score": score,
                "clear_reason": clr_reason,
            })

        with VALIDATE_CLEAN_IDS_LOCK:
            validate_clean_ids_status.update({
                "running": False,
                "done": len(tasks),
                "confirmed": confirmed,
                "cleared": len(cleared_items),
                "skipped_api": skipped_local,
                "queued": queued,
                "errors": errors,
                "finished_at": int(time.time()),
                "cleared_rows": cleared_rows_report,
                "confirmed_rows": confirmed_rows,
                "skipped_rows": skipped_rows[:500],
                "message": (
                    f"Локальная сверка готова. Подтверждено: {confirmed}, очищено: {len(cleared_items)}"
                    + (f", пропущено: {skipped_local}" if skipped_local else "")
                    + (f", ошибок: {errors}" if errors else "")
                    + "."
                ),
            })
    except Exception as e:
        with VALIDATE_CLEAN_IDS_LOCK:
            validate_clean_ids_status.update({
                "running": False,
                "finished_at": int(time.time()),
                "message": "Ошибка локальной проверки: " + str(e)[:180],
            })


@app.route("/api/id-replace-candidates", methods=["POST"])
def api_id_replace_candidates():
    app_settings = load_app_settings()
    no_id_cfg = (app_settings.get("no_id_search") or {})
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "")).strip()
    query = str(payload.get("query", "")).strip()
    current_id = normalize_onliner_id(payload.get("onliner_id", ""))
    exclude_current = _coerce_bool(payload.get("exclude_current", False), default=False)
    try:
        limit = int(payload.get("limit", 80))
    except Exception:
        limit = 80
    limit = max(10, min(limit, int(no_id_cfg.get("max_candidates", 80) or 80), 150))

    if not name and not query:
        return jsonify({"items": []})

    items = []
    seen = set()

    # 1) Быстрый приоритет: текущий ID (для сравнения) сразу в список.
    # Только локальная БД: без внешних API-запросов.
    if current_id and not exclude_current:
        db_item = db_get_product_by_id(current_id) or {}
        cur_name = str(db_item.get("name", "")).strip()
        cur_url = str(db_item.get("url", "")).strip()
        hints = _category_path_hints(category)
        if hints and cur_url and not any(h in cur_url for h in hints):
            cur_name = ""
            cur_url = ""
        items.append({
            "id": current_id,
            "name": cur_name or f"Текущий ID {current_id}",
            "url": cur_url,
            "score": 0.0,
            "source": "current",
        })
        seen.add(current_id)

    # 2) Только локальная SQLite БД (без B2B и без публичного catalog API).
    local_name = name or query
    local_top = db_find_top_candidates(local_name, top_n=limit, min_score=0.12, allow_b2b=False)
    exact = db_find_exact_id_for_name(local_name)
    local_candidates = []
    if isinstance(exact, dict):
        local_candidates.append(exact)
    if isinstance(local_top, list):
        local_candidates.extend(local_top)
    for c in local_candidates:
        cid = normalize_onliner_id(c.get("id", ""))
        if not cid or cid in seen:
            continue
        items.append({
            "id": cid,
            "name": str(c.get("name", "")).strip(),
            "url": str(c.get("url", "")).strip(),
            "score": round(float(c.get("score", 0.0) or 0.0), 3),
            "source": "local_db",
        })
        seen.add(cid)
        if len(items) >= limit:
            break

    return jsonify({"items": items[:limit]})


def _build_duplicate_onliner_id_issues(df):
    if "OnlinerID" not in df.columns:
        return 0, []

    grouped = {}
    for i, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        name = str(row.get("Название", "")).strip()
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        grouped.setdefault(oid, []).append({
            "row_idx": int(i),
            "name": name,
            "name_key": name_key,
            "supplier": str(row.get("Поставщик", "")).strip(),
            "category": str(row_category(row)).strip(),
        })

    product_cache = load_onliner_product_cache()
    issues = []
    problem_ids = 0
    for oid, rows in grouped.items():
        if len(rows) < 2:
            continue
        distinct_name_map = {}
        for item in rows:
            key = str(item.get("name_key") or "").strip()
            if key and key not in distinct_name_map:
                distinct_name_map[key] = str(item.get("name") or "").strip()
        if len(distinct_name_map) < 2:
            continue

        confirmed_rows = []
        pending_rows = []
        for item in rows:
            if is_manually_confirmed_id(item.get("name", ""), oid):
                confirmed_rows.append(item)
            else:
                pending_rows.append(item)

        # Если текущий ID уже подтвержден вручную у части строк,
        # не тревожим их повторно: оставляем в проверке только остальные строки.
        if pending_rows:
            rows_for_review = pending_rows
        else:
            # Если все строки с этим ID уже вручную подтверждены, считаем конфликт обработанным.
            continue

        problem_ids += 1
        cached_info = product_cache.get(oid) if isinstance(product_cache, dict) else {}
        api_name = str((cached_info or {}).get("name", "")).strip()
        api_url = str((cached_info or {}).get("url", "")).strip()
        distinct_names = [n for n in distinct_name_map.values() if n]

        for item in rows_for_review:
            current_name = str(item.get("name") or "").strip()
            current_key = str(item.get("name_key") or "").strip()
            other_names = [n for k, n in distinct_name_map.items() if k != current_key and n]
            reason_parts = []
            if api_name:
                reason_parts.append(f"Текущий ID ведет на {api_name}")
            reason = f"Этот OnlinerID используется у {len(distinct_name_map)} разных товаров"
            if other_names:
                shown = ", ".join(other_names[:2])
                if len(other_names) > 2:
                    shown += ", ..."
                reason += f": {shown}"
            if confirmed_rows:
                reason += f". Уже подтверждено вручную: {len(confirmed_rows)}"
            reason_parts.append(reason)
            reason_label = ". ".join(part for part in reason_parts if part)
            issues.append({
                "row_idx": int(item.get("row_idx", -1)),
                "onliner_id": oid,
                "name": current_name,
                "supplier": str(item.get("supplier") or "").strip(),
                "category": str(item.get("category") or "").strip(),
                "api_name": api_name,
                "api_url": api_url,
                "score": 0.0,
                "reason": "duplicate_onliner_id",
                "reason_label": reason_label,
                "status": "mismatch",
                "status_label": "Одинаковый ID",
                "duplicate_id_count": int(problem_ids),
                "duplicate_row_count": int(len(rows)),
                "duplicate_name_count": int(len(distinct_name_map)),
                "other_names": other_names[:4],
                "needs_review": True,
            })

    issues.sort(key=lambda x: (str(x.get("onliner_id") or ""), str(x.get("name") or "").lower()))
    return int(problem_ids), issues


def apply_export_duplicate_id_filter(df, supplier_names=None):
    supplier_list = _normalize_supplier_name_list(supplier_names or [])
    if df is None or df.empty or not supplier_list:
        return df
    supplier_lookup = {name.strip().lower() for name in supplier_list if str(name or "").strip()}
    if not supplier_lookup:
        return df
    _, issues = _build_duplicate_onliner_id_issues(df)
    if not issues:
        return df
    drop_indexes = set()
    for issue in issues:
        supplier = str(issue.get("supplier") or "").strip().lower()
        row_idx = issue.get("row_idx")
        if supplier in supplier_lookup and isinstance(row_idx, int):
            drop_indexes.add(int(row_idx))
    if not drop_indexes:
        return df
    return df.drop(index=list(drop_indexes), errors="ignore").copy()


def apply_export_keep_lowest_price_per_onliner_id(df):
    if df is None or df.empty:
        return df
    id_col = "OnlinerID" if "OnlinerID" in df.columns else ("onliner_id" if "onliner_id" in df.columns else None)
    if not id_col:
        return df
    price_col = "Цена" if "Цена" in df.columns else ("price" if "price" in df.columns else None)
    temp = df.copy()
    temp["_oid_norm"] = temp[id_col].apply(normalize_onliner_id)
    has_id_mask = temp["_oid_norm"].astype(str) != ""
    if not has_id_mask.any():
        return df
    if price_col:
        raw_prices = temp[price_col].astype(str).str.replace("\xa0", "", regex=False).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
        temp["_price_num"] = pd.to_numeric(raw_prices, errors="coerce")
    else:
        temp["_price_num"] = np.nan
    keep_idx = set()
    for _, grp in temp[has_id_mask].groupby("_oid_norm", sort=False):
        grp_with_price = grp[grp["_price_num"].notna()]
        if not grp_with_price.empty:
            keep_idx.add(int(grp_with_price["_price_num"].idxmin()))
        else:
            keep_idx.add(int(grp.index[0]))
    drop_mask = has_id_mask & ~temp.index.isin(keep_idx)
    if not drop_mask.any():
        return df
    return df[~drop_mask].copy()


def _is_pc_export_row(row):
    name = str(row.get("Название", "") or row.get("product_name", "") or "").strip()
    low_name = name.lower()
    if _is_tgpc_pc_name(name):
        return True
    if low_name.startswith("компьютер "):
        return True
    if low_name.startswith("пэвм "):
        return True
    if low_name.startswith("системный блок "):
        return True
    if "iven" in low_name and "компьютер" in low_name:
        return True
    category = str(row.get("Категория", "") or row.get("category", "") or row_category(row) or "").strip().lower()
    if any(token in category for token in [
        "пэвм",
        "системный блок",
        "компьютер",
        "компьютеры / tgpc",
        "готовые решения tgpc",
    ]):
        return True
    link = str(row.get("Ссылка", "") or row.get("url", "") or "").strip().lower()
    if any(token in link for token in ["/desktoppc/", "/computer/", "/monoblock/", "/nettop/"]):
        return True
    onliner_name = str(row.get("Onliner", "") or row.get("onliner_name", "") or "").strip().lower()
    if "iven" in onliner_name and ("superpower" in onliner_name or "gaming" in onliner_name):
        return True
    return False


def apply_export_only_pc_filter(df, supplier_names=None):
    supplier_list = _normalize_supplier_name_list(supplier_names or [])
    if df is None or df.empty or not supplier_list:
        return df
    supplier_lookup = {name.strip().lower() for name in supplier_list if str(name or "").strip()}
    if not supplier_lookup:
        return df
    supplier_col = "Поставщик" if "Поставщик" in df.columns else ("supplier" if "supplier" in df.columns else None)
    if not supplier_col:
        return df
    keep_mask = df.apply(
        lambda row: str(row.get(supplier_col, "") or "").strip().lower() not in supplier_lookup or _is_pc_export_row(row),
        axis=1,
    )
    return df[keep_mask].copy()


@app.route("/api/check-duplicate-onliner-ids", methods=["POST"])
def api_check_duplicate_onliner_ids():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Сводный прайс не найден"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)
    if df.empty:
        return jsonify({
            "status": "ok",
            "problem_ids": 0,
            "problem_rows": 0,
            "items": [],
            "message": "В текущем прайсе нет строк для проверки.",
        })

    problem_ids, issues = _build_duplicate_onliner_id_issues(df)
    if not issues:
        return jsonify({
            "status": "ok",
            "problem_ids": 0,
            "problem_rows": 0,
            "items": [],
            "message": "Одинаковых OnlinerID у разных товаров не найдено.",
        })

    return jsonify({
        "status": "ok",
        "problem_ids": int(problem_ids),
        "problem_rows": int(len(issues)),
        "items": issues,
        "message": f"Найдено одинаковых OnlinerID: {problem_ids}. Строк для проверки: {len(issues)}.",
    })


@app.route("/api/verify-all-ids-start", methods=["POST"])
def api_verify_all_ids_start():
    global verify_all_ids_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    with VERIFY_ALL_IDS_LOCK:
        if verify_all_ids_status.get("running"):
            return jsonify({"status": "already_running"})
        verify_all_ids_status = {
            "running": True,
            "total": 0,
            "done": 0,
            "matched": 0,
            "mismatched": 0,
            "errors": 0,
            "items": [],
            "report_items": [],
            "started_at": int(time.time()),
            "finished_at": 0,
            "message": "Подготовка проверки ID...",
        }

    threading.Thread(target=_verify_all_ids_worker, args=(str(session_dir),), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/verify-all-ids-status")
def api_verify_all_ids_status():
    with VERIFY_ALL_IDS_LOCK:
        st = dict(verify_all_ids_status)
        st["items"] = list(st.get("items", []) or [])
        return jsonify(st)


@app.route("/api/validate-clean-ids-start", methods=["POST"])
def api_validate_clean_ids_start():
    global validate_clean_ids_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    with VALIDATE_CLEAN_IDS_LOCK:
        if validate_clean_ids_status.get("running"):
            return jsonify({"status": "already_running"})
        validate_clean_ids_status = {
            "running": True,
            "total": 0, "done": 0,
            "confirmed": 0, "cleared": 0, "skipped_api": 0, "queued": 0, "errors": 0,
            "mode": "api",
            "mode_label": "Onliner API",
            "skipped_label": "Пропуск = API не ответил, ID не меняли.",
            "started_at": int(time.time()),
            "finished_at": 0,
            "message": "Подготовка валидации...",
        }

    threading.Thread(target=_validate_clean_ids_worker, args=(str(session_dir),), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/validate-clean-ids-db-start", methods=["POST"])
def api_validate_clean_ids_db_start():
    global validate_clean_ids_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    with VALIDATE_CLEAN_IDS_LOCK:
        if validate_clean_ids_status.get("running"):
            return jsonify({"status": "already_running"})
        validate_clean_ids_status = {
            "running": True,
            "total": 0, "done": 0,
            "confirmed": 0, "cleared": 0, "skipped_api": 0, "queued": 0, "errors": 0,
            "mode": "db",
            "mode_label": "Локальная БД 150k",
            "skipped_label": "Пропуск = ID или имя не найдены в локальной БД, поэтому ID оставили без изменений.",
            "started_at": int(time.time()),
            "finished_at": 0,
            "message": "Подготовка локальной сверки...",
        }

    threading.Thread(target=_validate_clean_ids_db_worker, args=(str(session_dir),), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/validate-clean-ids-status")
def api_validate_clean_ids_status():
    with VALIDATE_CLEAN_IDS_LOCK:
        return jsonify(dict(validate_clean_ids_status))


@app.route("/api/cpu-review-queue-start", methods=["POST"])
def api_cpu_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    cpu_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_cpu = _looks_like_cpu_name(str(row.get("Название", "") or "").strip())
        if not (category == "Процессор" or looks_like_cpu):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        if not name:
            continue
        scanned += 1
        local_brand, local_model = _cpu_brand_model_key(name)
        if not local_brand or not local_model:
            no_model += 1
            cpu_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Процессор",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "cpu_brand": local_brand.upper() if local_brand else "",
                "cpu_model": local_model.upper() if local_model else "",
                "cpu_issue": "no_model",
                "cpu_issue_label": "Не удалось выделить модель CPU",
                "candidates": [],
            })
            continue
        candidates = _find_cpu_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            cpu_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Процессор",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "cpu_brand": local_brand.upper(),
                "cpu_model": local_model.upper(),
                "cpu_issue": "no_candidates",
                "cpu_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue
        queue[name_key] = {
            "name": name,
            "category": "Процессор",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "cpu_brand": local_brand.upper(),
            "cpu_model": local_model.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_model}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "cpu_brand_model_manual",
            "reason_label": "Процессор: совпадение только по производителю и модели. Подтверждение только вручную.",
        }
        cpu_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Процессор",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "cpu_brand": local_brand.upper(),
            "cpu_model": local_model.upper(),
            "cpu_issue": "queued",
            "cpu_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": cpu_report_items,
        "report_mode": "cpu",
        "report_title": "Отчёт CPU N-Tech",
        "report_subtitle": (
            f"Обработано CPU: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет товаров категории «Процессор» без ID. Сейчас CPU встречаются только внутри ПЭВМ/системных блоков.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "cpu",
                "report_title": "Отчёт CPU N-Tech",
                "report_subtitle": "В текущем прайсе CPU без ID не найдено.",
            })
        return jsonify(payload)
    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Процессоры N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": cpu_report_items,
            "report_mode": "cpu",
            "report_title": "Отчёт CPU N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/motherboard-review-queue-start", methods=["POST"])
def api_motherboard_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    board_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        if not name or not re.match(r"^\s*MB\s+", name, flags=re.IGNORECASE):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        board = _board_brand_model_key(name)
        local_brand = board.get("brand", "")
        local_model = board.get("model", "")
        if not local_brand or not local_model:
            no_model += 1
            board_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Материнская плата",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "board_brand": local_brand.upper() if local_brand else "",
                "board_model": local_model.upper() if local_model else "",
                "board_issue": "no_model",
                "board_issue_label": "Не удалось выделить модель платы",
                "candidates": [],
            })
            continue

        candidates = _find_board_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            board_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Материнская плата",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "board_brand": local_brand.upper(),
                "board_model": local_model.upper(),
                "board_issue": "no_candidates",
                "board_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Материнская плата",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "board_brand": local_brand.upper(),
            "board_model": local_model.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_model}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "board_brand_model_manual",
            "reason_label": "Материнская плата: совпадение по бренду и модели. Подтверждение только вручную.",
        }
        board_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Материнская плата",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "board_brand": local_brand.upper(),
            "board_model": local_model.upper(),
            "board_issue": "queued",
            "board_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": board_report_items,
        "report_mode": "board",
        "report_title": "Отчёт материнских плат N-Tech",
        "report_subtitle": (
            f"Обработано плат: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет материнских плат формата MB без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "board",
                "report_title": "Отчёт материнских плат N-Tech",
                "report_subtitle": "В текущем прайсе материнские платы без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Материнки N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": board_report_items,
            "report_mode": "board",
            "report_title": "Отчёт материнских плат N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/monitor-review-queue-start", methods=["POST"])
def api_monitor_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    monitor_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_monitor = bool(re.match(r'^\s*\d{2}(?:\.\d)?\s*"', name))
        if not name or not (category == "Монитор" or looks_like_monitor):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        monitor = _monitor_brand_model_key(name)
        local_brand = monitor.get("brand", "")
        local_model = monitor.get("model", "")
        if not local_brand or not local_model:
            no_model += 1
            monitor_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Монитор",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "monitor_brand": local_brand.upper() if local_brand else "",
                "monitor_model": monitor.get("model_text", ""),
                "monitor_issue": "no_model",
                "monitor_issue_label": "Не удалось выделить модель монитора",
                "candidates": [],
            })
            continue

        candidates = _find_monitor_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            monitor_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Монитор",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "monitor_brand": local_brand.upper(),
                "monitor_model": monitor.get("model_text", ""),
                "monitor_issue": "no_candidates",
                "monitor_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Монитор",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "monitor_brand": local_brand.upper(),
            "monitor_model": monitor.get("model_text", ""),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {monitor.get('model_text', '')}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "monitor_brand_model_manual",
            "reason_label": "Монитор: совпадение по бренду и модели. Подтверждение только вручную.",
        }
        monitor_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Монитор",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "monitor_brand": local_brand.upper(),
            "monitor_model": monitor.get("model_text", ""),
            "monitor_issue": "queued",
            "monitor_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": monitor_report_items,
        "report_mode": "monitor",
        "report_title": "Отчёт мониторов N-Tech",
        "report_subtitle": (
            f"Обработано мониторов: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет мониторов без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "monitor",
                "report_title": "Отчёт мониторов N-Tech",
                "report_subtitle": "В текущем прайсе мониторы без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Мониторы N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": monitor_report_items,
            "report_mode": "monitor",
            "report_title": "Отчёт мониторов N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/gpu-review-queue-start", methods=["POST"])
def api_gpu_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    gpu_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_gpu = bool(re.search(r"видеокарта|geforce|radeon|(?:^|[^a-z0-9])rtx\s*\d{4}|(?:^|[^a-z0-9])rx\s*\d{3,4}", name, flags=re.IGNORECASE))
        if not name or not (category == "Видеокарта" or looks_like_gpu):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        gpu = _gpu_brand_model_key(name)
        local_vendor = gpu.get("vendor", "")
        local_model = gpu.get("gpu_model", "")
        if not local_vendor or not local_model:
            no_model += 1
            gpu_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Видеокарта",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "gpu_vendor": local_vendor.upper() if local_vendor else "",
                "gpu_model": local_model.upper() if local_model else "",
                "gpu_sku": str(gpu.get("sku", "") or "").upper(),
                "gpu_issue": "no_model",
                "gpu_issue_label": "Не удалось выделить модель видеокарты",
                "candidates": [],
            })
            continue

        candidates = _find_gpu_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            gpu_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Видеокарта",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "gpu_vendor": local_vendor.upper(),
                "gpu_model": local_model.upper(),
                "gpu_sku": str(gpu.get("sku", "") or "").upper(),
                "gpu_issue": "no_candidates",
                "gpu_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Видеокарта",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "gpu_vendor": local_vendor.upper(),
            "gpu_model": local_model.upper(),
            "gpu_sku": str(gpu.get("sku", "") or "").upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_vendor.upper()} {local_model.upper()}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "gpu_brand_model_manual",
            "reason_label": "Видеокарта: совпадение по вендору, GPU и серии. Подтверждение только вручную.",
        }
        gpu_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Видеокарта",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "gpu_vendor": local_vendor.upper(),
            "gpu_model": local_model.upper(),
            "gpu_sku": str(gpu.get("sku", "") or "").upper(),
            "gpu_issue": "queued",
            "gpu_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": gpu_report_items,
        "report_mode": "gpu",
        "report_title": "Отчёт видеокарт N-Tech",
        "report_subtitle": (
            f"Обработано видеокарт: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет видеокарт без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "gpu",
                "report_title": "Отчёт видеокарт N-Tech",
                "report_subtitle": "В текущем прайсе видеокарты без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Видеокарты N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": gpu_report_items,
            "report_mode": "gpu",
            "report_title": "Отчёт видеокарт N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/ram-review-queue-start", methods=["POST"])
def api_ram_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    ram_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_ram = bool(
            re.match(r"^\s*ddr[345]\b", name, flags=re.IGNORECASE)
            and not re.search(r"\bпэвм\b|\bкомпьютер\b|\bsoc[-\s]|\bматерин", name, flags=re.IGNORECASE)
        )
        if not name or not (category == "Оперативная память" or looks_like_ram):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        ram = _ram_brand_model_key(name)
        local_brand = ram.get("brand", "")
        local_sku = ram.get("sku", "")
        if not local_brand or (not local_sku and not ram.get("capacity_gb")):
            no_model += 1
            ram_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Оперативная память",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "ram_brand": local_brand.upper() if local_brand else "",
                "ram_sku": local_sku.upper() if local_sku else "",
                "ram_issue": "no_model",
                "ram_issue_label": "Не удалось выделить модель памяти",
                "candidates": [],
            })
            continue

        candidates = _find_ram_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            ram_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Оперативная память",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "ram_brand": local_brand.upper(),
                "ram_sku": local_sku.upper(),
                "ram_issue": "no_candidates",
                "ram_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Оперативная память",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "ram_brand": local_brand.upper(),
            "ram_sku": local_sku.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_sku.upper()}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "ram_brand_model_manual",
            "reason_label": "Оперативная память: совпадение по бренду и коду модуля. Подтверждение только вручную.",
        }
        ram_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Оперативная память",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "ram_brand": local_brand.upper(),
            "ram_sku": local_sku.upper(),
            "ram_issue": "queued",
            "ram_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": ram_report_items,
        "report_mode": "ram",
        "report_title": "Отчёт оперативной памяти N-Tech",
        "report_subtitle": (
            f"Обработано памяти: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет оперативной памяти без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "ram",
                "report_title": "Отчёт оперативной памяти N-Tech",
                "report_subtitle": "В текущем прайсе оперативная память без ID не найдена.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Оперативка N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": ram_report_items,
            "report_mode": "ram",
            "report_title": "Отчёт оперативной памяти N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/ssd-review-queue-start", methods=["POST"])
def api_ssd_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    ssd_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        if not name:
            continue
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_ssd = bool(
            re.search(r"(?:^|[^a-z0-9])ssd(?=$|[^a-z0-9])|nvme|m\.?2|твердотельн", name, flags=re.IGNORECASE)
            and not re.search(r"\bпэвм\b|\bкомпьютер\b|\bноутбук\b", name, flags=re.IGNORECASE)
        )
        if not (category == "SSD" or looks_like_ssd):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        ssd = _ssd_brand_model_key(name)
        local_brand = ssd.get("brand", "")
        local_code = str(ssd.get("code", "") or "").strip()
        local_model = str(ssd.get("model", "") or "").strip()
        if not local_code and not local_brand:
            no_model += 1
            ssd_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "SSD",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "ssd_brand": local_brand.upper() if local_brand else "",
                "ssd_model": local_model.upper() if local_model else "",
                "ssd_code": "",
                "ssd_issue": "no_model",
                "ssd_issue_label": "Не удалось выделить бренд/модель SSD",
                "candidates": [],
            })
            continue

        candidates = _find_ssd_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            ssd_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "SSD",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "ssd_brand": local_brand.upper() if local_brand else "",
                "ssd_model": local_model.upper() if local_model else "",
                "ssd_code": local_code.upper(),
                "ssd_issue": "no_candidates",
                "ssd_issue_label": "Кандидаты по коду/модели в БД не найдены",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "SSD",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "ssd_brand": local_brand.upper() if local_brand else "",
            "ssd_model": local_model.upper() if local_model else "",
            "ssd_code": local_code.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_code.upper()}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "ssd_bracket_code_manual",
            "reason_label": "SSD: приоритет точному коду в скобках, fallback по бренду+модели/объёму. Подтверждение только вручную.",
        }
        ssd_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "SSD",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "ssd_brand": local_brand.upper() if local_brand else "",
            "ssd_model": local_model.upper() if local_model else "",
            "ssd_code": local_code.upper(),
            "ssd_issue": "queued",
            "ssd_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": ssd_report_items,
        "report_mode": "ssd",
        "report_title": "Отчёт SSD N-Tech",
        "report_subtitle": (
            f"Обработано SSD: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет SSD без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "ssd",
                "report_title": "Отчёт SSD N-Tech",
                "report_subtitle": "В текущем прайсе SSD без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"SSD N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": ssd_report_items,
            "report_mode": "ssd",
            "report_title": "Отчёт SSD N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/psu-review-queue-start", methods=["POST"])
def api_psu_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    psu_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_psu = bool(
            re.search(r"^\s*бп\b|блок\s*питания|80\s*plus|(?:^|[^a-z0-9])psu(?=$|[^a-z0-9])", name, flags=re.IGNORECASE)
            and re.search(r"\b\d{3,4}\s*w\b", name, flags=re.IGNORECASE)
        )
        if not name or not (category == "Блок питания" or looks_like_psu):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        psu = _psu_brand_model_key(name)
        local_brand = psu.get("brand", "")
        local_watt = psu.get("watt", "")
        local_code = str(psu.get("code", "") or "").upper()
        if not local_brand or not local_watt:
            no_model += 1
            psu_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Блок питания",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "psu_brand": local_brand.upper() if local_brand else "",
                "psu_model": (f"{local_watt}W" if local_watt else ""),
                "psu_code": local_code,
                "psu_issue": "no_model",
                "psu_issue_label": "Не удалось выделить бренд/мощность БП",
                "candidates": [],
            })
            continue

        candidates = _find_psu_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            psu_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Блок питания",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "psu_brand": local_brand.upper(),
                "psu_model": f"{local_watt}W",
                "psu_code": local_code,
                "psu_issue": "no_candidates",
                "psu_issue_label": "Бренд/мощность найдены, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Блок питания",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "psu_brand": local_brand.upper(),
            "psu_model": f"{local_watt}W",
            "psu_code": local_code,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_watt}W",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "psu_brand_power_manual",
            "reason_label": "Блок питания: строгий матч по бренду, мощности, 80 PLUS/модульности/коду. Подтверждение только вручную.",
        }
        psu_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Блок питания",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "psu_brand": local_brand.upper(),
            "psu_model": f"{local_watt}W",
            "psu_code": local_code,
            "psu_issue": "queued",
            "psu_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": psu_report_items,
        "report_mode": "psu",
        "report_title": "Отчёт блоков питания N-Tech",
        "report_subtitle": (
            f"Обработано БП: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет блоков питания без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "psu",
                "report_title": "Отчёт блоков питания N-Tech",
                "report_subtitle": "В текущем прайсе блоки питания без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Блоки питания N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": psu_report_items,
            "report_mode": "psu",
            "report_title": "Отчёт блоков питания N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/case-review-queue-start", methods=["POST"])
def api_case_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    case_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_case = _looks_like_case_name(name)
        if not name or not (category == "Корпус" or looks_like_case):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        case_meta = _case_brand_model_key(name)
        local_brand = case_meta.get("brand", "")
        local_code = str(case_meta.get("code", "") or "").upper()
        local_series = str(case_meta.get("series", "") or "").upper()
        if not local_brand:
            no_model += 1
            case_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Корпус",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "case_brand": local_brand.upper() if local_brand else "",
                "case_model": local_series,
                "case_code": local_code,
                "case_issue": "no_model",
                "case_issue_label": "Не удалось выделить бренд/серию корпуса",
                "candidates": [],
            })
            continue

        candidates = _find_case_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            case_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Корпус",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "case_brand": local_brand.upper(),
                "case_model": local_series,
                "case_code": local_code,
                "case_issue": "no_candidates",
                "case_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Корпус",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "case_brand": local_brand.upper(),
            "case_model": local_series,
            "case_code": local_code,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_series or local_code}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "case_brand_model_manual",
            "reason_label": "Корпус: строгий матч по бренду, серии/коду, форм-фактору и признаку с БП/без БП. Подтверждение только вручную.",
        }
        case_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Корпус",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "case_brand": local_brand.upper(),
            "case_model": local_series,
            "case_code": local_code,
            "case_issue": "queued",
            "case_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": case_report_items,
        "report_mode": "case",
        "report_title": "Отчёт корпусов N-Tech",
        "report_subtitle": (
            f"Обработано корпусов: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет корпусов без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "case",
                "report_title": "Отчёт корпусов N-Tech",
                "report_subtitle": "В текущем прайсе корпуса без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Корпуса N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": case_report_items,
            "report_mode": "case",
            "report_title": "Отчёт корпусов N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/hdd-review-queue-start", methods=["POST"])
def api_hdd_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    hdd_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks_like_hdd = _looks_like_hdd_name(name)
        if not name or not (category == "Жесткий диск" or looks_like_hdd):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        hdd_meta = _hdd_brand_model_key(name)
        local_brand = str(hdd_meta.get("brand", "") or "").strip()
        local_code = str(hdd_meta.get("code", "") or "").upper()
        local_capacity = str(hdd_meta.get("capacity", "") or "").strip()
        if not local_brand and not local_code:
            no_model += 1
            hdd_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Жесткий диск",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "hdd_brand": local_brand.upper() if local_brand else "",
                "hdd_code": "",
                "hdd_capacity": local_capacity,
                "hdd_issue": "no_model",
                "hdd_issue_label": "Не удалось выделить бренд/артикул HDD",
                "candidates": [],
            })
            continue

        candidates = _find_hdd_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            hdd_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Жесткий диск",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "hdd_brand": local_brand.upper() if local_brand else "",
                "hdd_code": local_code,
                "hdd_capacity": local_capacity,
                "hdd_issue": "no_candidates",
                "hdd_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Жесткий диск",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "hdd_brand": local_brand.upper() if local_brand else "",
            "hdd_code": local_code,
            "hdd_capacity": local_capacity,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_code or local_capacity}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "hdd_article_manual",
            "reason_label": "HDD: совпадение по бренду, артикулу в скобках, объёму и типу (внутр./внеш.). Подтверждение только вручную.",
        }
        hdd_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Жесткий диск",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "hdd_brand": local_brand.upper() if local_brand else "",
            "hdd_code": local_code,
            "hdd_capacity": local_capacity,
            "hdd_issue": "queued",
            "hdd_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": hdd_report_items,
        "report_mode": "hdd",
        "report_title": "Отчёт HDD N-Tech",
        "report_subtitle": (
            f"Обработано HDD: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет HDD без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "hdd",
                "report_title": "Отчёт HDD N-Tech",
                "report_subtitle": "В текущем прайсе HDD без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"HDD N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": hdd_report_items,
            "report_mode": "hdd",
            "report_title": "Отчёт HDD N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/cooler-review-queue-start", methods=["POST"])
def api_cooler_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    cooler_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        air_like = _looks_like_cooler_name(name)
        liq_like = _looks_like_liquid_cpu_cooling_name(name)
        if not name:
            continue
        if category == "Охлаждение" and not (air_like or liq_like):
            continue
        if not (category == "Кулер" or air_like or liq_like):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        cooler_meta = _cooler_brand_model_key(name)
        local_brand = str(cooler_meta.get("brand", "") or "").strip()
        local_code = str(cooler_meta.get("code", "") or "").upper()
        local_tdp = str(cooler_meta.get("tdp", "") or "").strip()
        if not local_brand and not local_code:
            no_model += 1
            cooler_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Охлаждение",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "cooler_brand": local_brand.upper() if local_brand else "",
                "cooler_code": "",
                "cooler_tdp": local_tdp,
                "cooler_issue": "no_model",
                "cooler_issue_label": "Не удалось выделить бренд/код охлаждения",
                "candidates": [],
            })
            continue

        candidates = _find_cooler_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            cooler_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Охлаждение",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "cooler_brand": local_brand.upper() if local_brand else "",
                "cooler_code": local_code,
                "cooler_tdp": local_tdp,
                "cooler_issue": "no_candidates",
                "cooler_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Охлаждение",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "cooler_brand": local_brand.upper() if local_brand else "",
            "cooler_code": local_code,
            "cooler_tdp": local_tdp,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_code or local_tdp}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "cooler_article_manual",
            "reason_label": "Охлаждение (кулер / СЖО): бренд, артикул, TDP, цвет. Подтверждение только вручную.",
        }
        cooler_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Охлаждение",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "cooler_brand": local_brand.upper() if local_brand else "",
            "cooler_code": local_code,
            "cooler_tdp": local_tdp,
            "cooler_issue": "queued",
            "cooler_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": cooler_report_items,
        "report_mode": "cooler",
        "report_title": "Отчёт охлаждения N-Tech",
        "report_subtitle": (
            f"Обработано позиций охлаждения: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет позиций охлаждения без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "cooler",
                "report_title": "Отчёт охлаждения N-Tech",
                "report_subtitle": "В текущем прайсе охлаждение без ID не найдено.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Охлаждение N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": cooler_report_items,
            "report_mode": "cooler",
            "report_title": "Отчёт охлаждения N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/printer-review-queue-start", methods=["POST"])
def api_printer_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    printer_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        looks = _looks_like_printer_or_mfp_name(name)
        if not name:
            continue
        if not (category == "Принтер и МФУ" or looks):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        pm_meta = _printer_mfp_brand_model_key(name)
        local_brand = str(pm_meta.get("brand", "") or "").strip()
        local_article = str(pm_meta.get("article", "") or "").strip()
        local_model = str(pm_meta.get("model_display", "") or "").strip()
        local_mc = str(pm_meta.get("model_compact", "") or "").strip()
        if not local_brand and not local_article and len(local_mc) < 5:
            no_model += 1
            printer_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Принтер и МФУ",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "printer_brand": local_brand.upper() if local_brand else "",
                "printer_article": local_article.upper() if local_article else "",
                "printer_model": local_model,
                "printer_issue": "no_model",
                "printer_issue_label": "Не удалось выделить бренд / модель / артикул принтера или МФУ",
                "candidates": [],
            })
            continue

        candidates = _find_printer_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        if not candidates:
            no_candidates += 1
            printer_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Принтер и МФУ",
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "printer_brand": local_brand.upper() if local_brand else "",
                "printer_article": local_article.upper() if local_article else "",
                "printer_model": local_model,
                "printer_issue": "no_candidates",
                "printer_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": "Принтер и МФУ",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "printer_brand": local_brand.upper() if local_brand else "",
            "printer_article": local_article.upper() if local_article else "",
            "printer_model": local_model,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_model or local_article}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "printer_article_manual",
            "reason_label": "Принтер / МФУ: бренд, модель, артикул в скобках. Подтверждение только вручную.",
        }
        printer_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": "Принтер и МФУ",
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "printer_brand": local_brand.upper() if local_brand else "",
            "printer_article": local_article.upper() if local_article else "",
            "printer_model": local_model,
            "printer_issue": "queued",
            "printer_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": printer_report_items,
        "report_mode": "printer",
        "report_title": "Отчёт принтеров и МФУ N-Tech",
        "report_subtitle": (
            f"Обработано принтеров и МФУ: {scanned}. "
            f"В очереди: {queued}, без модели: {no_model}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_model": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет принтеров или МФУ без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "printer",
                "report_title": "Отчёт принтеров и МФУ N-Tech",
                "report_subtitle": "В текущем прайсе принтеры / МФУ без ID не найдены.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Принтеры и МФУ N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без модели: {no_model}." if no_model else "")
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_model + no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": printer_report_items,
            "report_mode": "printer",
            "report_title": "Отчёт принтеров и МФУ N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/peripheral-review-queue-start", methods=["POST"])
def api_peripheral_review_queue_start():
    global autofill_iven_status
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Нет данных"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if df.empty:
        return jsonify({"status": "error", "message": "Прайс пуст"}), 400

    queue = load_review_queue()
    scanned = 0
    queued = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    ntech_supplier_names = {"N-TECH", "NTECH"}
    now_ts = int(time.time())
    peripheral_report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip().upper()
        if supplier not in ntech_supplier_names:
            skipped_non_ntech += 1
            continue
        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        if not name:
            continue
        if category not in {"Клавиатура", "Мышь", "Наушники", "Акустика"} and not _looks_like_peripheral_name(name):
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if oid:
            skipped_with_id += 1
            continue

        scanned += 1
        candidates = _find_peripheral_review_candidates(name, top_n=5)
        name_key = _normalize_name_key(name)
        if not name_key:
            continue
        report_category = category if category in {"Клавиатура", "Мышь", "Наушники", "Акустика"} else "Периферия"
        if not candidates:
            no_candidates += 1
            peripheral_report_items.append({
                "name": name,
                "row_idx": int(row_idx),
                "category": report_category,
                "supplier": str(row.get("Поставщик", "") or "").strip(),
                "peripheral_issue": "no_candidates",
                "peripheral_issue_label": "Кандидатов в БД не найдено",
                "candidates": [],
            })
            continue

        queue[name_key] = {
            "name": name,
            "category": report_category,
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": name,
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "peripheral_manual",
            "reason_label": "Периферия N-Tech: кандидаты найдены, требуется ручное подтверждение.",
        }
        peripheral_report_items.append({
            "name": name,
            "row_idx": int(row_idx),
            "category": report_category,
            "supplier": str(row.get("Поставщик", "") or "").strip(),
            "peripheral_issue": "queued",
            "peripheral_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": str((candidates[0] or {}).get("source", "") or "").strip() if candidates else "",
            "candidates": list(candidates),
        })
        queued += 1

    save_review_queue(queue)
    report_payload = {
        "matches": [],
        "no_match": peripheral_report_items,
        "report_mode": "peripheral",
        "report_title": "Отчёт периферии N-Tech",
        "report_subtitle": (
            f"Обработано позиций периферии: {scanned}. "
            f"В очереди: {queued}, без кандидатов: {no_candidates}."
        ),
    }
    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_candidates": 0,
            "skipped_with_id": int(skipped_with_id),
            "skipped_non_ntech": int(skipped_non_ntech),
            "message": "В текущем прайсе N-Tech нет периферии без ID.",
            **report_payload,
        }
        with AUTOFILL_IVEN_LOCK:
            autofill_iven_status.update({
                "running": False,
                "total": 0,
                "done": 0,
                "applied": 0,
                "skipped": 0,
                "percent": 100,
                "started_at": now_ts,
                "finished_at": int(time.time()),
                "message": payload["message"],
                "matches": [],
                "no_match": [],
                "report_mode": "peripheral",
                "report_title": "Отчёт периферии N-Tech",
                "report_subtitle": "В текущем прайсе периферия без ID не найдена.",
            })
        return jsonify(payload)

    payload = {
        "status": "ok",
        "scanned": int(scanned),
        "queued": int(queued),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "message": (
            f"Периферия N-Tech: в ручную очередь добавлено {queued}."
            + (f" Без кандидатов: {no_candidates}." if no_candidates else "")
        ),
        **report_payload,
    }
    with AUTOFILL_IVEN_LOCK:
        autofill_iven_status.update({
            "running": False,
            "total": int(scanned),
            "done": int(scanned),
            "applied": 0,
            "skipped": int(no_candidates),
            "percent": 100,
            "started_at": now_ts,
            "finished_at": int(time.time()),
            "message": payload["message"],
            "matches": [],
            "no_match": peripheral_report_items,
            "report_mode": "peripheral",
            "report_title": "Отчёт периферии N-Tech",
            "report_subtitle": report_payload["report_subtitle"],
        })
    return jsonify(payload)


@app.route("/api/review-queue")
def api_review_queue():
    session_dir = session.get("session_dir")
    queue = load_review_queue()
    if not queue:
        return jsonify({"items": []})

    # Если есть активная сессия — обогащаем актуальными row_idx из текущего DataFrame
    result = []
    stale_keys = set()
    if session_dir:
        try:
            df = read_consolidated_df(session_dir)
            name_to_row = {}
            name_to_has_id = {}
            for i, row in df.iterrows():
                nk = _normalize_name_key(str(row.get("Название", "")))
                if nk:
                    name_to_row[nk] = int(i)
                    name_to_has_id[nk] = bool(normalize_onliner_id(row.get("OnlinerID", "")))
        except Exception:
            name_to_row = {}
            name_to_has_id = {}
    else:
        name_to_row = {}
        name_to_has_id = {}

    for name_key, entry in queue.items():
        if name_to_has_id.get(name_key):
            stale_keys.add(name_key)
            continue
        item = dict(entry)
        item["name_key"] = name_key
        item["row_idx"] = name_to_row.get(name_key)
        result.append(item)

    if stale_keys:
        for name_key in stale_keys:
            queue.pop(name_key, None)
        save_review_queue(queue)

    result.sort(key=lambda x: x.get("added_at", 0), reverse=True)
    return jsonify({"items": result})


@app.route("/api/review-queue-pick", methods=["POST"])
def api_review_queue_pick():
    payload = request.get_json(silent=True) or {}
    name_key = str(payload.get("name_key", "")).strip()
    oid = normalize_onliner_id(payload.get("onliner_id", ""))
    url = str(payload.get("url", "")).strip()
    name = str(payload.get("name", "")).strip()

    if not name_key:
        return jsonify({"status": "error", "message": "name_key обязателен"}), 400

    queue = load_review_queue()
    entry = queue.get(name_key, {})
    if not name:
        name = str(entry.get("name", "")).strip()

    if oid:
        # Пользователь выбрал кандидата — сохраняем в manual_bindings
        manual_bindings = load_manual_id_bindings()
        manual_bindings[name_key] = {"id": oid, "url": url}
        save_manual_id_bindings(manual_bindings)

        # Применяем к текущей сессии, если она есть
        session_dir = session.get("session_dir")
        if session_dir:
            try:
                df = read_consolidated_df(session_dir)
                if "OnlinerID" not in df.columns:
                    df["OnlinerID"] = ""
                if "Ссылка" not in df.columns:
                    df["Ссылка"] = ""
                for i, row in df.iterrows():
                    nk = _normalize_name_key(str(row.get("Название", "")))
                    if nk == name_key:
                        df.at[i, "OnlinerID"] = oid
                        if url:
                            df.at[i, "Ссылка"] = url
                write_consolidated_df(session_dir, df)
                write_consolidated_json(df, Path(session_dir) / "consolidated.json")
                append_id_change_journal({
                    "ts": int(time.time()),
                    "action": "review_queue_pick",
                    "source": "api_review_queue_pick",
                    "changes": [{"name": name, "new_onliner_id": oid, "new_url": url}],
                })
            except Exception:
                pass

    # Убираем из очереди (независимо от того, выбрал или пропустил)
    queue.pop(name_key, None)
    save_review_queue(queue)
    return jsonify({"status": "ok", "remaining": len(queue)})


@app.route("/api/review-queue-clear", methods=["POST"])
def api_review_queue_clear():
    save_review_queue({})
    return jsonify({"status": "ok"})


@app.route("/api/categories")
def api_categories():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"categories": []})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"categories": []})

    df = read_consolidated_df(session_dir)
    if "Название" not in df.columns:
        return jsonify({"categories": []})

    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)
    overrides = load_category_overrides()
    category_counts = {}
    for category in df.apply(lambda row: row_category(row, overrides), axis=1):
        category_counts[category] = category_counts.get(category, 0) + 1

    items = [
        {"name": name, "count": count}
        for name, count in sorted(category_counts.items(), key=lambda x: _category_sort_key(x[0]))
    ]
    return jsonify({"categories": items})


@app.route("/api/category-catalog")
def api_category_catalog():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"categories": CATEGORY_PRIORITY})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    all_cats = set(CATEGORY_PRIORITY)
    overrides = load_category_overrides()
    all_cats.update(v for v in overrides.values() if str(v).strip())
    all_cats.update(k for k in load_category_markups().keys() if str(k).strip())
    if cons_path.exists():
        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df, overrides)
        for _, row in df.iterrows():
            all_cats.add(row_category(row, overrides))
    return jsonify({"categories": sorted(all_cats, key=_category_sort_key)})


@app.route("/api/suppliers")
def api_suppliers():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"suppliers": []})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"suppliers": []})
    df = read_consolidated_df(session_dir)
    suppliers = sorted({str(s).strip() for s in df.get("Поставщик", pd.Series(dtype=str)).dropna().tolist() if str(s).strip()})
    return jsonify({"suppliers": suppliers})


@app.route("/api/supplier-categories")
def api_supplier_categories():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"categories": []})
    supplier = str(request.args.get("supplier", "")).strip()
    if not supplier:
        return jsonify({"categories": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"categories": []})

    df = read_consolidated_df(session_dir)
    if "Поставщик" not in df.columns:
        return jsonify({"categories": []})
    df = df[df["Поставщик"].astype(str).str.strip() == supplier]
    df = ensure_category_column(df)
    visibility_map = load_visibility_map(session_dir)
    hidden_set = set(visibility_map.get(supplier, []))

    counts = {}
    for _, row in df.iterrows():
        cat = row_category(row)
        counts[cat] = counts.get(cat, 0) + 1

    items = []
    for name, count in counts.items():
        items.append({"name": name, "count": count, "hidden": name in hidden_set})
    items.sort(key=lambda x: (1 if x.get("hidden") else 0, _category_sort_key(str(x.get("name", "")).strip())))
    return jsonify({"status": "ok", "categories": items})


@app.route("/api/category-visibility", methods=["POST"])
def api_category_visibility():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400

    payload = request.get_json(silent=True) or {}
    supplier = str(payload.get("supplier", "")).strip()
    categories = payload.get("categories", [])
    hidden = bool(payload.get("hidden", True))

    if not supplier:
        return jsonify({"status": "error", "message": "Поставщик не выбран"}), 400
    if not isinstance(categories, list):
        return jsonify({"status": "error", "message": "Некорректный список категорий"}), 400

    categories = [str(x).strip() for x in categories if str(x).strip()]
    if not categories:
        return jsonify({"status": "error", "message": "Категории не выбраны"}), 400

    visibility_map = load_visibility_map(session_dir)
    hidden_set = set(visibility_map.get(supplier, []))

    if hidden:
        hidden_set.update(categories)
    else:
        hidden_set.difference_update(categories)

    if hidden_set:
        visibility_map[supplier] = sorted(hidden_set, key=_category_sort_key)
    else:
        visibility_map.pop(supplier, None)

    save_visibility_map(session_dir, visibility_map)
    categories_out = [{"name": name, "hidden": True} for name in hidden_set]
    categories_out.sort(key=lambda x: (1 if x.get("hidden") else 0, _category_sort_key(str(x.get("name", "")).strip())))
    return jsonify({
        "status": "ok",
        "supplier": supplier,
        "hidden": hidden,
        "categories": categories_out,
    })


@app.route("/api/apply-markup", methods=["POST"])
def api_apply_markup():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    cons_json_path = Path(session_dir) / "consolidated.json"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "No data"})

    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    percent = payload.get("percent", None)
    threshold = payload.get("threshold", 0)
    min_profit = payload.get("min_profit", 0)
    no_discount_percent = payload.get("no_discount_percent", 0)
    base_mode = str(payload.get("base_mode", "wholesale")).strip().lower()
    if base_mode not in {"wholesale", "onliner_min", "onliner_avg", "onliner_max"}:
        base_mode = "wholesale"
    if not isinstance(categories, list) or not categories:
        return jsonify({"status": "error", "message": "Категории не выбраны"})
    try:
        percent = float(percent)
    except Exception:
        return jsonify({"status": "error", "message": "Некорректный процент"})
    try:
        threshold = float(threshold)
    except Exception:
        return jsonify({"status": "error", "message": "Некорректный порог опта"})
    try:
        min_profit = float(min_profit)
    except Exception:
        return jsonify({"status": "error", "message": "Некорректная мин. прибыль"})
    try:
        no_discount_percent = float(no_discount_percent)
    except Exception:
        return jsonify({"status": "error", "message": "Некорректный процент для цены без скидки"})
    if percent < 0:
        return jsonify({"status": "error", "message": "Процент не может быть отрицательным"})
    if threshold < 0:
        return jsonify({"status": "error", "message": "Порог опта не может быть отрицательным"})
    if min_profit < 0:
        return jsonify({"status": "error", "message": "Мин. прибыль не может быть отрицательной"})
    if no_discount_percent < 0:
        return jsonify({"status": "error", "message": "Процент цены без скидки не может быть отрицательным"})

    df = read_consolidated_df(session_dir)
    if "Название" not in df.columns or "Цена" not in df.columns:
        return jsonify({"status": "error", "message": "В файле нет нужных колонок"})
    if "РРЦ" not in df.columns:
        df["РРЦ"] = ""
    if "Цена без скидки" not in df.columns:
        df["Цена без скидки"] = ""
    df["РРЦ"] = df["РРЦ"].astype("object")
    df["Цена без скидки"] = df["Цена без скидки"].astype("object")
    df = ensure_category_column(df)

    selected = set(str(c).strip() for c in categories if str(c).strip())
    market_map = {}
    market_checked = 0
    if base_mode in {"onliner_min", "onliner_avg", "onliner_max"}:
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
        # Protect against extremely heavy external checks on huge selections.
        unique_ids = list(dict.fromkeys(ids))[:400]
        market_checked = len(unique_ids)
        market_map = get_onliner_market_stats_bulk(unique_ids, max_workers=22, id_hints=id_hints_bulk)

    updated = 0
    eligible = 0
    missing_market = 0
    for i, row in df.iterrows():
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
            percent,
            threshold=threshold,
            min_profit=min_profit,
            no_discount_percent=no_discount_percent,
        )
        df.at[i, "РРЦ"] = rrc
        df.at[i, "Цена без скидки"] = no_discount_price
        updated += 1

    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, cons_json_path)
    # Запоминаем последнюю наценку для выбранных категорий.
    markups = load_category_markups()
    for c in selected:
        markups[c] = {
            "percent": percent,
            "threshold": threshold,
            "min_profit": min_profit,
            "no_discount_percent": no_discount_percent,
            "base_mode": base_mode,
        }
    save_category_markups(markups)
    return jsonify({
        "status": "ok",
        "updated": updated,
        "eligible": eligible,
        "total": len(df),
        "percent": percent,
        "threshold": threshold,
        "min_profit": min_profit,
        "no_discount_percent": no_discount_percent,
        "base_mode": base_mode,
        "market_checked": market_checked,
        "missing_market": missing_market,
    })


@app.route("/api/markup-preview", methods=["POST"])
def api_markup_preview():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": []})

    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    percent = payload.get("percent", 0)
    limit = payload.get("limit", 8)

    try:
        percent = float(percent)
    except Exception:
        percent = 0.0
    try:
        limit = int(limit)
    except Exception:
        limit = 8
    limit = max(1, min(limit, 20))

    selected = {str(c).strip() for c in categories if str(c).strip()}
    if not selected:
        return jsonify({"items": []})

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)
    if "Название" not in df.columns or "Цена" not in df.columns:
        return jsonify({"items": []})

    items = []
    for i, row in df.iterrows():
        category = row_category(row)
        if category not in selected:
            continue
        price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        if pd.isna(price):
            continue
        old_rrc = pd.to_numeric(row.get("РРЦ", np.nan), errors="coerce")
        calc_rrc = round_price_to_90(float(price) * (1.0 + percent / 100.0))
        items.append({
            "category": category,
            "name": str(row.get("Название", "")),
            "price": round(float(price), 2),
            "old_rrc": "" if pd.isna(old_rrc) else round(float(old_rrc), 2),
            "new_rrc": round(float(calc_rrc), 2),
        })
        if len(items) >= limit:
            break

    return jsonify({"items": items})


@app.route("/api/category-override-items")
def api_category_override_items():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": []})

    query = str(request.args.get("q", "")).strip().lower()
    limit = int(request.args.get("limit", 40) or 40)
    limit = max(1, min(limit, 200))

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    if "Название" not in df.columns:
        return jsonify({"items": []})

    overrides = load_category_overrides()
    result = []
    for _, row in df.iterrows():
        name = str(row.get("Название", ""))
        if not name:
            continue
        if query and query not in name.lower():
            continue
        key = build_item_category_key(row)
        auto_cat = infer_category(name)
        eff_cat = row_category(row, overrides)
        result.append({
            "key": key,
            "name": name,
            "supplier": str(row.get("Поставщик", "")),
            "auto_category": auto_cat,
            "category": eff_cat,
            "manual": (eff_cat != auto_cat),
        })
        if len(result) >= limit:
            break

    return jsonify({"items": result})


@app.route("/api/category-override-set", methods=["POST"])
def api_category_override_set():
    session_dir = session.get("session_dir")
    payload = request.get_json(silent=True) or {}
    item_key = str(payload.get("item_key", "")).strip()
    target_category = str(payload.get("target_category", "")).strip()

    if not item_key:
        return jsonify({"status": "error", "message": "Товар не выбран"})
    if not target_category:
        return jsonify({"status": "error", "message": "Категория не выбрана"})

    overrides = load_category_overrides()
    overrides[item_key] = target_category

    if session_dir:
        cons_path = Path(session_dir) / "consolidated_price.xlsx"
        if cons_path.exists():
            df = read_consolidated_df(session_dir)
            df = ensure_category_column(df, overrides)
            changed = 0
            for i, row in df.iterrows():
                keys = set(build_item_category_keys(row))
                if item_key in keys:
                    df.at[i, "Категория"] = target_category
                    for k in keys:
                        overrides[k] = target_category
                    changed += 1
            if changed:
                write_consolidated_df(session_dir, df)
                write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    save_category_overrides(overrides)
    return jsonify({"status": "ok"})


@app.route("/api/category-preview-items", methods=["POST"])
def api_category_preview_items():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": []})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": []})

    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    with_market = bool(payload.get("with_market", False))
    allow_stale_market = bool(payload.get("allow_stale_market", True))
    try:
        limit = int(payload.get("limit", 4000))
    except Exception:
        limit = 4000
    limit = max(1, min(limit, 10000))
    try:
        max_market_checks = int(payload.get("max_market_checks", 300))
    except Exception:
        max_market_checks = 300
    max_market_checks = max(1, min(max_market_checks, 800))
    selected = {str(c).strip() for c in categories if str(c).strip()}
    if not selected:
        return jsonify({"items": []})

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)

    overrides = load_category_overrides()
    items = []
    onliner_ids = []
    for i, row in df.iterrows():
        category = row_category(row, overrides)
        if category not in selected:
            continue
        price = pd.to_numeric(row.get("Цена", np.nan), errors="coerce")
        rrc = pd.to_numeric(row.get("РРЦ", np.nan), errors="coerce")
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if with_market and oid:
            onliner_ids.append(oid)
        item = {
            "key": build_item_category_key(row),
            "row_idx": int(i),
            "onliner_id": oid,
            "name": str(row.get("Название", "")),
            "supplier": str(row.get("Поставщик", "")),
            "category": category,
            "price": "" if pd.isna(price) else round(float(price), 2),
            "rrc": "" if pd.isna(rrc) else round(float(rrc), 2),
        }
        items.append(item)
        if len(items) >= limit:
            break
    market_map = {}
    market_checked = 0
    preview_row_count = len(items)
    rows_with_onliner_id = sum(1 for it in items if str(it.get("onliner_id") or "").strip())
    market_unique_onliner_ids = 0
    if with_market and onliner_ids:
        unique_ids = list(dict.fromkeys(onliner_ids))
        if not allow_stale_market:
            unique_ids = unique_ids[:max_market_checks]
        market_unique_onliner_ids = len(unique_ids)
        market_checked = market_unique_onliner_ids
        cache = load_onliner_market_cache()
        for oid in unique_ids:
            market_map[oid] = get_onliner_market_stats_from_cache_only(oid, cache=cache, allow_stale=allow_stale_market)
    missing_market = 0
    missing_market_ids = set()
    no_onliner_id = 0
    for it in items:
        oid = it.get("onliner_id", "")
        stats = market_map.get(oid, {}) if oid else {}
        mmin = stats.get("min")
        mavg = stats.get("avg")
        mmax = stats.get("max")
        if with_market and not oid:
            no_onliner_id += 1
        if with_market and oid and (mmin is None and mavg is None):
            missing_market += 1
            missing_market_ids.add(oid)
        it["market_min"] = "" if mmin is None else round(float(mmin), 2)
        it["market_avg"] = "" if mavg is None else round(float(mavg), 2)
        it["market_max"] = "" if mmax is None else round(float(mmax), 2)
        it["market_offers"] = int(stats.get("offers", 0) or 0) if stats else 0
        it["min_competitors"] = int(stats.get("min_competitors", 0) or 0) if stats else 0
        it["avg_competitors"] = int(stats.get("avg_competitors", 0) or 0) if stats else 0

    items.sort(key=lambda x: (x["category"], x["name"].lower()))
    return jsonify({
        "items": items,
        "preview_row_count": preview_row_count,
        "market_rows_with_onliner_id": rows_with_onliner_id,
        "market_unique_onliner_ids": market_unique_onliner_ids,
        "market_checked": market_checked,
        "missing_market": missing_market,
        "missing_market_ids": len(missing_market_ids),
        "no_onliner_id": no_onliner_id,
    })


def _market_refresh_worker(session_dir, categories):
    try:
        cons_path = Path(session_dir) / "consolidated_price.xlsx"
        if not cons_path.exists():
            with MARKET_REFRESH_LOCK:
                market_refresh_status.update({"running": False, "finished_at": int(time.time())})
            return

        df = read_consolidated_df(session_dir)
        df = ensure_category_column(df)
        selected = {str(c).strip() for c in categories if str(c).strip()}
        if selected:
            df = df[df.apply(lambda r: row_category(r) in selected, axis=1)]

        cat_to_ids = {}
        for _, row in df.iterrows():
            cat = row_category(row)
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            cat_to_ids.setdefault(cat, set()).add(oid)

        all_ids = sorted(set().union(*cat_to_ids.values())) if cat_to_ids else []
        with MARKET_REFRESH_LOCK:
            market_refresh_status["total"] = len(all_ids)
            market_refresh_status["done"] = 0
            market_refresh_status["success"] = 0
            market_refresh_status["errors"] = 0
            market_refresh_status["recent_errors"] = []
            market_refresh_status["categories"] = {
                cat: {"done": 0, "total": len(ids), "percent": 0, "errors": 0, "recent_errors": []}
                for cat, ids in cat_to_ids.items()
            }

        cache = load_onliner_market_cache()
        now = int(time.time())
        id_to_cats = {}
        for cat, ids in cat_to_ids.items():
            for oid in ids:
                id_to_cats.setdefault(oid, []).append(cat)

        id_hints = {}
        for _, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid or oid in id_hints:
                continue
            id_hints[oid] = {
                "name": str(row.get("Название", "") or ""),
                "category": row_category(row),
            }

        def _fetch_market_for_refresh(oid):
            h = id_hints.get(oid) or {}
            return fetch_onliner_market_stats(
                oid,
                product_name=str(h.get("name", "") or ""),
                category_name=str(h.get("category", "") or ""),
            )

        success_count = 0
        error_count = 0
        with ThreadPoolExecutor(max_workers=MARKET_REFRESH_POOL_WORKERS) as ex:
            fut_to_oid = {ex.submit(_fetch_market_for_refresh, oid): oid for oid in all_ids}
            done_count = 0
            for fut in as_completed(fut_to_oid):
                oid = fut_to_oid[fut]
                try:
                    stats = fut.result()
                except Exception:
                    stats = {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0, "_error": True}
                had_values_before = market_stats_has_values(cache.get(oid))
                has_values_now = market_stats_has_values(stats)
                error_reason = str(stats.get("_error_reason", "") or "").strip()
                if has_values_now:
                    cache[oid] = {"updated_at": now, **stats}
                    success_count += 1
                elif not had_values_before:
                    cache[oid] = {"updated_at": now, **stats}
                    error_count += 1
                else:
                    error_count += 1
                done_count += 1
                with MARKET_REFRESH_LOCK:
                    market_refresh_status["done"] = done_count
                    market_refresh_status["success"] = success_count
                    market_refresh_status["errors"] = error_count
                    for cat in id_to_cats.get(oid, []):
                        st = market_refresh_status["categories"].get(cat)
                        if not st:
                            continue
                        st["done"] += 1
                        st["percent"] = int(round((st["done"] / max(st["total"], 1)) * 100))
                        if not has_values_now:
                            st["errors"] = int(st.get("errors", 0)) + 1
                            if error_reason:
                                line = f"{cat}: {oid} -> {error_reason}"
                                recent = list(st.get("recent_errors", []) or [])
                                recent.append(line)
                                st["recent_errors"] = recent[-5:]
                                all_recent = list(market_refresh_status.get("recent_errors", []) or [])
                                all_recent.append(line)
                                market_refresh_status["recent_errors"] = all_recent[-12:]

        save_onliner_market_cache(cache)
    finally:
        with MARKET_REFRESH_LOCK:
            market_refresh_status["running"] = False
            market_refresh_status["finished_at"] = int(time.time())


def _collect_known_onliner_ids(max_ids=AUTO_REFRESH_MAX_IDS, session_dir=None):
    ids = []
    # 0) Current consolidated session IDs (preferred, all categories in current price).
    try:
        sdir = str(session_dir or "").strip()
        if sdir:
            cons_path = Path(sdir) / "consolidated_price.xlsx"
            if cons_path.exists():
                df = read_consolidated_df(sdir)
                for _, row in df.iterrows():
                    oid = normalize_onliner_id(row.get("OnlinerID", ""))
                    if oid:
                        ids.append(oid)
    except Exception:
        pass
    # 1) existing market cache ids
    cache = load_onliner_market_cache()
    ids.extend(cache.keys())
    # 2) id cache ids
    id_cache = load_id_cache()
    if isinstance(id_cache, dict):
        for _, rec in id_cache.items():
            if not isinstance(rec, dict):
                continue
            oid = normalize_onliner_id(rec.get("id", ""))
            if oid:
                ids.append(oid)
    out = []
    seen = set()
    for oid in ids:
        if oid and oid not in seen:
            seen.add(oid)
            out.append(oid)
        if len(out) >= max_ids:
            break
    return out


def _market_id_hints_from_session(session_dir):
    """Первая строка прайса по каждому OnlinerID → подсказки для B2B-поиска раздела/производителя."""
    hints = {}
    try:
        sdir = str(session_dir or "").strip()
        if not sdir:
            return hints
        cons_path = Path(sdir) / "consolidated_price.xlsx"
        if not cons_path.exists():
            return hints
        df = read_consolidated_df(sdir)
        df = ensure_category_column(df)
        for _, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid or oid in hints:
                continue
            hints[oid] = {
                "name": str(row.get("Название", "") or ""),
                "category": row_category(row),
            }
    except Exception:
        pass
    return hints


def _auto_market_refresh_loop():
    # Runs while app process is alive.
    while True:
        try:
            settings = load_auto_refresh_settings()
            if not settings.get("enabled"):
                time.sleep(AUTO_REFRESH_POLL_SEC)
                continue

            with MARKET_REFRESH_LOCK:
                manual_running = bool(market_refresh_status.get("running"))
            if manual_running:
                time.sleep(AUTO_REFRESH_POLL_SEC)
                continue

            interval_hours = int(settings.get("interval_hours", 12) or 12)
            if interval_hours not in AUTO_REFRESH_ALLOWED_HOURS:
                interval_hours = 12
            now = int(time.time())
            last_run = int(settings.get("last_run_ts", 0) or 0)
            due = (last_run <= 0) or (now - last_run >= interval_hours * 3600)
            if not due:
                time.sleep(AUTO_REFRESH_POLL_SEC)
                continue

            ids = _collect_known_onliner_ids(session_dir=LAST_ACTIVE_SESSION_DIR)
            if not ids:
                settings["last_run_ts"] = now
                settings["last_status"] = "idle"
                settings["last_count"] = 0
                settings["last_message"] = "Нет товаров с OnlinerID для автообновления."
                save_auto_refresh_settings(settings)
                time.sleep(AUTO_REFRESH_POLL_SEC)
                continue

            settings["last_started_ts"] = now
            settings["last_status"] = "running"
            settings["last_message"] = f"Автообновление запущено, товаров: {len(ids)}"
            save_auto_refresh_settings(settings)

            # refresh in bounded batches without touching UI status
            cache = load_onliner_market_cache()
            auto_hints = _market_id_hints_from_session(LAST_ACTIVE_SESSION_DIR)

            def _auto_fetch_market(oid):
                h = auto_hints.get(oid) or {}
                return fetch_onliner_market_stats(
                    oid,
                    product_name=str(h.get("name", "") or ""),
                    category_name=str(h.get("category", "") or ""),
                )

            with ThreadPoolExecutor(max_workers=min(MARKET_REFRESH_POOL_WORKERS, max(4, len(ids)))) as ex:
                fut_to_oid = {ex.submit(_auto_fetch_market, oid): oid for oid in ids}
                for fut in as_completed(fut_to_oid):
                    oid = fut_to_oid[fut]
                    try:
                        stats = fut.result()
                    except Exception:
                        stats = {"min": None, "avg": None, "max": None, "offers": 0, "min_competitors": 0, "avg_competitors": 0, "_error": True}
                    had_values_before = market_stats_has_values(cache.get(oid))
                    has_values_now = market_stats_has_values(stats)
                    if has_values_now or not had_values_before:
                        cache[oid] = {"updated_at": now, **stats}
            save_onliner_market_cache(cache)

            done_ts = int(time.time())
            latest = load_auto_refresh_settings()
            latest["last_run_ts"] = done_ts
            latest["last_status"] = "ok"
            latest["last_count"] = len(ids)
            latest["last_message"] = f"Автообновление завершено. Обновлено ID: {len(ids)}"
            save_auto_refresh_settings(latest)
        except Exception as e:
            latest = load_auto_refresh_settings()
            latest["last_status"] = "error"
            latest["last_message"] = f"Ошибка автообновления: {str(e)[:160]}"
            save_auto_refresh_settings(latest)
        time.sleep(AUTO_REFRESH_POLL_SEC)


@app.route("/api/auto-refresh-settings")
def api_auto_refresh_settings():
    settings = load_auto_refresh_settings()
    now = int(time.time())
    interval_hours = int(settings.get("interval_hours", 12) or 12)
    if interval_hours not in AUTO_REFRESH_ALLOWED_HOURS:
        interval_hours = 12
    last_run_ts = int(settings.get("last_run_ts", 0) or 0)
    next_run_ts = 0
    if settings.get("enabled"):
        next_run_ts = (last_run_ts + interval_hours * 3600) if last_run_ts > 0 else now
    next_in_sec = max(0, next_run_ts - now) if next_run_ts else 0
    return jsonify({
        "enabled": bool(settings.get("enabled")),
        "interval_hours": interval_hours,
        "last_run_ts": last_run_ts,
        "last_started_ts": int(settings.get("last_started_ts", 0) or 0),
        "last_status": str(settings.get("last_status", "idle")),
        "last_count": int(settings.get("last_count", 0) or 0),
        "last_message": str(settings.get("last_message", "")),
        "next_run_ts": int(next_run_ts or 0),
        "next_in_sec": int(next_in_sec or 0),
    })


@app.route("/api/auto-refresh-settings", methods=["POST"])
def api_auto_refresh_settings_update():
    payload = request.get_json(silent=True) or {}
    current = load_auto_refresh_settings()
    was_enabled = bool(current.get("enabled"))
    if "enabled" in payload:
        current["enabled"] = bool(payload.get("enabled"))
    if "interval_hours" in payload:
        try:
            interval = int(payload.get("interval_hours"))
        except Exception:
            interval = current.get("interval_hours", 12)
        if interval in AUTO_REFRESH_ALLOWED_HOURS:
            current["interval_hours"] = interval
    if current.get("enabled") and int(current.get("last_run_ts", 0) or 0) <= 0:
        # First enable: run ASAP.
        current["last_run_ts"] = 0
        current["last_message"] = "Автообновление включено. Ближайший запуск — в ближайшие секунды."
    elif not current.get("enabled"):
        current["last_message"] = "Автообновление выключено."
    save_auto_refresh_settings(current)

    # Immediate full refresh when toggled ON: refresh all categories now.
    if current.get("enabled") and not was_enabled:
        sdir = session.get("session_dir") or LAST_ACTIVE_SESSION_DIR
        started = _start_market_refresh(sdir, [])
        latest = load_auto_refresh_settings()
        if started.get("status") == "started":
            latest["last_status"] = "running"
            latest["last_started_ts"] = int(time.time())
            latest["last_message"] = "Автообновление включено. Мгновенный запуск по всем категориям."
        elif started.get("status") == "already_running":
            latest["last_status"] = "running"
            latest["last_message"] = "Автообновление включено. Уже идет текущее обновление."
        else:
            latest["last_status"] = "error"
            latest["last_message"] = "Автообновление включено, но старт не выполнен: " + str(started.get("message", "нет активной сессии"))
        save_auto_refresh_settings(latest)

    return jsonify({"status": "ok"})


@app.route("/api/app-settings")
def api_app_settings():
    data = load_app_settings()
    # Redact secrets before sending to frontend
    b2b = data.get("onliner_b2b")
    if isinstance(b2b, dict):
        if str(b2b.get("client_secret") or "").strip():
            b2b["client_secret"] = "••••••••"
    sources = data.get("api_sources")
    if isinstance(sources, dict):
        for key in ("iven", "tradex"):
            src = sources.get(key)
            if isinstance(src, dict) and str(src.get("file_url") or "").strip():
                src["file_url"] = "••••••••"
        ntech = sources.get("ntech")
        if isinstance(ntech, dict):
            if str(ntech.get("password") or "").strip():
                ntech["password"] = "••••••••"
    return jsonify({"status": "ok", "settings": data})


@app.route("/api/app-settings", methods=["POST"])
def api_app_settings_update():
    payload = request.get_json(silent=True) or {}
    current = load_app_settings()
    # Preserve secrets from .env if frontend sends empty/redacted values
    b2b = payload.get("onliner_b2b")
    if isinstance(b2b, dict):
        if not str(b2b.get("client_secret") or "").strip() or b2b.get("client_secret") == "••••••••":
            b2b["client_secret"] = current.get("onliner_b2b", {}).get("client_secret", "")
    sources = payload.get("api_sources")
    if isinstance(sources, dict):
        for key in ("iven", "tradex"):
            src = sources.get(key)
            if isinstance(src, dict):
                if not str(src.get("file_url") or "").strip() or src.get("file_url") == "••••••••":
                    src["file_url"] = current.get("api_sources", {}).get(key, {}).get("file_url", "")
        ntech = sources.get("ntech")
        if isinstance(ntech, dict):
            if not str(ntech.get("password") or "").strip() or ntech.get("password") == "••••••••":
                ntech["password"] = current.get("api_sources", {}).get("ntech", {}).get("password", "")
    merged = _deep_merge_dict(current, payload if isinstance(payload, dict) else {})
    saved = save_app_settings(merged)
    return jsonify({"status": "ok", "settings": saved})


@app.route("/api/onliner-b2b-test", methods=["POST"])
def api_onliner_b2b_test():
    try:
        token_info = onliner_b2b_get_token(force_refresh=True)
        resp = onliner_b2b_request("GET", "/shop")
        preview = {}
        try:
            preview = resp.json() if resp.content else {}
        except Exception:
            preview = {}
        return jsonify({
            "status": "ok",
            "token_type": str(token_info.get("token_type", "Bearer") or "Bearer"),
            "expires_in": int(token_info.get("expires_in", 0) or 0),
            "http_status": int(resp.status_code or 0),
            "response_preview": preview if isinstance(preview, (dict, list)) else {},
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:300]}), 400


@app.route("/api/onliner-b2b-probe", methods=["POST"])
def api_onliner_b2b_probe():
    try:
        token_info = onliner_b2b_get_token(force_refresh=True)

        def _json_payload(resp):
            try:
                return resp.json() if resp.content else {}
            except Exception:
                return {}

        def _pick_items(payload):
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                for key in ("items", "sections", "manufacturers", "products", "data", "results"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        return value
                    if isinstance(value, dict):
                        nested = _pick_items(value)
                        if nested:
                            return nested
                if payload and all(isinstance(v, dict) for v in payload.values()):
                    return list(payload.values())
                numeric_like_keys = [str(k).strip() for k in payload.keys()]
                if payload and all(re.fullmatch(r"\d+", key or "") for key in numeric_like_keys):
                    normalized = []
                    for raw_key, raw_value in payload.items():
                        item_id = str(raw_key).strip()
                        if isinstance(raw_value, dict):
                            entry = dict(raw_value)
                            entry.setdefault("id", item_id)
                        else:
                            entry = {"id": item_id, "name": str(raw_value or "").strip()}
                        normalized.append(entry)
                    return normalized
            return []

        def _item_id(item):
            if not isinstance(item, dict):
                return ""
            for key in ("id", "section_id", "manufacturer_id", "product_id", "sectionId", "manufacturerId", "productId"):
                value = item.get(key)
                if value not in (None, ""):
                    return str(value).strip()
            urls = item.get("url") or item.get("href") or item.get("link")
            if isinstance(urls, str):
                m = re.search(r"/(\d+)(?:/)?$", urls.strip())
                if m:
                    return str(m.group(1)).strip()
            return ""

        def _item_name(item):
            if not isinstance(item, dict):
                return ""
            for key in ("name", "full_name", "title", "key", "slug"):
                value = item.get(key)
                if value not in (None, ""):
                    return str(value).strip()
            return ""

        section_resp = onliner_b2b_request("GET", "/sections")
        section_payload = _json_payload(section_resp)
        sections = _pick_items(section_payload)
        section_sample = sections[:3] if isinstance(sections, list) else []
        section_payload_type = type(section_payload).__name__
        section_payload_keys = list(section_payload.keys())[:10] if isinstance(section_payload, dict) else []

        result = {
            "status": "ok",
            "token_type": str(token_info.get("token_type", "Bearer") or "Bearer"),
            "expires_in": int(token_info.get("expires_in", 0) or 0),
            "sections_http_status": int(section_resp.status_code or 0),
            "sections_count": len(sections),
            "sections_sample": section_sample,
            "sections_payload_type": section_payload_type,
            "sections_payload_keys": section_payload_keys,
            "sections_preview": section_payload if isinstance(section_payload, (dict, list)) else {},
            "manufacturers_http_status": 0,
            "manufacturers_count": 0,
            "manufacturers_sample": [],
            "products_http_status": 0,
            "products_count": 0,
            "products_sample": [],
            "message": "",
        }

        first_section = sections[0] if sections else {}
        first_section_id = _item_id(first_section)
        if not first_section_id:
            result["message"] = "B2B вернул разделы, но не удалось выделить section id для дальнейшей проверки. Проверь sections_preview."
            return jsonify(result)

        manufacturers_resp = onliner_b2b_request("GET", f"/sections/{first_section_id}/manufacturers")
        manufacturers_payload = _json_payload(manufacturers_resp)
        manufacturers = _pick_items(manufacturers_payload)
        result["manufacturers_http_status"] = int(manufacturers_resp.status_code or 0)
        result["manufacturers_count"] = len(manufacturers)
        result["manufacturers_sample"] = manufacturers[:3] if isinstance(manufacturers, list) else []

        first_manufacturer = manufacturers[0] if manufacturers else {}
        first_manufacturer_id = _item_id(first_manufacturer)
        if not first_manufacturer_id:
            result["message"] = "B2B вернул производителей, но не удалось выделить manufacturer id для проверки товаров."
            return jsonify(result)

        products_resp = onliner_b2b_request("GET", f"/sections/{first_section_id}/manufacturers/{first_manufacturer_id}/products")
        products_payload = _json_payload(products_resp)
        products = _pick_items(products_payload)
        result["products_http_status"] = int(products_resp.status_code or 0)
        result["products_count"] = len(products)
        result["products_sample"] = products[:3] if isinstance(products, list) else []
        result["message"] = (
            "B2B данные получены. "
            f"Раздел: {_item_name(first_section) or first_section_id}; "
            f"производитель: {_item_name(first_manufacturer) or first_manufacturer_id}."
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:300]}), 400


@app.route("/api/source-fetch-start", methods=["POST"])
def api_source_fetch_start():
    payload = request.get_json(silent=True) or {}
    source_key = str(payload.get("source", "")).strip().lower()
    client_key = _get_api_source_status_key()
    settings = load_app_settings()
    cfg = (((settings or {}).get("api_sources") or {}).get(source_key) or {})
    if not cfg:
        return jsonify({"status": "error", "message": "Неизвестный источник"})
    runtime = _get_source_runtime(source_key, client_key=client_key)
    if runtime.get("running"):
        return jsonify({"status": "ok", "state": _serialize_source_runtime(runtime)})
    _update_source_runtime(
        source_key,
        client_key=client_key,
        running=True,
        ready=False,
        progress=0,
        downloaded=0,
        total_bytes=0,
        status="starting",
        message="Подготавливаю выгрузку...",
        started_at=time.time(),
        finished_at=0,
    )
    thread = threading.Thread(target=_fetch_api_source_worker, args=(source_key, client_key), daemon=True)
    thread.start()
    return jsonify({"status": "ok", "state": _serialize_source_runtime(_get_source_runtime(source_key, client_key=client_key))})


@app.route("/api/source-fetch-status")
def api_source_fetch_status():
    client_key = _get_api_source_status_key()
    source_key = str(request.args.get("source", "")).strip().lower()
    if source_key:
        state = _serialize_source_runtime(_get_source_runtime(source_key, client_key=client_key))
        return jsonify({"status": "ok", "state": state, "history": get_api_fetch_history(limit=20)})
    settings = load_app_settings()
    items = []
    for src in _iter_api_sources_for_ui(settings):
        runtime = _serialize_source_runtime(_get_source_runtime(src["key"], client_key=client_key))
        runtime.update({
            "label": src["label"],
            "supplier": src["supplier"],
            "enabled": src["enabled"],
            "configured": src["configured"],
            "mode": src["mode"],
        })
        items.append(runtime)
    return jsonify({"status": "ok", "items": items, "history": get_api_fetch_history(limit=20)})


@app.route("/api/source-process", methods=["POST"])
def api_source_process():
    payload = request.get_json(silent=True) or {}
    source_key = str(payload.get("source", "")).strip().lower()
    runtime = _get_source_runtime(source_key, client_key=_get_api_source_status_key())
    file_path = Path(str(runtime.get("file_path", "") or ""))
    supplier = str(runtime.get("supplier", "") or source_key.upper()).strip() or source_key.upper()
    label = str(runtime.get("label", source_key.upper()) or source_key.upper())
    started_at = int(time.time())
    if not file_path.exists():
        return jsonify({"status": "error", "message": "Сначала выгрузи прайс"}), 400
    try:
        result = _process_supplier_files([{
            "filepath": file_path,
            "display_name": runtime.get("file_name", file_path.name),
            "supplier_name": supplier,
        }])
    except Exception as e:
        finished_at = int(time.time())
        append_api_fetch_history({
            "source_key": source_key,
            "label": label,
            "supplier": supplier,
            "event_type": "process",
            "status": "error",
            "message": str(e) or "Не удалось обработать прайс",
            "file_name": file_path.name,
            "file_size": int(file_path.stat().st_size if file_path.exists() else 0),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": max(0, finished_at - started_at),
        })
        return jsonify({"status": "error", "message": str(e) or "Не удалось обработать прайс"}), 500
    _finalize_processed_session(result["session_id"], result["session_dir"], result["output_path"])
    finished_at = int(time.time())
    stats = result.get("stats") or {}
    append_api_fetch_history({
        "source_key": source_key,
        "label": label,
        "supplier": supplier,
        "event_type": "process",
        "status": "ok",
        "message": "Прайс обработан",
        "file_name": file_path.name,
        "file_size": int(file_path.stat().st_size if file_path.exists() else 0),
        "items_count": int(stats.get("consolidated", 0) or 0),
        "without_id_count": int(stats.get("without_id", 0) or 0),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": max(0, finished_at - started_at),
        "session_id": str(result.get("session_id", "") or ""),
    })
    return jsonify({"status": "ok", "redirect_url": url_for("result_page", sid=result["session_id"])})


@app.route("/api/source-process-batch", methods=["POST"])
def api_source_process_batch():
    payload = request.get_json(silent=True) or {}
    client_key = _get_api_source_status_key()
    requested_sources = payload.get("sources")
    if isinstance(requested_sources, list):
        source_keys = [str(item or "").strip().lower() for item in requested_sources if str(item or "").strip()]
    else:
        source_keys = []
    with SOURCE_FETCH_LOCK:
        client_state = dict(source_fetch_statuses.get(client_key, {}) or {})
    if not source_keys:
        source_keys = [str(k or "").strip().lower() for k, v in client_state.items() if isinstance(v, dict) and v.get("ready")]
    dedup = []
    seen = set()
    for key in source_keys:
        if key and key not in seen:
            seen.add(key)
            dedup.append(key)
    source_keys = dedup
    if not source_keys:
        return jsonify({"status": "error", "message": "Нет готовых API-прайсов для обработки."}), 400

    started_at = int(time.time())
    file_entries = []
    per_source_meta = []
    for source_key in source_keys:
        runtime = _get_source_runtime(source_key, client_key=client_key)
        file_path = Path(str(runtime.get("file_path", "") or ""))
        if not file_path.exists():
            continue
        supplier = str(runtime.get("supplier", "") or source_key.upper()).strip() or source_key.upper()
        label = str(runtime.get("label", source_key.upper()) or source_key.upper())
        file_entries.append({
            "filepath": file_path,
            "display_name": runtime.get("file_name", file_path.name),
            "supplier_name": supplier,
        })
        per_source_meta.append({
            "source_key": source_key,
            "supplier": supplier,
            "label": label,
            "file_name": file_path.name,
            "file_size": int(file_path.stat().st_size if file_path.exists() else 0),
        })
    if not file_entries:
        return jsonify({"status": "error", "message": "Готовые файлы не найдены. Сначала нажми «Выгрузить»."}), 400

    try:
        result = _process_supplier_files(file_entries)
    except Exception as e:
        finished_at = int(time.time())
        err_msg = str(e) or "Не удалось обработать API-прайсы"
        for meta in per_source_meta:
            append_api_fetch_history({
                "source_key": meta["source_key"],
                "label": meta["label"],
                "supplier": meta["supplier"],
                "event_type": "process",
                "status": "error",
                "message": "Пакетная обработка: " + err_msg,
                "file_name": meta["file_name"],
                "file_size": meta["file_size"],
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_sec": max(0, finished_at - started_at),
            })
        return jsonify({"status": "error", "message": err_msg}), 500

    _finalize_processed_session(result["session_id"], result["session_dir"], result["output_path"])
    finished_at = int(time.time())
    stats = result.get("stats") or {}
    for meta in per_source_meta:
        append_api_fetch_history({
            "source_key": meta["source_key"],
            "label": meta["label"],
            "supplier": meta["supplier"],
            "event_type": "process",
            "status": "ok",
            "message": "Пакетная обработка API-источников",
            "file_name": meta["file_name"],
            "file_size": meta["file_size"],
            "items_count": int(stats.get("consolidated", 0) or 0),
            "without_id_count": int(stats.get("without_id", 0) or 0),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": max(0, finished_at - started_at),
            "session_id": str(result.get("session_id", "") or ""),
        })
    return jsonify({
        "status": "ok",
        "processed_sources": source_keys,
        "redirect_url": url_for("result_page", sid=result["session_id"]),
    })


@app.route("/api/market-refresh-start", methods=["POST"])
def api_market_refresh_start():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})
    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    if not isinstance(categories, list):
        categories = []
    return jsonify(_start_market_refresh(str(session_dir), categories))


def _start_market_refresh(session_dir, categories):
    session_dir = str(session_dir or "").strip()
    if not session_dir:
        return {"status": "error", "message": "No session"}
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return {"status": "error", "message": "No data"}
    if not isinstance(categories, list):
        categories = []
    with MARKET_REFRESH_LOCK:
        if market_refresh_status.get("running"):
            return {"status": "already_running"}
        market_refresh_status["running"] = True
        market_refresh_status["started_at"] = int(time.time())
        market_refresh_status["finished_at"] = 0
        market_refresh_status["total"] = 0
        market_refresh_status["done"] = 0
        market_refresh_status["success"] = 0
        market_refresh_status["errors"] = 0
        market_refresh_status["categories"] = {}
    threading.Thread(
        target=_market_refresh_worker,
        args=(session_dir, categories),
        daemon=True,
    ).start()
    return {"status": "started"}


@app.route("/api/market-refresh-status")
def api_market_refresh_status():
    with MARKET_REFRESH_LOCK:
        st = dict(market_refresh_status)
        cats = st.get("categories", {}) or {}
        cats_pct = {
            k: {
                "done": int(v.get("done", 0)),
                "total": int(v.get("total", 0)),
                "percent": int(v.get("percent", 0)),
                "errors": int(v.get("errors", 0) or 0),
                "recent_errors": list(v.get("recent_errors", []) or []),
            }
            for k, v in cats.items()
        }
        total = int(st.get("total", 0))
        done = int(st.get("done", 0))
        overall = int(round((done / max(total, 1)) * 100)) if total else 0
        return jsonify({
            "running": bool(st.get("running")),
            "total": total,
            "done": done,
            "success": int(st.get("success", 0) or 0),
            "errors": int(st.get("errors", 0) or 0),
            "overall_percent": overall,
            "categories": cats_pct,
            "recent_errors": list(st.get("recent_errors", []) or []),
            "started_at": int(st.get("started_at", 0)),
            "finished_at": int(st.get("finished_at", 0)),
        })


@app.route("/api/onliner-offers/<onliner_id>")
def api_onliner_offers(onliner_id):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return jsonify({"status": "error", "message": "Пустой OnlinerID"})
    product, product_error = _fetch_onliner_product_payload(oid)
    if not product:
        return jsonify({"status": "error", "message": product_error or "Товар не найден"})
    prices_obj = product.get("prices") or {}
    offers_count = int((prices_obj.get("offers") or {}).get("count") or 0)
    positions_url = str(prices_obj.get("url", "")).strip()
    if not positions_url:
        return jsonify({
            "status": "ok",
            "offers_count": offers_count,
            "positions_count": 0,
            "unique_sellers_count": 0,
            "offers": [],
            "note": "API товара найден, но детализация офферов отсутствует.",
        })
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        rp = onliner_api_get(positions_url, timeout=12, headers=headers)
        if not rp.ok:
            return jsonify({"status": "error", "message": f"positions: http {rp.status_code}"})
        payload = rp.json() or {}
    except Exception:
        return jsonify({"status": "error", "message": "positions: timeout/connection"})
    offers = _extract_offer_rows(payload)
    unique_sellers = set()
    for row in offers:
        unique_sellers.add((str(row.get("seller_id", "")).strip(), str(row.get("seller_name", "")).strip()))
    return jsonify({
        "status": "ok",
        "offers_count": offers_count,
        "positions_count": len(offers),
        "unique_sellers_count": len(unique_sellers),
        "offers": offers[:120],
        "note": "Сравните offers.count, число позиций API и уникальные магазины. На сайте Onliner цифры могут отличаться.",
    })


@app.route("/api/category-markups")
def api_category_markups():
    return jsonify({"markups": load_category_markups()})


@app.route("/api/category-override-bulk", methods=["POST"])
def api_category_override_bulk():
    session_dir = session.get("session_dir")
    payload = request.get_json(silent=True) or {}
    item_keys = payload.get("item_keys", [])
    target_category = str(payload.get("target_category", "")).strip()
    if not isinstance(item_keys, list) or not item_keys:
        return jsonify({"status": "error", "message": "Не выбраны товары"})
    if not target_category:
        return jsonify({"status": "error", "message": "Не выбрана целевая категория"})

    keys = [str(k).strip() for k in item_keys if str(k).strip()]
    if not keys:
        return jsonify({"status": "error", "message": "Не выбраны товары"})

    overrides = load_category_overrides()
    for key in keys:
        overrides[key] = target_category

    updated_rows = 0
    if session_dir:
        cons_path = Path(session_dir) / "consolidated_price.xlsx"
        if cons_path.exists():
            df = read_consolidated_df(session_dir)
            df = ensure_category_column(df, overrides)
            key_set = set(keys)
            for i, row in df.iterrows():
                row_keys = set(build_item_category_keys(row))
                if key_set.intersection(row_keys):
                    df.at[i, "Категория"] = target_category
                    for k in row_keys:
                        overrides[k] = target_category
                    updated_rows += 1
            if updated_rows:
                write_consolidated_df(session_dir, df)
                write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    save_category_overrides(overrides)

    return jsonify({"status": "ok", "updated": len(keys), "updated_rows": updated_rows})


@app.route("/api/category-autosort-preview", methods=["POST"])
def api_category_autosort_preview():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"items": [], "checked": 0, "skipped": 0})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"items": [], "checked": 0, "skipped": 0})

    payload = request.get_json(silent=True) or {}
    categories = payload.get("categories", [])
    selected = {str(c).strip() for c in categories if str(c).strip()} if isinstance(categories, list) else set()
    try:
        min_confidence = float(payload.get("min_confidence", 0.64))
    except Exception:
        min_confidence = 0.64
    min_confidence = max(0.50, min(0.95, min_confidence))

    df = read_consolidated_df(session_dir)
    if "Название" not in df.columns:
        return jsonify({"items": [], "checked": 0, "skipped": 0})
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)

    overrides = load_category_overrides()

    # Локальное обучение категорий только по уже загруженному прайсу:
    # "как у вас руками отсортировано" + текущие назначенные категории.
    category_token_counts = {}
    category_item_counts = {}
    for _, row in df.iterrows():
        cat = row_category(row, overrides)
        if not cat:
            continue
        toks = set(_name_tokens(row.get("Название", "")))
        if not toks:
            continue
        bucket = category_token_counts.setdefault(cat, {})
        for t in toks:
            bucket[t] = int(bucket.get(t, 0)) + 1
        category_item_counts[cat] = int(category_item_counts.get(cat, 0)) + 1

    # Частые токены по категориям + idf-подобный вес по редкости токена.
    token_category_df = {}
    for cat, tok_map in category_token_counts.items():
        for tok in tok_map.keys():
            token_category_df[tok] = int(token_category_df.get(tok, 0)) + 1

    def _predict_local_category(name):
        toks = set(_name_tokens(name))
        if not toks:
            return "", 0.0

        best_cat = ""
        best_score = 0.0
        second_score = 0.0
        total_cats = max(1, len(category_token_counts))

        for cat, tok_map in category_token_counts.items():
            cat_size = int(category_item_counts.get(cat, 0))
            if cat_size < 2:
                continue

            raw = 0.0
            hit = 0
            for t in toks:
                cnt = int(tok_map.get(t, 0))
                if cnt <= 0:
                    continue
                hit += 1
                # редкие по категориям токены сильнее помогают классификации
                idf = np.log1p((1.0 + total_cats) / (1.0 + int(token_category_df.get(t, 0))))
                raw += (cnt / max(1.0, float(cat_size))) * (1.0 + float(idf))

            if hit == 0:
                continue

            coverage = hit / max(1.0, float(len(toks)))
            score = (0.72 * raw) + (0.28 * coverage)

            if score > best_score:
                second_score = best_score
                best_score = score
                best_cat = cat
            elif score > second_score:
                second_score = score

        if not best_cat:
            return "", 0.0

        # Уверенность: нормализуем победителя и добавляем разрыв от 2-го места.
        gap = max(0.0, best_score - second_score)
        confidence = min(0.99, (best_score / (best_score + 0.8)) * 0.82 + min(0.17, gap))
        return best_cat, round(float(confidence), 3)

    checked = 0
    skipped = 0
    ai_checked = 0
    ai_suggested = 0
    ai_unavailable = 0
    proposals = {}
    conflict_keys = set()
    ai_candidates = []

    for _, row in df.iterrows():
        current_category = row_category(row, overrides)
        if selected and current_category not in selected:
            continue
        checked += 1

        name = str(row.get("Название", "")).strip()
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        # Режим AI-first: локальный классификатор используем только как подсказку для промпта.
        target_category, confidence = _predict_local_category(name)
        ai_candidates.append({
            "row": row,
            "name": name,
            "oid": oid,
            "current_category": current_category,
            "local_target": target_category,
            "local_confidence": confidence,
        })
        continue

    # AI fallback only for unresolved/low-confidence rows.
    if ai_candidates:
        valid_categories = sorted([str(c).strip() for c in category_item_counts if str(c).strip()], key=_category_sort_key)
        ai_batch = ai_candidates[:OPENAI_AUTOSORT_MAX_ITEMS]

        prepared = []
        for item in ai_batch:
            row = item.get("row")
            if row is None:
                skipped += 1
                continue
            name = str(item.get("name", "")).strip()
            current_category = str(item.get("current_category", "")).strip()
            local_target = str(item.get("local_target", "")).strip()
            local_confidence = float(item.get("local_confidence", 0.0) or 0.0)

            row_keys = build_item_category_keys(row)
            if any(str(overrides.get(k, "")).strip() for k in row_keys):
                skipped += 1
                continue

            item_key = build_item_category_key(row)
            if not item_key:
                skipped += 1
                continue

            local_hint = (
                f"local_target={local_target}; local_confidence={round(local_confidence, 3)}; "
                f"current_category={current_category}"
            )
            prepared.append({
                "item": item,
                "row": row,
                "name": name,
                "item_key": item_key,
                "current_category": current_category,
                "local_hint": local_hint,
            })

        ai_checked += len(prepared)
        if not OPENAI_API_KEY and prepared:
            ai_unavailable += len(prepared)

        def _ask_ai(entry):
            ai_category, ai_confidence, ai_reason = _openai_autosort_predict_category(
                entry["name"],
                valid_categories,
                local_hint=entry["local_hint"],
            )
            return entry, ai_category, ai_confidence, ai_reason

        if prepared:
            workers = max(1, min(OPENAI_AUTOSORT_MAX_WORKERS, len(prepared)))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_ask_ai, entry) for entry in prepared]
                for fut in as_completed(futs):
                    entry, ai_category, ai_confidence, ai_reason = fut.result()
                    item = entry["item"]
                    row = entry["row"]
                    item_key = entry["item_key"]
                    name = entry["name"]
                    current_category = entry["current_category"]

                    if not ai_category or ai_confidence < max(0.56, min_confidence):
                        skipped += 1
                        continue
                    if ai_category == current_category:
                        skipped += 1
                        continue

                    existing = proposals.get(item_key)
                    if existing and str(existing.get("target_category", "")).strip() != ai_category:
                        conflict_keys.add(item_key)
                        continue
                    if existing:
                        continue

                    proposals[item_key] = {
                        "item_key": item_key,
                        "onliner_id": str(item.get("oid", "")).strip(),
                        "name": name,
                        "supplier": str(row.get("Поставщик", "")).strip(),
                        "current_category": current_category,
                        "target_category": ai_category,
                        "catalog_category": "",
                        "source": f"AI classifier ({ai_reason})",
                        "confidence": round(float(ai_confidence), 3),
                    }
                    ai_suggested += 1

    for key in list(conflict_keys):
        proposals.pop(key, None)

    proposal_keys = set(proposals.keys())
    affected_rows = dict.fromkeys(proposal_keys, 0)
    if proposal_keys:
        for _, row in df.iterrows():
            row_keys = set(build_item_category_keys(row))
            for k in proposal_keys.intersection(row_keys):
                affected_rows[k] += 1

    items = []
    for item_key, rec in proposals.items():
        out = dict(rec)
        out["affected_rows"] = int(affected_rows.get(item_key, 1) or 1)
        items.append(out)
    items.sort(key=lambda x: (_category_sort_key(x.get("target_category", "")), _category_sort_key(x.get("current_category", "")), str(x.get("name", "")).lower()))

    return jsonify({
        "items": items,
        "checked": int(checked),
        "skipped": int(skipped + len(conflict_keys)),
        "ai_checked": int(ai_checked),
        "ai_suggested": int(ai_suggested),
        "ai_unavailable": int(ai_unavailable),
    })


@app.route("/api/category-autosort-apply", methods=["POST"])
def api_category_autosort_apply():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "No data"})

    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        return jsonify({"status": "error", "message": "Нет выбранных позиций"})

    target_by_key = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        item_key = str(it.get("item_key", "")).strip()
        target_category = str(it.get("target_category", "")).strip()
        if not item_key or not target_category:
            continue
        target_by_key[item_key] = target_category
    if not target_by_key:
        return jsonify({"status": "error", "message": "Нет корректных данных для применения"})

    overrides = load_category_overrides()
    for item_key, target_category in target_by_key.items():
        overrides[item_key] = target_category

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df, overrides)
    updated_rows = 0
    target_key_set = set(target_by_key.keys())
    for i, row in df.iterrows():
        row_keys = set(build_item_category_keys(row))
        matched = [target_by_key[k] for k in row_keys if k in target_key_set]
        if not matched:
            continue
        target_category = matched[0]
        if len(matched) > 1:
            # Теоретически возможна коллизия: берем первую (детерминированно).
            target_category = sorted(matched)[0]
        current_category = str(df.at[i, "Категория"]).strip() if "Категория" in df.columns else row_category(row, overrides)
        if current_category != target_category:
            df.at[i, "Категория"] = target_category
            updated_rows += 1
        # Расширяем ручную привязку на все ключи этой строки.
        for rk in row_keys:
            overrides[rk] = target_category

    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, Path(session_dir) / "consolidated.json")
    save_category_overrides(overrides)

    return jsonify({
        "status": "ok",
        "updated_keys": int(len(target_by_key)),
        "updated_rows": int(updated_rows),
    })


@app.route("/api/resolve-start", methods=["POST"])
def api_resolve_start():
    global resolve_status
    if resolve_status["running"]:
        return jsonify({"status": "already_running"})

    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "No session"})

    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "No data"})

    df = read_consolidated_df(session_dir)

    id_to_name = {}
    for _, row in df.iterrows():
        oid = row.get("OnlinerID")
        name = row.get("Название", "")
        if oid and str(oid).strip() and str(oid) != "nan":
            id_to_name[str(oid)] = name

    all_ids = list(id_to_name.keys())
    cache = load_url_cache()
    uncached = [oid for oid in all_ids if oid not in cache]

    resolve_status = {
        "running": True,
        "resolved": 0,
        "total": len(uncached),
        "cached": len(cache),
    }

    def _run_resolve():
        global resolve_status
        try:
            def progress(done, total):
                resolve_status["resolved"] = done
                resolve_status["cached"] = len(cache)

            resolve_onliner_urls(uncached, cache=cache, max_workers=5, progress_callback=progress, id_to_name=id_to_name)
            resolve_status["resolved"] = resolve_status["total"]
            resolve_status["cached"] = len(cache)

            df = read_consolidated_df(session_dir)
            for i, row in df.iterrows():
                oid = row.get("OnlinerID")
                if oid and str(oid) in cache:
                    df.at[i, "Ссылка"] = cache.get(str(oid), "")
            write_consolidated_df(session_dir, df)

            cons_json_path = Path(session_dir) / "consolidated.json"
            write_consolidated_json(df, cons_json_path)
        finally:
            resolve_status["running"] = False

    thread = threading.Thread(target=_run_resolve, daemon=True)
    thread.start()

    return jsonify({"status": "started", "total": len(uncached)})


@app.route("/api/resolve-status")
def api_resolve_status():
    return jsonify(resolve_status)


def _parse_google_spreadsheet_id(url_or_id):
    s = str(url_or_id or "").strip()
    if not s:
        return ""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1).strip()
    s2 = s.strip()
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", s2):
        return s2
    return ""


def _resolve_service_account_json_path(raw):
    """
    Ищем JSON ключ сервисного аккаунта. Возвращает (Path|None, подсказка_для_ошибки).
    """
    raw = str(raw or "").strip()
    raw = raw.strip('"').strip("'").strip("\u200b").strip()
    raw = os.path.expanduser(raw)
    if not raw:
        return None, "В настройках пустое поле пути к JSON — введите путь и нажмите «Сохранить настройки»."
    tried = []
    candidates = []
    p0 = Path(raw)
    if p0.is_absolute():
        candidates.append(p0)
    else:
        base_app = Path(__file__).resolve().parent
        candidates.append(base_app / raw)
        candidates.append(Path.cwd() / raw)
    seen = set()
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        key = str(rp)
        if key in seen:
            continue
        seen.add(key)
        tried.append(key)
        if rp.is_file():
            return rp, ""
    return None, "Файл не найден. Проверьте путь и что настройки сохранены. Искали: " + " · ".join(tried)


def _prepare_consolidated_for_export(session_dir):
    """Тот же набор фильтров, что и для /download. Возвращает (DataFrame|None, имя_файла.xlsx)."""
    settings = load_app_settings()
    export_cfg = settings.get("export", {})
    include_without_id = bool(export_cfg.get("include_without_id", True))
    keep_lowest_id_price = bool(export_cfg.get("keep_lowest_price_per_onliner_id", False))
    base_name = str(export_cfg.get("price_name", "consolidated_price")).strip() or "consolidated_price"
    exclude_duplicate_id_suppliers = export_cfg.get("exclude_duplicate_id_suppliers", [])
    only_pc_suppliers = export_cfg.get("only_pc_suppliers", [])
    only_pc_price_name = str(export_cfg.get("only_pc_price_name", "N-tech_TGPC_Beznal")).strip() or "N-tech_TGPC_Beznal"
    download_name = f"{base_name}.xlsx"
    sd = str(session_dir or "").strip()
    if not sd:
        return None, download_name
    cons_path = Path(sd) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return None, download_name
    df = read_consolidated_df(sd)
    filtered = apply_visibility_filter(df, sd)
    if not include_without_id and "OnlinerID" in filtered.columns:
        mask = filtered["OnlinerID"].apply(lambda v: bool(normalize_onliner_id(v)))
        filtered = filtered[mask].copy()
    if keep_lowest_id_price:
        filtered = apply_export_keep_lowest_price_per_onliner_id(filtered)
    filtered = apply_export_duplicate_id_filter(filtered, exclude_duplicate_id_suppliers)
    before_only_pc_len = len(filtered)
    filtered = apply_export_only_pc_filter(filtered, only_pc_suppliers)
    if only_pc_suppliers and len(filtered) != before_only_pc_len:
        download_name = f"{only_pc_price_name}.xlsx"
    return filtered, download_name


def _export_column_is_onliner_id(name):
    """Колонка с Onliner ID (в т.ч. с пробелами / другим регистром)."""
    raw = str(name or "").strip().lower().replace("\xa0", " ")
    compact = re.sub(r"[\s_]+", "", raw)
    if compact == "onlinerid":
        return True
    if "onliner" in compact and compact.endswith("id"):
        return True
    return False


def _normalize_export_column_name(name):
    raw = str(name or "").strip().lower().replace("\xa0", " ")
    return re.sub(r"\s+", " ", raw)


def _export_column_is_money(name):
    normalized = _normalize_export_column_name(name)
    if not normalized:
        return False
    money_cols = {
        "цена",
        "лучшая цена",
        "ррц",
        "цена без скидки",
        "цена без ндс",
        "цена с ндс",
    }
    if normalized in money_cols:
        return True
    return ("цена" in normalized) and ("ссылка" not in normalized)


def _coerce_money_value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float, np.integer, np.floating)):
        fv = float(v)
        if not math.isfinite(fv):
            return ""
        return f"{fv:.2f}"
    s = str(v).strip()
    if not s:
        return ""
    s = s.replace("\xa0", "").replace(" ", "")
    # RU decimal comma and Excel/Sheets artifacts are normalized to dot.
    s = s.replace(",", ".")
    try:
        fv = float(s)
        if not math.isfinite(fv):
            return ""
        return f"{fv:.2f}"
    except Exception:
        return str(v)


def _dataframe_to_sheet_values(df):
    if df is None or df.empty:
        return []
    original_cols = list(df.columns)
    normalized_map = {_normalize_export_column_name(c): c for c in original_cols}

    # Fixed Google Sheets layout:
    # A: empty, B: Название, C: Цена, D: Поставщик, E: Гарантия,
    # F: Дней доставки, G: РРЦ, H: Цена без скидки
    target_layout = [
        ("", []),
        ("Название", ["наименование", "название"]),
        # Оптовая цена из миксера:
        # приоритет "Опт цена"/"Лучшая цена", fallback на "Цена",
        # но не на сервисные денежные колонки.
        ("Цена", ["опт цена", "лучшая цена", "цена"]),
        ("Поставщик", ["поставщик"]),
        ("Гарантия", ["гарантия"]),
        ("Дней доставки", ["дней доставки", "дни доставки", "доставка дней", "срок поставки"]),
        ("РРЦ", ["ррц"]),
        ("Цена без скидки", ["цена без скидки"]),
        ("OnlinerID", ["onlinerid", "onliner id"]),
    ]
    resolved_columns = []
    for _header_name, aliases in target_layout:
        picked = None
        for alias in aliases:
            if alias in normalized_map:
                picked = normalized_map[alias]
                break
        resolved_columns.append(picked)

    headers = [item[0] for item in target_layout]
    rows = [headers]
    for _, row in df.iterrows():
        line = []
        for idx, src_col in enumerate(resolved_columns):
            if idx == 0:
                line.append("")
                continue
            if not src_col:
                line.append("")
                continue
            col_name = src_col
            v = row.get(src_col)
            if _export_column_is_onliner_id(col_name):
                line.append(normalize_onliner_id(v))
                continue
            if _export_column_is_money(col_name):
                line.append(_coerce_money_value(v))
                continue
            if v is None:
                line.append("")
                continue
            if isinstance(v, float) and math.isnan(v):
                line.append("")
                continue
            try:
                if pd.isna(v):
                    line.append("")
                    continue
            except (ValueError, TypeError):
                pass
            try:
                if hasattr(v, "isoformat") and not isinstance(v, (str, bytes, int, float, bool)):
                    line.append(str(v.isoformat()))
                else:
                    s = str(v)
                    line.append("" if s.lower() == "nan" else s)
            except Exception:
                line.append(str(v))
        rows.append(line)
    return rows


@app.route("/download")
def download():
    settings = load_app_settings()
    export_cfg = settings.get("export", {})
    base_name = str(export_cfg.get("price_name", "consolidated_price")).strip() or "consolidated_price"
    download_name = f"{base_name}.xlsx"
    session_dir = session.get("session_dir")
    if session_dir:
        filtered, download_name = _prepare_consolidated_for_export(session_dir)
        if filtered is not None:
            visible_path = Path(session_dir) / "consolidated_price_visible.xlsx"
            filtered.to_excel(visible_path, index=False)
            return send_file(str(visible_path), as_attachment=True, download_name=download_name)
    output_path = session.get("output_path")
    if output_path and os.path.exists(output_path):
        return send_file(output_path, as_attachment=True, download_name=download_name)
    return redirect(url_for("index", error="Файл не найден. Загрузите прайсы заново."))


@app.route("/api/export-google-sheets", methods=["POST"])
def api_export_google_sheets():
    try:
        import gspread
        from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
        from gspread.utils import rowcol_to_a1
    except ImportError:
        return jsonify({"status": "error", "message": "Не установлен пакет gspread."}), 500

    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    settings = load_app_settings()
    ex = settings.get("export", {})
    sheet_ref = str(ex.get("google_sheets_spreadsheet_url_or_id", "") or "").strip()
    tab = str(ex.get("google_sheets_tab", "Прайс N-Tech") or "Прайс N-Tech").strip() or "Прайс N-Tech"
    sa_raw = str(ex.get("google_sheets_service_account_json", "") or "").strip()
    sid = _parse_google_spreadsheet_id(sheet_ref)
    if not sid:
        return jsonify({
            "status": "error",
            "message": "В настройках не указана ссылка или ID таблицы (поле «Google Таблица — ссылка или ID»).",
        }), 400
    sa_path, sa_err = _resolve_service_account_json_path(sa_raw)
    if not sa_path:
        return jsonify({
            "status": "error",
            "message": sa_err or "Укажите путь к JSON сервисного аккаунта и убедитесь, что файл существует.",
        }), 400

    filtered, _ = _prepare_consolidated_for_export(session_dir)
    if filtered is None:
        return jsonify({"status": "error", "message": "Нет сводного прайса (consolidated_price.xlsx) в текущей сессии."}), 400
    if filtered.empty:
        return jsonify({"status": "error", "message": "Сводный прайс пуст после применения фильтров выгрузки."}), 400

    values = _dataframe_to_sheet_values(filtered)
    if len(values) < 2:
        return jsonify({"status": "error", "message": "Нет строк данных для выгрузки."}), 400

    try:
        gc = gspread.service_account(filename=str(sa_path))
        sh = gc.open_by_key(sid)
    except SpreadsheetNotFound:
        return jsonify({
            "status": "error",
            "message": "Таблица не найдена. Проверьте ID/ссылку и что файл расшарен на e-mail сервисного аккаунта из JSON (доступ «Редактор»).",
        }), 400
    except APIError as e:
        return jsonify({"status": "error", "message": f"Google Sheets API: {e}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Не удалось открыть таблицу: {e}"}), 400

    created = False
    try:
        ws = sh.worksheet(tab)
    except WorksheetNotFound:
        ncols0 = max(len(values[0]), 26)
        nrows0 = max(len(values) + 200, 1000)
        ws = sh.add_worksheet(title=tab[:99], rows=nrows0, cols=ncols0)
        created = True
    if not created:
        try:
            ws.clear()
        except Exception:
            pass

    ncols = len(values[0])
    nvals = len(values)
    # Лист мог быть создан раньше с маленькой сеткой (напр. 4000 строк) — расширяем под весь прайс.
    pad_rows = max(nvals + 200, 1000)
    pad_cols = max(ncols + 2, 26)
    try:
        cur_r = int(ws.row_count)
        cur_c = int(ws.col_count)
    except Exception:
        cur_r, cur_c = pad_rows, pad_cols
    if cur_r < pad_rows or cur_c < pad_cols:
        try:
            ws.resize(rows=max(pad_rows, cur_r), cols=max(pad_cols, cur_c))
        except APIError as e:
            return jsonify({"status": "error", "message": f"Не удалось расширить лист под данные ({nvals} строк): {e}"}), 500
        except Exception as e:
            return jsonify({"status": "error", "message": f"Не удалось расширить лист под данные: {e}"}), 500

    batch = 4000
    try:
        for i in range(0, len(values), batch):
            chunk = values[i : i + batch]
            top = i + 1
            bottom = i + len(chunk)
            rng = f"{rowcol_to_a1(top, 1)}:{rowcol_to_a1(bottom, ncols)}"
            ws.update(chunk, rng, value_input_option="USER_ENTERED")
    except APIError as e:
        return jsonify({"status": "error", "message": f"Ошибка записи в лист: {e}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Ошибка записи в лист: {e}"}), 500

    try:
        full_rng = f"A1:{rowcol_to_a1(len(values), ncols)}"
        ws.format(full_rng, {
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        })
    except Exception:
        pass

    url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    nrows = len(values) - 1
    return jsonify({
        "status": "ok",
        "message": f"Готово: {nrows} строк, {ncols} колонок на листе «{tab}». {url}",
        "spreadsheet_url": url,
        "rows": nrows,
        "columns": ncols,
        "sheet_title": tab,
    })


@app.route("/download/id-quality-report")
def download_id_quality_report():
    session_dir = session.get("session_dir")
    if not session_dir:
        return redirect(url_for("index", error="Нет активной сессии"))
    path = Path(session_dir) / "id_quality_report.csv"
    if not path.exists():
        return redirect(url_for("index", error="ID quality report не найден"))
    return send_file(str(path), as_attachment=True, download_name="id_quality_report.csv")


@app.route("/api/id-quality-report")
def api_id_quality_report():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "no_session"})
    summary_path = Path(session_dir) / "id_quality_report.json"
    report_path = Path(session_dir) / "id_quality_report.csv"
    if not summary_path.exists():
        return jsonify({"status": "not_found"})
    try:
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
    except Exception:
        return jsonify({"status": "error"})
    summary["status"] = "ok"
    summary["has_csv"] = report_path.exists()
    return jsonify(summary)


@app.route("/api/preexport-quality-check")
def api_preexport_quality_check():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Сводный прайс не найден"}), 400

    df = read_consolidated_df(session_dir)
    df = ensure_category_column(df)
    df = apply_visibility_filter(df, session_dir)
    if df.empty:
        return jsonify({
            "status": "ok",
            "checked": 0,
            "missing_id_count": 0,
            "suspicious_price_count": 0,
            "duplicate_count": 0,
            "missing_id_samples": [],
            "suspicious_price_samples": [],
            "duplicate_samples": [],
        })

    missing_id_samples = []
    suspicious_price_samples = []
    duplicate_samples = []

    # 1) Без ID
    missing_mask = []
    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        is_missing = not bool(oid)
        missing_mask.append(is_missing)
        if is_missing and len(missing_id_samples) < 8:
            missing_id_samples.append(f"[{str(row.get('Категория', '')).strip()}] {str(row.get('Название', '')).strip()}")
    missing_id_count = int(sum(1 for x in missing_mask if x))

    # 2) Подозрительная цена по бизнес-логике маржи:
    # сравниваем оптовую "Цена" и розничную "РРЦ".
    # Флагим, если:
    # - опт/РРЦ невалидны,
    # - РРЦ <= опта,
    # - слишком маленькая разница (абсолютная или процентная).
    MIN_MARGIN_PCT = 5.0
    MIN_MARGIN_ABS = 20.0

    raw_wholesale = df.get("Цена", None)
    if raw_wholesale is None:
        raw_wholesale = df.get("Лучшая цена", pd.Series(dtype=float))
    raw_rrc = df.get("РРЦ", pd.Series(dtype=float))

    def _normalize_price_series(series_like):
        return pd.Series(series_like).astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)

    wholesale = pd.to_numeric(_normalize_price_series(raw_wholesale), errors="coerce")
    rrc = pd.to_numeric(_normalize_price_series(raw_rrc), errors="coerce")

    suspicious_mask = []
    for i, row in df.iterrows():
        p = wholesale.loc[i] if i in wholesale.index else np.nan
        r = rrc.loc[i] if i in rrc.index else np.nan
        cat = str(row.get("Категория", "")).strip()
        bad = False
        reason = ""
        if not np.isfinite(p) or p <= 0:
            bad = True
            reason = "невалидный опт"
        elif not np.isfinite(r) or r <= 0:
            bad = True
            reason = "невалидный РРЦ"
        else:
            margin_abs = float(r - p)
            margin_pct = float((margin_abs / p) * 100.0) if p > 0 else -999.0
            if margin_abs <= 0:
                bad = True
                reason = "РРЦ <= опт"
            # Низкая маржа: считаем проблемой, только если одновременно
            # и абсолютная, и процентная маржа ниже порога.
            elif margin_abs < MIN_MARGIN_ABS and margin_pct < MIN_MARGIN_PCT:
                bad = True
                reason = f"низкая маржа (<{MIN_MARGIN_ABS} руб и <{MIN_MARGIN_PCT}%)"
        suspicious_mask.append(bad)
        if bad and len(suspicious_price_samples) < 8:
            raw_opt = row.get("Цена", row.get("Лучшая цена", ""))
            raw_rrc_val = row.get("РРЦ", "")
            shown_opt = ("" if not np.isfinite(p) else round(float(p), 2))
            shown_rrc = ("" if not np.isfinite(r) else round(float(r), 2))
            margin_txt = ""
            if np.isfinite(p) and p > 0 and np.isfinite(r):
                m_abs = float(r - p)
                m_pct = float((m_abs / p) * 100.0)
                margin_txt = f", маржа={round(m_abs, 2)} ({round(m_pct, 2)}%)"
            suspicious_price_samples.append(
                f"[{cat}] {str(row.get('Название', '')).strip()} | причина: {reason or 'проверка цены'} | опт={shown_opt}, РРЦ={shown_rrc}{margin_txt}"
                + (
                    f" (raw опт: {str(raw_opt).strip()}, raw РРЦ: {str(raw_rrc_val).strip()})"
                    if ((not np.isfinite(p) and str(raw_opt).strip()) or (not np.isfinite(r) and str(raw_rrc_val).strip()))
                    else ""
                )
            )
    suspicious_price_count = int(sum(1 for x in suspicious_mask if x))

    # 3) Дубли (поставщик + нормализованное имя)
    dup_map = {}
    for _, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip().lower()
        name_key = _normalize_name_key(row.get("Название", ""))
        if not name_key:
            continue
        key = f"{supplier}|{name_key}"
        dup_map[key] = int(dup_map.get(key, 0)) + 1
    duplicate_count = int(sum(v for v in dup_map.values() if v > 1))
    if duplicate_count:
        for _, row in df.iterrows():
            supplier = str(row.get("Поставщик", "")).strip()
            name = str(row.get("Название", "")).strip()
            key = f"{supplier.lower()}|{_normalize_name_key(name)}"
            if dup_map.get(key, 0) > 1:
                duplicate_samples.append(f"[{supplier}] {name} (x{dup_map.get(key, 0)})")
                if len(duplicate_samples) >= 8:
                    break

    return jsonify({
        "status": "ok",
        "checked": int(len(df)),
        "missing_id_count": missing_id_count,
        "suspicious_price_count": suspicious_price_count,
        "duplicate_count": duplicate_count,
        "missing_id_samples": missing_id_samples,
        "suspicious_price_samples": suspicious_price_samples,
        "duplicate_samples": duplicate_samples,
    })


@app.route("/api/reapply-saved-markups", methods=["POST"])
def api_reapply_saved_markups():
    session_dir = session.get("session_dir")
    if not session_dir:
        return jsonify({"status": "error", "message": "Нет активной сессии"}), 400
    cons_path = Path(session_dir) / "consolidated_price.xlsx"
    if not cons_path.exists():
        return jsonify({"status": "error", "message": "Сводный прайс не найден"}), 400

    df = read_consolidated_df(session_dir)
    if df.empty:
        return jsonify({"status": "ok", "updated_rows": 0})

    if "РРЦ" not in df.columns:
        df["РРЦ"] = ""

    before_rrc = pd.to_numeric(df["РРЦ"], errors="coerce")
    df2 = apply_saved_markups_to_df(df.copy())
    after_rrc = pd.to_numeric(df2.get("РРЦ", pd.Series(dtype=float)), errors="coerce")

    changed = 0
    for i in df2.index:
        b = before_rrc.loc[i] if i in before_rrc.index else np.nan
        a = after_rrc.loc[i] if i in after_rrc.index else np.nan
        if (pd.isna(b) and pd.notna(a)) or (pd.notna(b) and pd.notna(a) and float(b) != float(a)):
            changed += 1

    write_consolidated_df(session_dir, df2)
    write_consolidated_json(df2, Path(session_dir) / "consolidated.json")
    return jsonify({"status": "ok", "updated_rows": int(changed)})


if __name__ == "__main__":
    print("=" * 50)
    print("Price Mixer Web")
    print("Открой в браузере: http://localhost:5001")
    print("=" * 50)
    init_onliner_db()
    # Stable local run mode: no Flask reloader double-process.
    app.run(debug=False, use_reloader=False, load_dotenv=False, host="127.0.0.1", port=5001)


