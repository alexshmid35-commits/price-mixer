"""Bulk Onliner ID cleanup operations for consolidated prices."""

import time
from pathlib import Path

import numpy as np

from price_mixer.services.consolidated_io import has_consolidated_data
from price_mixer.services.product_normalization import (
    build_item_category_key as default_build_item_category_key,
    normalize_name_key as default_normalize_name_key,
    normalize_onliner_id,
)


NTECH_SUPPLIERS = {"N-TECH", "NTECH"}


def clear_invalid_onliner_ids(
    session_dir,
    payload,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    load_id_cache,
    save_id_cache,
    load_manual_id_bindings,
    save_manual_id_bindings,
    build_item_category_key=default_build_item_category_key,
    normalize_name_key=default_normalize_name_key,
    get_id_cache_key_for_name=None,
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400
    payload = payload if isinstance(payload, dict) else {}
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        return {"status": "ok", "cleared": 0}

    keys_to_clear, ids_to_clear = _clear_targets(items)
    if not keys_to_clear and not ids_to_clear:
        return {"status": "ok", "cleared": 0}

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return {"status": "ok", "cleared": 0}
    _ensure_id_columns(df, empty_value="")

    cleared = 0
    touched_name_keys = []
    touched_articles = []
    for index, row in df.iterrows():
        row_key = build_item_category_key(row)
        row_oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not ((row_key and row_key in keys_to_clear) or (row_oid and row_oid in ids_to_clear)):
            continue
        if row_oid:
            name = str(row.get("Название", "")).strip()
            touched_name_keys.append(normalize_name_key(name))
            if callable(get_id_cache_key_for_name):
                touched_articles.append(get_id_cache_key_for_name(name))
        df.at[index, "OnlinerID"] = ""
        df.at[index, "Ссылка"] = ""
        cleared += 1

    if cleared > 0:
        _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json)
        _clear_id_cache_entries(touched_articles, ids_to_clear, load_id_cache, save_id_cache)
        _clear_manual_bindings_for_ids(touched_name_keys, ids_to_clear, load_manual_id_bindings, save_manual_id_bindings)

    return {"status": "ok", "cleared": int(cleared)}


def clear_all_nonpc_onliner_ids(
    session_dir,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    append_id_change_journal,
    load_review_queue,
    save_review_queue,
    load_manual_id_bindings,
    save_manual_id_bindings,
    load_id_cache,
    save_id_cache,
    is_tgpc_pc_name,
    normalize_name_key=default_normalize_name_key,
    get_id_cache_key_for_name=None,
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400
    if not _consolidated_exists(session_dir):
        return {"status": "error", "message": "Нет данных для обработки"}, 400

    try:
        df = read_consolidated_df(session_dir)
        if "OnlinerID" not in df.columns:
            return {"status": "ok", "cleared": 0, "kept_pc": 0, "message": "В прайсе нет OnlinerID."}
        _ensure_id_columns(df, empty_value=np.nan)

        cleared = 0
        kept_pc = 0
        skipped_other_suppliers = 0
        journal_changes = []
        affected_name_keys = set()
        affected_articles = set()

        for index, row in df.iterrows():
            oid = normalize_onliner_id(row.get("OnlinerID", ""))
            if not oid:
                continue
            supplier = str(row.get("Поставщик", "")).strip().upper()
            if supplier not in NTECH_SUPPLIERS:
                skipped_other_suppliers += 1
                continue
            name = str(row.get("Название", "")).strip()
            if is_tgpc_pc_name(name):
                kept_pc += 1
                continue
            old_url = str(row.get("Ссылка", "")).strip()
            df.at[index, "OnlinerID"] = np.nan
            df.at[index, "Ссылка"] = ""
            cleared += 1
            _collect_affected(name, affected_name_keys, affected_articles, normalize_name_key, get_id_cache_key_for_name)
            journal_changes.append(_journal_change(index, name, oid, old_url, "bulk_clear_nonpc_before_rematch"))

        _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json)
        if journal_changes:
            append_id_change_journal({
                "ts": int(time.time()),
                "action": "clear_all_nonpc_onliner_ids",
                "session_dir": str(session_dir),
                "source": "api_clear_all_nonpc_onliner_ids",
                "changes": journal_changes,
            })

        _clear_review_queue_entries(affected_name_keys, load_review_queue, save_review_queue)
        cleared_manual_bindings = _clear_mapping_keys(affected_name_keys, load_manual_id_bindings, save_manual_id_bindings)
        cleared_id_cache = _clear_mapping_keys(affected_articles, load_id_cache, save_id_cache)

        return {
            "status": "ok",
            "cleared": int(cleared),
            "kept_pc": int(kept_pc),
            "skipped_other_suppliers": int(skipped_other_suppliers),
            "cleared_manual_bindings": int(cleared_manual_bindings),
            "cleared_id_cache": int(cleared_id_cache),
            "message": f"N-Tech: очищено ID {cleared}. ПЭВМ сохранено: {kept_pc}. Кэш N-Tech тоже очищен. Остальные поставщики не тронуты.",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:220]}, 500


