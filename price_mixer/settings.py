"""Application settings loading, normalization, and persistence."""

import json
import os
import re
import threading
import time
from pathlib import Path

from price_mixer.config import cfg
from price_mixer.runtime_paths import get_runtime_paths

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
RUNTIME_PATHS = get_runtime_paths()
APP_SETTINGS_FILE = RUNTIME_PATHS.state_file("app_settings.json")
AUTO_REFRESH_SETTINGS_FILE = RUNTIME_PATHS.state_file("auto_refresh_settings.json")
ONLINER_API_SETTINGS_FILE = RUNTIME_PATHS.state_file("onliner_api_settings.json")

AUTO_REFRESH_ALLOWED_HOURS = (3, 6, 12)

ONLINER_API_SETTINGS_LOCK = threading.RLock()
ONLINER_API_SETTINGS_CACHE = {"loaded_at": 0.0, "mtime": 0.0, "data": None}
ONLINER_API_DEFAULT_SETTINGS = {
    "proxy_pool": [],
    "allow_direct": True,
    "retry_attempts": 3,
    "backoff_sec": 0.6,
    "proxy_cooldown_sec": 180,
    "max_parallel_workers": 10,
}


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


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _read_onliner_api_settings():
    data = _read_json_file(ONLINER_API_SETTINGS_FILE)

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
    _write_json_file(ONLINER_API_SETTINGS_FILE, payload)
    with ONLINER_API_SETTINGS_LOCK:
        ONLINER_API_SETTINGS_CACHE["loaded_at"] = time.time()
        ONLINER_API_SETTINGS_CACHE["mtime"] = ONLINER_API_SETTINGS_FILE.stat().st_mtime if ONLINER_API_SETTINGS_FILE.exists() else 0.0
        ONLINER_API_SETTINGS_CACHE["data"] = dict(payload)
    return dict(payload)


def get_onliner_api_max_workers(default=10):
    settings = load_onliner_api_settings()
    return _coerce_int(settings.get("max_parallel_workers", default), default, min_value=1, max_value=24)


def _normalize_auto_refresh_settings(data=None):
    data = data or {}
    if not isinstance(data, dict):
        data = {}
    enabled = bool(data.get("enabled", False))
    interval = int(data.get("interval_hours", 12) or 12)
    if interval not in AUTO_REFRESH_ALLOWED_HOURS:
        interval = 12
    return {
        "enabled": enabled,
        "interval_hours": interval,
        "last_run_ts": int(data.get("last_run_ts", 0) or 0),
        "last_started_ts": int(data.get("last_started_ts", 0) or 0),
        "last_status": str(data.get("last_status", "idle") or "idle"),
        "last_count": int(data.get("last_count", 0) or 0),
        "last_message": str(data.get("last_message", "") or ""),
    }


def load_auto_refresh_settings():
    return _normalize_auto_refresh_settings(_read_json_file(AUTO_REFRESH_SETTINGS_FILE))


def save_auto_refresh_settings(settings):
    payload = _normalize_auto_refresh_settings(settings)
    _write_json_file(AUTO_REFRESH_SETTINGS_FILE, payload)
    return payload


