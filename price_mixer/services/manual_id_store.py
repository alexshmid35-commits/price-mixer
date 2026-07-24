"""Persistent storage helpers for manual Onliner ID decisions."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from price_mixer.logging_config import get_logger
from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.state_store import load_dict, load_list, save_dict, save_list


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATHS = get_runtime_paths()
MANUAL_ID_BINDINGS_FILE = RUNTIME_PATHS.state_file("manual_id_bindings.json")
ID_CHANGE_JOURNAL_FILE = RUNTIME_PATHS.state_file("id_change_journal.json")
ID_CHANGE_JOURNAL_LIMIT = 5000
MANUAL_BINDINGS_MIGRATION_KEY = "manual_bindings_v2_migrated"
ID_JOURNAL_MIGRATION_KEY = "id_change_journal_v1_migrated"
_ID_JOURNAL_LOCK = threading.RLock()
LOGGER = get_logger("price_mixer.state.manual_ids")


def load_manual_id_bindings(path=None, get_db_func=None):
    if path is not None:
        return _clean_bindings(load_dict(Path(path)))

    db = _prepare_db(get_db_func)
    if db is None:
        return _clean_bindings(load_dict(MANUAL_ID_BINDINGS_FILE))

    try:
        if db.get_state_meta(MANUAL_BINDINGS_MIGRATION_KEY) == "1":
            return _clean_bindings(db.get_manual_bindings())

        json_bindings = _clean_bindings(load_dict(MANUAL_ID_BINDINGS_FILE))
        db.replace_manual_bindings(json_bindings)
        migrated = _clean_bindings(db.get_manual_bindings())
        if migrated != json_bindings:
            raise RuntimeError("manual binding migration verification failed")
        db.set_state_meta(MANUAL_BINDINGS_MIGRATION_KEY, "1")
        return migrated
    except Exception as exc:
        LOGGER.warning("SQLite manual bindings load failed, using JSON: %s", exc)
        return _clean_bindings(load_dict(MANUAL_ID_BINDINGS_FILE))


def save_manual_id_bindings(bindings, path=None, get_db_func=None):
    cleaned = _clean_bindings(bindings)
    if path is not None:
        save_dict(Path(path), cleaned)
        return

    db = _prepare_db(get_db_func)
    if db is not None:
        try:
            db.replace_manual_bindings(cleaned)
            saved = _clean_bindings(db.get_manual_bindings())
            if saved != cleaned:
                raise RuntimeError("manual binding save verification failed")
            db.set_state_meta(MANUAL_BINDINGS_MIGRATION_KEY, "1")
        except Exception as exc:
            LOGGER.warning(
                "SQLite manual bindings save failed, JSON remains primary: %s", exc
            )
    save_dict(MANUAL_ID_BINDINGS_FILE, cleaned)


def load_id_change_journal(path=None, get_db_func=None, limit=ID_CHANGE_JOURNAL_LIMIT):
    if path is not None:
        return _clean_journal_rows(load_list(Path(path)), limit)

    db = _prepare_db(get_db_func)
    if db is None:
        return _clean_journal_rows(load_list(ID_CHANGE_JOURNAL_FILE), limit)
    try:
        with _ID_JOURNAL_LOCK:
            _ensure_id_journal_migrated(db, limit)
            return _clean_journal_rows(db.get_id_journal(limit), limit)
    except Exception as exc:
        LOGGER.warning("SQLite ID journal load failed, using JSON: %s", exc)
        return _clean_journal_rows(load_list(ID_CHANGE_JOURNAL_FILE), limit)


def save_id_change_journal(rows, path=None, get_db_func=None, limit=ID_CHANGE_JOURNAL_LIMIT):
    cleaned = _clean_journal_rows(rows, limit)
    if path is not None:
        save_list(Path(path), cleaned, limit=limit)
        return

    db = _prepare_db(get_db_func)
    if db is not None:
        try:
            with _ID_JOURNAL_LOCK:
                db.replace_id_journal(cleaned, limit=limit)
                saved = _clean_journal_rows(db.get_id_journal(limit), limit)
                if saved != cleaned:
                    raise RuntimeError("ID journal save verification failed")
                db.set_state_meta(ID_JOURNAL_MIGRATION_KEY, "1")
                return
        except Exception as exc:
            LOGGER.warning("SQLite ID journal save failed, using JSON: %s", exc)
    save_list(ID_CHANGE_JOURNAL_FILE, cleaned, limit=limit)


def append_id_change_journal(entry, path=None, get_db_func=None, limit=ID_CHANGE_JOURNAL_LIMIT):
    cleaned = _clean_journal_entry(entry)
    if path is not None:
        rows = _clean_journal_rows(load_list(Path(path)), limit)
        rows.append(cleaned)
        save_list(Path(path), rows, limit=limit)
        return

    db = _prepare_db(get_db_func)
    if db is not None:
        try:
            with _ID_JOURNAL_LOCK:
                _ensure_id_journal_migrated(db, limit)
                db.append_id_journal(
                    cleaned["ts"],
                    cleaned["action"],
                    cleaned["source"],
                    cleaned["changes"],
                    session_dir=cleaned["session_dir"],
                    limit=limit,
                )
                return
        except Exception as exc:
            LOGGER.warning("SQLite ID journal append failed, using JSON: %s", exc)
    rows = _clean_journal_rows(load_list(ID_CHANGE_JOURNAL_FILE), limit)
    rows.append(cleaned)
    save_list(ID_CHANGE_JOURNAL_FILE, rows, limit=limit)


def is_manually_confirmed_id(
    name,
    onliner_id,
    supplier_name="",
    load_bindings=load_manual_id_bindings,
    normalize_name_key_func=None,
):
    oid = normalize_onliner_id(onliner_id)
    name_key = normalize_name_key_func(name) if callable(normalize_name_key_func) else str(name or "").strip().lower()
    if not oid or not name_key:
        return False
    supplier_token = _supplier_key_token(supplier_name)
    binding_key = f"supplier:{supplier_token}:{name_key}" if supplier_token else name_key
    bindings = load_bindings()
    rec = bindings.get(binding_key)
    if not isinstance(rec, dict) and supplier_token:
        legacy = bindings.get(name_key)
        if isinstance(legacy, dict) and _record_matches_supplier(legacy, supplier_name):
            rec = legacy
    if not isinstance(rec, dict):
        return False
    if bool(rec.get("blocked", False)):
        return False
    return normalize_onliner_id(rec.get("id", "")) == oid


def supplier_scoped_binding_key(name_key, supplier_name):
    """Return the durable binding key for one supplier and one normalized name."""
    base_key = str(name_key or "").strip()
    supplier_token = _supplier_key_token(supplier_name)
    if not base_key or not supplier_token:
        return base_key
    return f"supplier:{supplier_token}:{base_key}"


def build_supplier_binding_record(onliner_id, url="", supplier_name="", *, blocked=False):
    record = {
        "id": normalize_onliner_id(onliner_id),
        "url": str(url or "").strip(),
    }
    supplier = str(supplier_name or "").strip()
    if supplier:
        record["suppliers"] = [supplier]
    if blocked:
        record["blocked"] = True
    return record


def _supplier_key_token(supplier_name):
    token = str(supplier_name or "").strip().lower()
    token = token.replace(" ", "_").replace("-", "_")
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_")


def _record_matches_supplier(record, supplier_name):
    raw = record.get("suppliers", record.get("supplier", "")) if isinstance(record, dict) else ""
    if isinstance(raw, str):
        suppliers = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        suppliers = [str(part or "").strip() for part in raw if str(part or "").strip()]
    else:
        suppliers = []
    expected = _supplier_key_token(supplier_name)
    return bool(expected and any(_supplier_key_token(item) == expected for item in suppliers))


def migrate_bindings_to_supplier_scope(bindings, suppliers_by_key=None, default_suppliers=None):
    """Convert legacy global records into independent supplier-scoped records."""
    cleaned = _clean_bindings(bindings)
    suppliers_by_key = suppliers_by_key if isinstance(suppliers_by_key, dict) else {}
    defaults = _unique_suppliers(default_suppliers or [])
    migrated = {}
    created = 0
    unresolved = 0

    for key, record in cleaned.items():
        if str(key).startswith("supplier:"):
            migrated[key] = record
            continue

        explicit = record.get("suppliers", []) if isinstance(record, dict) else []
        suppliers = _unique_suppliers(explicit or suppliers_by_key.get(key, []) or defaults)
        if not suppliers:
            unresolved += 1
            migrated[key] = record
            continue

        for supplier in suppliers:
            supplier_token = _supplier_key_token(supplier)
            if not supplier_token:
                continue
            scoped_key = f"supplier:{supplier_token}:{key}"
            scoped_record = dict(record)
            scoped_record["suppliers"] = [supplier]
            if scoped_key not in migrated:
                migrated[scoped_key] = scoped_record
                created += 1

    return migrated, {
        "before": len(cleaned),
        "after": len(migrated),
        "created_scoped": created,
        "unresolved_global": unresolved,
    }


def _unique_suppliers(values):
    out = []
    seen = set()
    for value in values or []:
        supplier = str(value or "").strip()
        token = _supplier_key_token(supplier)
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(supplier)
    return out


def _clean_bindings(bindings):
    if not isinstance(bindings, dict):
        return {}
    cleaned = {}
    for raw_key, raw_info in bindings.items():
        name_key = str(raw_key or "").strip()
        if not name_key or not isinstance(raw_info, dict):
            continue
        record = {
            "id": normalize_onliner_id(raw_info.get("id", "")),
            "url": str(raw_info.get("url", "") or "").strip(),
        }
        if bool(raw_info.get("blocked", False)):
            record["blocked"] = True
        raw_suppliers = raw_info.get("suppliers", None)
        if raw_suppliers is None:
            raw_suppliers = raw_info.get("supplier", "")
        if isinstance(raw_suppliers, str):
            suppliers = [part.strip() for part in raw_suppliers.replace(";", ",").split(",") if part.strip()]
        elif isinstance(raw_suppliers, (list, tuple, set)):
            suppliers = [str(part or "").strip() for part in raw_suppliers if str(part or "").strip()]
        else:
            suppliers = []
        if suppliers:
            record["suppliers"] = list(dict.fromkeys(suppliers))
        cleaned[name_key] = record
    return cleaned


def _clean_journal_entry(entry):
    entry = entry if isinstance(entry, dict) else {}
    changes = entry.get("changes", [])
    if not isinstance(changes, list):
        changes = []
    return {
        "ts": int(entry.get("ts", int(time.time())) or int(time.time())),
        "action": str(entry.get("action", "") or ""),
        "session_dir": str(entry.get("session_dir", "") or ""),
        "source": str(entry.get("source", "") or ""),
        "changes": changes,
    }


def _clean_journal_rows(rows, limit=ID_CHANGE_JOURNAL_LIMIT):
    if not isinstance(rows, list):
        return []
    cleaned = [_clean_journal_entry(row) for row in rows if isinstance(row, dict)]
    return cleaned[-max(0, int(limit or 0)):]


def _ensure_id_journal_migrated(db, limit=ID_CHANGE_JOURNAL_LIMIT):
    if db.get_state_meta(ID_JOURNAL_MIGRATION_KEY) == "1":
        return
    json_rows = _clean_journal_rows(load_list(ID_CHANGE_JOURNAL_FILE), limit)
    db.replace_id_journal(json_rows, limit=limit)
    migrated = _clean_journal_rows(db.get_id_journal(limit), limit)
    if migrated != json_rows:
        raise RuntimeError("ID journal migration verification failed")
    db.set_state_meta(ID_JOURNAL_MIGRATION_KEY, "1")


def _prepare_db(get_db_func=None):
    try:
        db = get_db_func() if callable(get_db_func) else _get_db()
        db.run_migrations()
        return db
    except Exception as exc:
        LOGGER.warning("SQLite manual bindings unavailable: %s", exc)
        return None


def _load_db_bindings(get_db_func=None):
    try:
        db = get_db_func() if callable(get_db_func) else _get_db()
        return _clean_bindings(db.get_manual_bindings())
    except Exception:
        return {}


def _save_db_bindings(bindings, get_db_func=None):
    try:
        db = get_db_func() if callable(get_db_func) else _get_db()
        for name_key, info in bindings.items():
            db.set_manual_binding(name_key, info.get("id", ""), info.get("url", ""))
    except Exception:
        pass


def _append_db_journal(entry, get_db_func=None):
    try:
        db = get_db_func() if callable(get_db_func) else _get_db()
        db.append_id_journal(
            entry.get("ts", int(time.time())),
            entry.get("action", ""),
            entry.get("source", ""),
            entry.get("changes", []),
        )
    except Exception:
        pass


def _get_db():
    from price_mixer.db import get_db

    return get_db()