def clear_ntech_duplicate_onliner_ids(
    session_dir,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    append_id_change_journal,
    load_review_queue,
    save_review_queue,
    load_manual_id_bindings,
    save_manual_id_bindings,
    load_id_cache,
    save_id_cache,
    normalize_name_key=default_normalize_name_key,
    get_id_cache_key_for_name=None,
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400
    if not _consolidated_exists(session_dir):
        return {"status": "error", "message": "Нет данных для обработки"}, 400

    try:
        df = read_consolidated_df(session_dir)
        if "OnlinerID" not in df.columns:
            return {"status": "ok", "cleared": 0, "duplicate_ids": 0, "message": "В прайсе нет OnlinerID."}
        _ensure_id_columns(df, empty_value=np.nan)

        ntech_rows, id_counts = _ntech_rows_with_ids(df)
        duplicate_ids = {oid for oid, count in id_counts.items() if count > 1}
        if not duplicate_ids:
            return {
                "status": "ok",
                "cleared": 0,
                "duplicate_ids": 0,
                "message": "У N-Tech не найдено дублирующихся OnlinerID.",
            }

        cleared = 0
        journal_changes = []
        affected_name_keys = set()
        affected_articles = set()
        for index, row, oid in ntech_rows:
            if oid not in duplicate_ids:
                continue
            name = str(row.get("Название", "")).strip()
            old_url = str(row.get("Ссылка", "")).strip()
            df.at[index, "OnlinerID"] = np.nan
            df.at[index, "Ссылка"] = ""
            cleared += 1
            _collect_affected(name, affected_name_keys, affected_articles, normalize_name_key, get_id_cache_key_for_name)
            journal_changes.append(_journal_change(index, name, oid, old_url, "bulk_clear_ntech_duplicate_ids"))

        _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json)
        append_id_change_journal({
            "ts": int(time.time()),
            "action": "clear_ntech_duplicate_onliner_ids",
            "session_dir": str(session_dir),
            "source": "api_clear_ntech_duplicate_onliner_ids",
            "changes": journal_changes,
        })

        _clear_review_queue_entries(affected_name_keys, load_review_queue, save_review_queue)
        cleared_manual_bindings = _clear_mapping_keys(affected_name_keys, load_manual_id_bindings, save_manual_id_bindings)
        cleared_id_cache = _clear_mapping_keys(affected_articles, load_id_cache, save_id_cache)

        return {
            "status": "ok",
            "cleared": int(cleared),
            "duplicate_ids": int(len(duplicate_ids)),
            "cleared_manual_bindings": int(cleared_manual_bindings),
            "cleared_id_cache": int(cleared_id_cache),
            "message": f"N-Tech: очищено строк-дублей {cleared} (уникальных ID: {len(duplicate_ids)}).",
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:220]}, 500


def _clear_targets(items):
    keys_to_clear = set()
    ids_to_clear = set()
    for item in items[:2000]:
        key = str((item or {}).get("key", "")).strip()
        oid = normalize_onliner_id((item or {}).get("onliner_id", ""))
        if key:
            keys_to_clear.add(key)
        if oid:
            ids_to_clear.add(oid)
    return keys_to_clear, ids_to_clear


def _consolidated_exists(session_dir):
    return has_consolidated_data(session_dir)


def _ensure_id_columns(df, empty_value):
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    df["Ссылка"] = df["Ссылка"].astype("object")


def _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json):
    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, Path(session_dir) / "consolidated.json")


def _clear_id_cache_entries(article_keys, ids_to_clear, load_id_cache, save_id_cache):
    id_cache = load_id_cache()
    changed = False
    for article_key in article_keys:
        key = str(article_key or "").strip()
        if not key:
            continue
        record = id_cache.get(key)
        if isinstance(record, dict):
            rid = normalize_onliner_id(record.get("id", ""))
            if rid and rid in ids_to_clear:
                id_cache.pop(key, None)
                changed = True
    if changed:
        save_id_cache(id_cache)


def _clear_manual_bindings_for_ids(name_keys, ids_to_clear, load_manual_id_bindings, save_manual_id_bindings):
    bindings = load_manual_id_bindings()
    changed = False
    for name_key in name_keys:
        key = str(name_key or "").strip()
        if not key:
            continue
        record = bindings.get(key)
        if isinstance(record, dict):
            rid = normalize_onliner_id(record.get("id", ""))
            if rid and rid in ids_to_clear:
                bindings.pop(key, None)
                changed = True
    if changed:
        save_manual_id_bindings(bindings)


def _collect_affected(name, affected_name_keys, affected_articles, normalize_name_key, get_id_cache_key_for_name):
    name_key = normalize_name_key(name)
    if name_key:
        affected_name_keys.add(name_key)
    if callable(get_id_cache_key_for_name):
        article_key = str(get_id_cache_key_for_name(name) or "").strip()
        if article_key:
            affected_articles.add(article_key)


def _journal_change(index, name, oid, old_url, reason):
    return {
        "row_idx": int(index),
        "name": name,
        "old_onliner_id": oid,
        "old_url": old_url,
        "new_onliner_id": "",
        "new_url": "",
        "reason": reason,
    }


def _clear_review_queue_entries(name_keys, load_review_queue, save_review_queue):
    queue = load_review_queue()
    changed = False
    for name_key in list(name_keys):
        if name_key in queue:
            queue.pop(name_key, None)
            changed = True
    if changed:
        save_review_queue(queue)


def _clear_mapping_keys(keys, load_mapping, save_mapping):
    mapping = load_mapping()
    changed = False
    cleared = 0
    for key in list(keys):
        if key in mapping:
            mapping.pop(key, None)
            changed = True
            cleared += 1
    if changed:
        save_mapping(mapping)
    return cleared


def _ntech_rows_with_ids(df):
    ntech_rows = []
    id_counts = {}
    for index, row in df.iterrows():
        supplier = str(row.get("Поставщик", "")).strip().upper()
        if supplier not in NTECH_SUPPLIERS:
            continue
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        ntech_rows.append((index, row, oid))
        id_counts[oid] = int(id_counts.get(oid, 0)) + 1
    return ntech_rows, id_counts