APP_SETTINGS_DEFAULTS = {
    "export": {
        "include_without_id": False,
        "price_name": "consolidated_price",
        "keep_lowest_price_per_onliner_id": True,
        "exclude_category_prefixes": ["Требует сортировки"],
        "exclude_name_contains": ["патрон", "milwaukee", "p.i.t"],
        "exclude_duplicate_id_suppliers": [],
        "only_pc_suppliers": [],
        "only_pc_price_name": "N-tech_TGPC_Beznal",
        "google_sheets_spreadsheet_url_or_id": "",
        "google_sheets_tab": "",
        "google_sheets_service_account_json": "",
    },
    "onliner_db_import": {"google_sheet_id": "", "google_sheet_name": "All_Catalog"},
    "ui": {"show_checks_block": True},
    "cache_api": ONLINER_API_DEFAULT_SETTINGS,
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
            {"pattern": "ntech", "supplier": "N-Tech"},
            {"pattern": "n-tech", "supplier": "N-Tech"},
            {"pattern": "n_tech", "supplier": "N-Tech"},
            {"pattern": "iven_zakaz", "supplier": "IVEN_zakaz"},
            {"pattern": "iven-zakaz", "supplier": "IVEN_zakaz"},
            {"pattern": "ivenzakaz", "supplier": "IVEN_zakaz"},
            {"pattern": "iven", "supplier": "IVEN"},
            {"pattern": "tradex", "supplier": "Tradex"},
            {"pattern": "1030z", "supplier": "BN-1030Z"},
            {"pattern": "1030", "supplier": "BN-1030"},
            {"pattern": "1374", "supplier": "BN-1374"},
            {"pattern": "price_bn", "supplier": "TGPC"},
        ],
    },
    "api_sources": {
        "iven": {"enabled": False, "label": "IVEN", "supplier": "IVEN", "mode": "direct_file", "file_url": "", "verify_ssl": False},
        "iven_zakaz": {"enabled": False, "label": "IVEN_ZAKAZ", "supplier": "IVEN_zakaz", "mode": "direct_file", "file_url": "", "verify_ssl": False},
        "tradex": {"enabled": False, "label": "Tradex", "supplier": "Tradex", "mode": "direct_file", "file_url": "", "verify_ssl": False},
        "ntech": {"enabled": False, "label": "N-Tech", "supplier": "N-Tech", "mode": "ntech_json", "auth_url": "", "price_url": "", "username": "", "password": "", "verify_ssl": False},
    },
    "uploads_cleanup": {"keep_last_sessions": 20, "keep_days": 7, "keep_api_fetch_hours": 12},
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
    out = list(APP_SETTINGS_DEFAULTS["suppliers"]["filename_rules"])
    if not isinstance(rules, list):
        return out
    seen = {str(item.get("pattern", "")).strip().lower() for item in out}
    for item in rules:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern", "")).strip()
        supplier = str(item.get("supplier", "")).strip()
        if not pattern or not supplier:
            continue
        supplier_compact = supplier.lower().replace("-", "").replace("_", "").replace(" ", "")
        if supplier_compact == "ntech":
            supplier = "N-Tech"
        elif supplier_compact == "ivenzakaz":
            supplier = "IVEN_zakaz"
        elif supplier_compact == "iven":
            supplier = "IVEN"
        pattern_key = pattern.lower()
        if pattern_key in seen:
            out = [
                {"pattern": pattern, "supplier": supplier}
                if str(existing.get("pattern", "")).strip().lower() == pattern_key
                else existing
                for existing in out
            ]
            continue
        out.append({"pattern": pattern, "supplier": supplier})
        seen.add(pattern_key)
    return out


def _normalize_api_sources(sources):
    defaults = APP_SETTINGS_DEFAULTS["api_sources"]
    out = {}
    raw = sources if isinstance(sources, dict) else {}
    for key, default_cfg in defaults.items():
        source_cfg = raw.get(key, {}) if isinstance(raw.get(key), dict) else {}
        mode = str(source_cfg.get("mode", default_cfg.get("mode", "direct_file"))).strip() or default_cfg.get("mode", "direct_file")
        item = {
            "enabled": _coerce_bool(source_cfg.get("enabled", default_cfg.get("enabled", False)), default=bool(default_cfg.get("enabled", False))),
            "label": str(source_cfg.get("label", default_cfg.get("label", key.upper()))).strip()[:40] or str(default_cfg.get("label", key.upper())),
            "supplier": str(source_cfg.get("supplier", default_cfg.get("supplier", key.upper()))).strip()[:80] or str(default_cfg.get("supplier", key.upper())),
            "mode": mode,
            "verify_ssl": _coerce_bool(source_cfg.get("verify_ssl", default_cfg.get("verify_ssl", False)), default=bool(default_cfg.get("verify_ssl", False))),
        }
        if mode == "ntech_json":
            item.update({
                "auth_url": str(source_cfg.get("auth_url", default_cfg.get("auth_url", ""))).strip(),
                "price_url": str(source_cfg.get("price_url", default_cfg.get("price_url", ""))).strip(),
                "username": str(source_cfg.get("username", default_cfg.get("username", ""))).strip(),
                "password": str(source_cfg.get("password", default_cfg.get("password", ""))),
            })
        else:
            item.update({"file_url": str(source_cfg.get("file_url", default_cfg.get("file_url", ""))).strip()})
        out[key] = item
    return out


def _normalize_supplier_name_list(value):
    raw_items = value if isinstance(value, list) else re.split(r"[\r\n,;]+", str(value or ""))
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


