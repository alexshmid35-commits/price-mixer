"""Supplier snapshot, diff, and API fetch history helpers."""

import time
from pathlib import Path

import pandas as pd

from price_mixer.logging_config import get_logger
from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.services.product_normalization import normalize_name_key, normalize_onliner_id
from price_mixer.state_store import load_dict, load_list, save_dict, save_list

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATHS = get_runtime_paths()
API_FETCH_HISTORY_FILE = RUNTIME_PATHS.state_file("api_fetch_history.json")
SUPPLIER_SNAPSHOTS_FILE = RUNTIME_PATHS.state_file("supplier_snapshots.json")
LOGGER = get_logger("price_mixer.supplier_snapshots")


def load_supplier_snapshots():
    data = load_dict(SUPPLIER_SNAPSHOTS_FILE)
    return data if isinstance(data.get("suppliers"), dict) else {"suppliers": {}}


def save_supplier_snapshots(data):
    suppliers = data.get("suppliers", {}) if isinstance(data, dict) else {}
    normalized = {"suppliers": {}}
    for supplier, sessions in suppliers.items():
        normalized_sessions = _normalize_supplier_sessions(sessions)
        if normalized_sessions:
            normalized["suppliers"][str(supplier)] = normalized_sessions
    save_dict(SUPPLIER_SNAPSHOTS_FILE, normalized)


def latest_supplier_snapshot(data, supplier):
    suppliers = data.get("suppliers", {}) if isinstance(data, dict) else {}
    sessions = suppliers.get(supplier, {}) if isinstance(suppliers, dict) else {}
    sessions = _normalize_supplier_sessions(sessions)
    if not sessions:
        return {}
    return max(sessions.values(), key=lambda snap: int((snap or {}).get("updated_at", 0) or 0))


def upsert_supplier_snapshot(data, supplier, session_id, snapshot, max_sessions=5):
    if not isinstance(data, dict):
        data = {}
    suppliers = data.setdefault("suppliers", {})
    sessions = _normalize_supplier_sessions(suppliers.get(supplier, {}))
    sessions[str(session_id or "latest")] = snapshot if isinstance(snapshot, dict) else {}
    ordered = sorted(
        sessions.items(),
        key=lambda item: int(((item[1] or {}).get("updated_at", 0) or 0)),
        reverse=True,
    )
    suppliers[supplier] = dict(ordered[:max(1, int(max_sessions or 5))])
    return data


def load_api_fetch_history():
    return load_list(API_FETCH_HISTORY_FILE)


def save_api_fetch_history(rows):
    save_list(API_FETCH_HISTORY_FILE, rows, limit=300)


def append_api_fetch_history(entry):
    if not isinstance(entry, dict):
        return
    rows = load_api_fetch_history()
    rows.append(entry)
    rows.sort(key=lambda x: int((x or {}).get("finished_at", 0) or (x or {}).get("started_at", 0) or 0), reverse=True)
    save_api_fetch_history(rows)


def _normalize_supplier_sessions(sessions):
    if not isinstance(sessions, dict):
        return {}
    if "items" in sessions and "updated_at" in sessions:
        return {"latest": sessions}
    out = {}
    for session_id, snapshot in sessions.items():
        if isinstance(snapshot, dict) and "items" in snapshot:
            out[str(session_id)] = snapshot
    return out


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
    name_key = normalize_name_key(row.get("Название", ""))
    if name_key:
        return f"name:{name_key}"
    return ""


def build_supplier_snapshot(df, supplier_name, category_getter=None):
    category_getter = category_getter or (lambda row: str(row.get("Категория", "") or ""))
    items = {}
    for _, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip()
        if supplier_name and supplier and supplier != supplier_name:
            continue
        key = _snapshot_item_key(row)
        if not key:
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        items[key] = {
            "name": str(row.get("Название", "")).strip(),
            "price": _snapshot_price(row.get("Цена", "")),
            "onliner_id": oid,
            "category": str(category_getter(row)).strip(),
            "has_id": bool(oid),
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
        save_dict(Path(session_dir) / "supplier_diff.json", diff_data or {})
    except Exception:
        LOGGER.exception("supplier diff could not be saved")


def load_session_supplier_diff(session_dir):
    if not session_dir:
        return {}
    return load_dict(Path(session_dir) / "supplier_diff.json")
