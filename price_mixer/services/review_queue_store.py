"""SQLite-backed persistence for the manual ID review queue."""

from __future__ import annotations

import threading
from pathlib import Path

from price_mixer.logging_config import get_logger
from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.state_store import load_dict, save_dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REVIEW_QUEUE_FILE = get_runtime_paths().state_file("id_review_queue.json")
REVIEW_QUEUE_MIGRATION_KEY = "review_queue_v1_migrated"
_REVIEW_QUEUE_LOCK = threading.RLock()
LOGGER = get_logger("price_mixer.state.review_queue")


def load_review_queue(path=None, get_db_func=None):
    if path is not None:
        return _clean_queue(load_dict(Path(path)))

    db = _prepare_db(get_db_func)
    if db is None:
        return _clean_queue(load_dict(REVIEW_QUEUE_FILE))

    try:
        with _REVIEW_QUEUE_LOCK:
            if db.get_state_meta(REVIEW_QUEUE_MIGRATION_KEY) == "1":
                return _clean_queue(db.get_review_queue())

            json_queue = _clean_queue(load_dict(REVIEW_QUEUE_FILE))
            db.replace_review_queue(json_queue)
            migrated = _clean_queue(db.get_review_queue())
            if migrated != json_queue:
                raise RuntimeError("review queue migration verification failed")
            db.set_state_meta(REVIEW_QUEUE_MIGRATION_KEY, "1")
            return migrated
    except Exception as exc:
        LOGGER.warning("SQLite review queue load failed, using JSON: %s", exc)
        return _clean_queue(load_dict(REVIEW_QUEUE_FILE))


def save_review_queue(queue, path=None, get_db_func=None):
    cleaned = _clean_queue(queue)
    if path is not None:
        save_dict(Path(path), cleaned)
        return

    db = _prepare_db(get_db_func)
    if db is not None:
        try:
            with _REVIEW_QUEUE_LOCK:
                db.replace_review_queue(cleaned)
                saved = _clean_queue(db.get_review_queue())
                if saved != cleaned:
                    raise RuntimeError("review queue save verification failed")
                db.set_state_meta(REVIEW_QUEUE_MIGRATION_KEY, "1")
                return
        except Exception as exc:
            LOGGER.warning("SQLite review queue save failed, using JSON: %s", exc)
    save_dict(REVIEW_QUEUE_FILE, cleaned)


def _clean_queue(queue):
    if not isinstance(queue, dict):
        return {}
    return {
        str(key): dict(entry)
        for key, entry in queue.items()
        if str(key or "").strip() and isinstance(entry, dict)
    }


def _prepare_db(get_db_func=None):
    try:
        db = get_db_func() if callable(get_db_func) else _get_db()
        db.run_migrations()
        return db
    except Exception as exc:
        LOGGER.warning("SQLite review queue unavailable: %s", exc)
        return None


def _get_db():
    from price_mixer.db import get_db

    return get_db()