def _normalize_text_list(value, limit=120):
    raw_items = value if isinstance(value, list) else re.split(r"[\r\n;]+", str(value or ""))
    out = []
    seen = set()
    for item in raw_items:
        text = str(item or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text[:limit])
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
            "include_without_id": _coerce_bool(export.get("include_without_id", False), default=False),
            "price_name": re.sub(r"[^A-Za-zА-Яа-я0-9._ -]+", "", str(export.get("price_name", "consolidated_price")).strip())[:80] or "consolidated_price",
            "keep_lowest_price_per_onliner_id": _coerce_bool(export.get("keep_lowest_price_per_onliner_id", True), default=True),
            "exclude_category_prefixes": _normalize_text_list(export.get("exclude_category_prefixes", []), limit=120),
            "exclude_name_contains": _normalize_text_list(export.get("exclude_name_contains", []), limit=120),
            "exclude_duplicate_id_suppliers": _normalize_supplier_name_list(export.get("exclude_duplicate_id_suppliers", [])),
            "only_pc_suppliers": _normalize_supplier_name_list(export.get("only_pc_suppliers", [])),
            "only_pc_price_name": re.sub(r"[^A-Za-zА-Яа-я0-9._ -]+", "", str(export.get("only_pc_price_name", "N-tech_TGPC_Beznal")).strip())[:80] or "N-tech_TGPC_Beznal",
            "google_sheets_spreadsheet_url_or_id": str(export.get("google_sheets_spreadsheet_url_or_id", "") or "").strip()[:500],
            "google_sheets_tab": str(export.get("google_sheets_tab", "") or "").strip()[:99],
            "google_sheets_service_account_json": str(export.get("google_sheets_service_account_json", "") or "").strip()[:500],
        },
        "onliner_db_import": {
            "google_sheet_id": str(onliner_db_import.get("google_sheet_id", "") or "").strip()[:240],
            "google_sheet_name": str(onliner_db_import.get("google_sheet_name", "All_Catalog") or "All_Catalog").strip()[:120] or "All_Catalog",
        },
        "ui": {"show_checks_block": _coerce_bool(ui.get("show_checks_block", True), default=True)},
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
        "suppliers": {"filename_rules": _normalize_filename_rules(suppliers.get("filename_rules", []))},
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
    }


def _overlay_env_secrets(data):
    b2b = data.setdefault("onliner_b2b", {})
    if not str(b2b.get("client_id") or "").strip():
        b2b["client_id"] = cfg.onliner_b2b_client_id
    if not str(b2b.get("client_secret") or "").strip():
        b2b["client_secret"] = cfg.onliner_b2b_client_secret

    export = data.setdefault("export", {})
    if not str(export.get("google_sheets_spreadsheet_url_or_id") or "").strip():
        export["google_sheets_spreadsheet_url_or_id"] = cfg.google_sheets_spreadsheet_id
    if not str(export.get("google_sheets_service_account_json") or "").strip():
        export["google_sheets_service_account_json"] = cfg.google_sheets_sa_json
    if not str(export.get("google_sheets_tab") or "").strip() and str(cfg.google_sheets_tab or "").strip():
        export["google_sheets_tab"] = cfg.google_sheets_tab

    db_import = data.setdefault("onliner_db_import", {})
    if not str(db_import.get("google_sheet_id") or "").strip():
        db_import["google_sheet_id"] = cfg.google_sheets_spreadsheet_id
    if not str(db_import.get("google_sheet_name") or "").strip():
        db_import["google_sheet_name"] = cfg.onliner_db_sheet_name

    sources = data.setdefault("api_sources", {})
    iven = sources.setdefault("iven", {})
    if not str(iven.get("file_url") or "").strip():
        iven["file_url"] = cfg.iven_file_url
    sources.setdefault("iven_zakaz", {})
    tradex = sources.setdefault("tradex", {})
    if not str(tradex.get("file_url") or "").strip():
        tradex["file_url"] = cfg.tradex_file_url
    ntech = sources.setdefault("ntech", {})
    if not str(ntech.get("username") or "").strip():
        ntech["username"] = cfg.ntech_username
    if not str(ntech.get("password") or "").strip():
        ntech["password"] = cfg.ntech_password
    return data


def load_app_settings():
    data = _normalize_app_settings(_read_json_file(APP_SETTINGS_FILE))
    try:
        return _overlay_env_secrets(data)
    except Exception:
        return data


def _strip_persisted_secrets(payload):
    b2b = payload.get("onliner_b2b")
    if isinstance(b2b, dict):
        b2b["client_id"] = ""
        b2b["client_secret"] = ""
    export = payload.get("export")
    if isinstance(export, dict):
        export["google_sheets_spreadsheet_url_or_id"] = str(export.get("google_sheets_spreadsheet_url_or_id", "") or "").strip()
        export["google_sheets_service_account_json"] = ""
        export["google_sheets_tab"] = str(export.get("google_sheets_tab", "") or "").strip()
    db_import = payload.get("onliner_db_import")
    if isinstance(db_import, dict):
        db_import["google_sheet_id"] = ""
        db_import["google_sheet_name"] = ""
    sources = payload.get("api_sources")
    if isinstance(sources, dict):
        for key in ("iven", "iven_zakaz", "tradex"):
            source = sources.get(key)
            if isinstance(source, dict):
                source["file_url"] = ""
        ntech = sources.get("ntech")
        if isinstance(ntech, dict):
            ntech["username"] = ""
            ntech["password"] = ""
    return payload


def save_app_settings(settings):
    payload = _strip_persisted_secrets(_normalize_app_settings(settings))
    _write_json_file(APP_SETTINGS_FILE, payload)
    save_onliner_api_settings(payload.get("cache_api", {}))
    return payload
