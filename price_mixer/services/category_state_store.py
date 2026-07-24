"""SQLite-backed storage for category runtime configuration documents."""

from __future__ import annotations

import copy
import threading
from pathlib import Path

from price_mixer.logging_config import get_logger
from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.state_store import load_dict, save_dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATHS = get_runtime_paths()
CATEGORY_OVERRIDES_STATE = "category_overrides"
MANUAL_CATEGORY_OVERRIDES_STATE = "manual_category_overrides"
CATEGORY_VISIBILITY_STATE = "category_visibility"
CATEGORY_MARKUPS_STATE = "category_markups"

CATEGORY_STATE_PATHS = {
    CATEGORY_OVERRIDES_STATE: RUNTIME_PATHS.state_file("category_overrides.json"),
    MANUAL_CATEGORY_OVERRIDES_STATE: RUNTIME_PATHS.state_file("manual_category_overrides.json"),
    CATEGORY_VISIBILITY_STATE: RUNTIME_PATHS.state_file("category_visibility.json"),
    CATEGORY_MARKUPS_STATE: RUNTIME_PATHS.state_file("category_markups.json"),
}

_STATE_LOCK = threading.RLock()
_STATE_CACHE = {}
_PREPARED_DBS = set()
_MIGRATED_STATES = set()
LOGGER = get_logger("price_mixer.state.category")


def load_category_state(state_key, json_path=None, get_db_func=None, *, sqlite_primary=True):
    path = Path(json_path or CATEGORY_STATE_PATHS[state_key])
    if not sqlite_primary:
        return load_dict(path)

    db = _prepare_db(get_db_func)
    if db is None:
        return load_dict(path)
    try:
        with _STATE_LOCK:
            _ensure_migrated(db, state_key, path)
            cache_key = _cache_key(db, state_key)
            revision = db.get_runtime_state_revisions([state_key]).get(state_key, 0)
            cached = _STATE_CACHE.get(cache_key)
            if cached is not None and cached[0] == revision:
                return copy.deepcopy(cached[1])
            payload, loaded_revision = db.get_runtime_state_json(state_key)
            if not isinstance(payload, dict) or not loaded_revision:
                raise RuntimeError(f"missing SQLite category state: {state_key}")
            _STATE_CACHE[cache_key] = (loaded_revision, payload)
            return copy.deepcopy(payload)
    except Exception as exc:
        LOGGER.warning(
            "SQLite load failed for %s, using JSON: %s", state_key, exc
        )
        return load_dict(path)


def save_category_state(payload, state_key, json_path=None, get_db_func=None, *, sqlite_primary=True):
    path = Path(json_path or CATEGORY_STATE_PATHS[state_key])
    cleaned = dict(payload) if isinstance(payload, dict) else {}
    if not sqlite_primary:
        save_dict(path, cleaned)
        return

    db = _prepare_db(get_db_func)
    if db is not None:
        try:
            with _STATE_LOCK:
                revision = db.set_runtime_state_json(state_key, cleaned)
                saved, saved_revision = db.get_runtime_state_json(state_key)
                if saved != cleaned or saved_revision != revision:
                    raise RuntimeError(f"category state save verification failed: {state_key}")
                db.set_state_meta(_migration_key(state_key), "1")
                _MIGRATED_STATES.add(_cache_key(db, state_key))
                _STATE_CACHE[_cache_key(db, state_key)] = (revision, copy.deepcopy(cleaned))
                return
        except Exception as exc:
            LOGGER.warning(
                "SQLite save failed for %s, using JSON: %s", state_key, exc
            )
    save_dict(path, cleaned)


def category_state_signature(state_keys=None, get_db_func=None):
    keys = list(state_keys or CATEGORY_STATE_PATHS.keys())
    db = _prepare_db(get_db_func)
    if db is None:
        return tuple((key, *_file_signature(CATEGORY_STATE_PATHS[key])) for key in keys)
    try:
        with _STATE_LOCK:
            for key in keys:
                _ensure_migrated(db, key, CATEGORY_STATE_PATHS[key])
            revisions = db.get_runtime_state_revisions(keys)
            return tuple((key, revisions.get(key, 0)) for key in keys)
    except Exception as exc:
        LOGGER.warning("SQLite signature failed, using JSON: %s", exc)
        return tuple((key, *_file_signature(CATEGORY_STATE_PATHS[key])) for key in keys)


def clear_category_state_cache():
    with _STATE_LOCK:
        _STATE_CACHE.clear()
        _PREPARED_DBS.clear()
        _MIGRATED_STATES.clear()


def _ensure_migrated(db, state_key, path):
    state_identity = _cache_key(db, state_key)
    if state_identity in _MIGRATED_STATES:
        return
    migration_key = _migration_key(state_key)
    if db.get_state_meta(migration_key) == "1":
        _MIGRATED_STATES.add(state_identity)
        return
    json_payload = load_dict(path)
    revision = db.set_runtime_state_json(state_key, json_payload)
    migrated, migrated_revision = db.get_runtime_state_json(state_key)
    if migrated != json_payload or migrated_revision != revision:
        raise RuntimeError(f"category state migration verification failed: {state_key}")
    db.set_state_meta(migration_key, "1")
    _MIGRATED_STATES.add(state_identity)
    _STATE_CACHE[state_identity] = (revision, copy.deepcopy(migrated))


def _migration_key(state_key):
    return f"category_state_{state_key}_v1_migrated"


def _cache_key(db, state_key):
    return _db_identity(db), state_key


def _db_identity(db):
    db_path = getattr(db, "path", None)
    if db_path is None:
        return f"object:{id(db)}"
    try:
        db_path = str(Path(db_path).resolve())
    except Exception:
        db_path = str(db_path)
    return db_path


def _file_signature(path):
    try:
        stat = Path(path).stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


def _prepare_db(get_db_func=None):
    try:
        db = get_db_func() if callable(get_db_func) else _get_db()
        identity = _db_identity(db)
        with _STATE_LOCK:
            if identity not in _PREPARED_DBS:
                db.run_migrations()
                _PREPARED_DBS.add(identity)
        return db
    except Exception as exc:
        LOGGER.warning("SQLite unavailable: %s", exc)
        return None


def _get_db():
    from price_mixer.db import get_db

    return get_db()
