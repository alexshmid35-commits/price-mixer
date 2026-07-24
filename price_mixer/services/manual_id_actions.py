"""Manual Onliner ID confirmation, clearing, and rollback actions."""

import time
from pathlib import Path
import re

from price_mixer.services.product_normalization import normalize_name_key, normalize_onliner_id


def confirm_manual_id_batch(
    session_dir,
    payload,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    load_id_cache,
    save_id_cache,
    sanitize_id_cache,
    load_manual_id_bindings,
    save_manual_id_bindings,
    load_review_queue,
    save_review_queue,
    append_id_change_journal,
    fetch_onliner_product_info=None,
    normalize_name_key_func=normalize_name_key,
    coerce_bool=None,
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400

    payload = payload if isinstance(payload, dict) else {}
    source = str(payload.get("source", "ui")).strip() or "ui"
    items_raw = payload.get("items", [])
    if not isinstance(items_raw, list) or not items_raw:
        return {"status": "error", "message": "Нет выбранных строк"}, 400

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return {"status": "error", "message": "В прайсе нет колонки OnlinerID"}, 400
    _ensure_id_columns(df)

    id_cache, id_cache_changed = sanitize_id_cache(load_id_cache())
    manual_bindings = load_manual_id_bindings()
    id_to_name_keys = _existing_id_name_keys(df, normalize_name_key_func)
    updated = 0
    blocked_duplicates = []
    blocked_stale = []
    touched_queue_items = []
    journal_entry = {
        "ts": int(time.time()),
        "action": "manual_id_confirm_batch",
        "session_dir": str(session_dir),
        "source": source,
        "changes": [],
    }
    coerce_bool = coerce_bool or _default_coerce_bool

    for raw in items_raw[:1000]:
        if not isinstance(raw, dict):
            continue
        item_name = str(raw.get("name", "")).strip()
        oid = normalize_onliner_id(raw.get("onliner_id", ""))
        final_url = str(raw.get("url", "")).strip()
        row_idx = raw.get("row_idx", None)
        allow_duplicate_id = coerce_bool(raw.get("allow_duplicate_id"), False)
        if not item_name or not oid:
            continue
        target_name_key = normalize_name_key_func(item_name)
        supplier_names = _supplier_scope_for_item(
            raw,
            df,
            row_idx,
            target_name_key=target_name_key,
            normalize_name_key_func=normalize_name_key_func,
        )
        if _df_has_supplier_scope(df) and not supplier_names:
            blocked_stale.append({
                "name": item_name,
                "row_idx": row_idx,
                "reason": "supplier_scope_missing",
            })
            continue
        target_rows = _matching_row_indices(
            df,
            item_name,
            row_idx,
            supplier_names,
            normalize_name_key_func,
        )
        if not target_rows:
            blocked_stale.append({
                "name": item_name,
                "row_idx": row_idx,
                "supplier": supplier_names[0] if len(supplier_names) == 1 else "",
                "reason": "row_changed_after_report",
            })
            continue

        duplicate_conflicts = _duplicate_id_conflicts(
            df,
            oid,
            target_name_key,
            item_name,
            normalize_name_key_func,
            supplier_names,
        )
        duplicate_conflicts.extend(_manual_binding_duplicate_conflicts(
            manual_bindings,
            oid,
            target_name_key,
            item_name,
            supplier_names,
        ))
        if duplicate_conflicts and not allow_duplicate_id:
            blocked_duplicates.append({
                "name": item_name,
                "onliner_id": oid,
                "known_items_with_same_id": int(len(duplicate_conflicts) + (1 if target_name_key else 0)),
                "conflicts": duplicate_conflicts[:5],
            })
            continue

        if not final_url and callable(fetch_onliner_product_info):
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

        manual_key = _manual_binding_storage_key(target_name_key, supplier_names)
        old_manual_binding = dict(manual_bindings.get(manual_key) or {}) if manual_key else {}
        if manual_key:
            manual_record = {"id": oid, "url": final_url}
            if supplier_names:
                manual_record["suppliers"] = supplier_names
            manual_bindings[manual_key] = manual_record
            touched_queue_items.append(({manual_key, target_name_key}, supplier_names))
            id_to_name_keys.setdefault(oid, set()).add(target_name_key)

        for df_idx in target_rows:
            df_name = str(df.at[df_idx, "Название"] if "Название" in df.columns else item_name).strip()
            old_id = normalize_onliner_id(df.at[df_idx, "OnlinerID"])
            old_url = str(df.at[df_idx, "Ссылка"]).strip() if "Ссылка" in df.columns else ""
            if old_id == oid and (not final_url or old_url == final_url):
                continue
            df.at[df_idx, "OnlinerID"] = oid
            if final_url:
                df.at[df_idx, "Ссылка"] = final_url
            journal_entry["changes"].append({
                "row_idx": int(df_idx) if isinstance(df_idx, int) or str(df_idx).isdigit() else str(df_idx),
                "name": df_name or item_name,
                "supplier": supplier_names[0] if len(supplier_names) == 1 else "",
                "binding_key": manual_key,
                "old_manual_binding": old_manual_binding,
                "old_onliner_id": old_id,
                "old_url": old_url,
                "new_onliner_id": oid,
                "new_url": final_url,
            })
            updated += 1

    for queue_keys, supplier_names in touched_queue_items:
        _remove_review_queue_keys(
            queue_keys,
            load_review_queue,
            save_review_queue,
            supplier_names=supplier_names,
        )
    if id_cache_changed:
        save_id_cache(id_cache)
    save_manual_id_bindings(manual_bindings)
    if journal_entry["changes"]:
        append_id_change_journal(journal_entry)
    _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json)

    if blocked_duplicates and updated <= 0:
        sample = blocked_duplicates[0]
        sample_conflicts = sample.get("conflicts", []) if isinstance(sample, dict) else []
        conflict = sample_conflicts[0] if sample_conflicts else {}
        conflict_name = str((conflict or {}).get("name", "") or "").strip()
        conflict_supplier = str((conflict or {}).get("supplier", "") or "").strip()
        conflict_row = (conflict or {}).get("row_idx", "")
        conflict_label = conflict_name or (f"строка {conflict_row}" if str(conflict_row).strip() else "другой товар")
        return {
            "status": "error",
            "code": "duplicate_id_assigned",
            "updated": 0,
            "blocked": blocked_duplicates[:20],
            "message": (
                f"Данный ID {sample.get('onliner_id', '')} уже присвоен"
                + (f" у поставщика {conflict_supplier}" if conflict_supplier else "")
                + f": {conflict_label}"
            ),
        }, 409
    if blocked_stale and updated <= 0:
        return {
            "status": "error",
            "code": "stale_price_row",
            "updated": 0,
            "blocked": blocked_stale[:20],
            "message": "Прайс уже изменился. Строка товара не совпала с отчётом; обнови список и повтори выбор.",
        }, 409
    if blocked_duplicates:
        return {
            "status": "ok",
            "updated": updated,
            "blocked": blocked_duplicates[:20],
            "message": (
                f"Сохранено: {updated}. Защита от дублей отклонила ещё {len(blocked_duplicates)} "
                "назначений с повторяющимися OnlinerID."
            ),
        }
    response = {"status": "ok", "updated": updated}
    if blocked_stale:
        response["stale"] = blocked_stale[:20]
    return response


def clear_manual_id(
    session_dir,
    payload,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    load_id_cache,
    save_id_cache,
    sanitize_id_cache,
    load_manual_id_bindings,
    save_manual_id_bindings,
    load_review_queue,
    save_review_queue,
    append_id_change_journal,
    normalize_name_key_func=normalize_name_key,
    get_id_cache_key_for_name=None,
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400

    payload = payload if isinstance(payload, dict) else {}
    source = str(payload.get("source", "ui")).strip() or "ui"
    item = payload.get("item", {})
    if not isinstance(item, dict):
        return {"status": "error", "message": "Некорректный payload"}, 400
    item_name = str(item.get("name", "")).strip()
    row_idx = item.get("row_idx", None)
    if not item_name or row_idx is None or str(row_idx).strip() == "":
        return {"status": "error", "message": "Нужно имя товара и row_idx"}, 400

    try:
        row_idx_int = int(row_idx)
    except Exception:
        return {"status": "error", "message": "Некорректный row_idx"}, 400

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return {"status": "error", "message": "В прайсе нет колонки OnlinerID"}, 400
    _ensure_id_columns(df)
    name_key = normalize_name_key_func(item_name)
    supplier_names = _supplier_scope_for_item(
        item,
        df,
        row_idx_int,
        target_name_key=name_key,
        normalize_name_key_func=normalize_name_key_func,
    )
    target_rows = _matching_row_indices(
        df,
        item_name,
        row_idx_int,
        supplier_names,
        normalize_name_key_func,
    )
    if not target_rows:
        return {
            "status": "error",
            "code": "stale_price_row",
            "message": "Прайс уже изменился: строка не совпадает с выбранным товаром.",
        }, 409
    row_idx_int = target_rows[0]
    old_id = normalize_onliner_id(df.at[row_idx_int, "OnlinerID"])
    old_url = str(df.at[row_idx_int, "Ссылка"]).strip()

    id_cache, _ = sanitize_id_cache(load_id_cache())
    cache_key = get_id_cache_key_for_name(item_name) if callable(get_id_cache_key_for_name) else ""
    if cache_key and cache_key in id_cache:
        id_cache.pop(cache_key, None)
    save_id_cache(id_cache)

    manual_bindings = load_manual_id_bindings()
    manual_key = _manual_binding_storage_key(name_key, supplier_names)
    old_manual_binding = dict(manual_bindings.get(manual_key) or {}) if manual_key else {}
    if name_key:
        manual_record = {"id": "", "url": "", "blocked": True}
        if supplier_names:
            manual_record["suppliers"] = supplier_names
        manual_bindings[manual_key] = manual_record
        save_manual_id_bindings(manual_bindings)
        _remove_review_queue_keys(
            {manual_key, name_key},
            load_review_queue,
            save_review_queue,
            supplier_names=supplier_names,
        )

    df.at[row_idx_int, "OnlinerID"] = ""
    df.at[row_idx_int, "Ссылка"] = ""

    append_id_change_journal({
        "ts": int(time.time()),
        "action": "manual_id_clear",
        "session_dir": str(session_dir),
        "source": source,
        "changes": [{
            "row_idx": int(row_idx_int),
            "name": item_name,
            "supplier": supplier_names[0] if len(supplier_names) == 1 else "",
            "binding_key": manual_key,
            "old_manual_binding": old_manual_binding,
            "old_onliner_id": old_id,
            "old_url": old_url,
            "new_onliner_id": "",
            "new_url": "",
        }],
    })

    _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json)
    return {"status": "ok", "cleared": 1}


def rollback_last_manual_id_change(
    session_dir,
    load_id_change_journal,
    save_id_change_journal,
    read_consolidated_df,
    write_consolidated_df,
    write_consolidated_json,
    load_manual_id_bindings=None,
    save_manual_id_bindings=None,
):
    if not session_dir:
        return {"status": "error", "message": "Нет активной сессии"}, 400

    rows = load_id_change_journal()
    if not rows:
        return {"status": "error", "message": "Журнал замен пуст"}, 400

    last_idx = -1
    for idx in range(len(rows) - 1, -1, -1):
        rec = rows[idx]
        if str(rec.get("session_dir", "")).strip() == str(session_dir):
            last_idx = idx
            break
    if last_idx < 0:
        return {"status": "error", "message": "Для текущей сессии нет записей отката"}, 400

    rec = rows.pop(last_idx)
    changes = rec.get("changes", []) if isinstance(rec, dict) else []
    if not isinstance(changes, list) or not changes:
        save_id_change_journal(rows)
        return {"status": "error", "message": "В записи нет изменений для отката"}, 400

    df = read_consolidated_df(session_dir)
    if "OnlinerID" not in df.columns:
        return {"status": "error", "message": "В прайсе нет OnlinerID"}, 400
    _ensure_id_columns(df)

    restored = 0
    binding_rollbacks = {}
    for change in changes:
        try:
            row_idx = int(change.get("row_idx"))
        except Exception:
            continue
        if row_idx not in df.index:
            continue
        old_id = normalize_onliner_id(change.get("old_onliner_id", ""))
        old_url = str(change.get("old_url", "")).strip()
        df.at[row_idx, "OnlinerID"] = old_id
        df.at[row_idx, "Ссылка"] = old_url
        binding_key = str(change.get("binding_key", "") or "").strip()
        if binding_key and binding_key not in binding_rollbacks:
            binding_rollbacks[binding_key] = change.get("old_manual_binding")
        restored += 1

    if binding_rollbacks and callable(load_manual_id_bindings) and callable(save_manual_id_bindings):
        manual_bindings = load_manual_id_bindings()
        for binding_key, old_record in binding_rollbacks.items():
            if isinstance(old_record, dict) and old_record:
                manual_bindings[binding_key] = dict(old_record)
            else:
                manual_bindings.pop(binding_key, None)
        save_manual_id_bindings(manual_bindings)

    _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json)
    save_id_change_journal(rows)
    return {"status": "ok", "restored": restored}


def _ensure_id_columns(df):
    if "Ссылка" not in df.columns:
        df["Ссылка"] = ""
    df["OnlinerID"] = df["OnlinerID"].astype("object")
    df["Ссылка"] = df["Ссылка"].astype("object")


def _normalize_supplier_scope(value):
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = []
    return [str(item or "").strip() for item in items if str(item or "").strip()]


def _supplier_scope_for_item(
    raw,
    df,
    row_idx,
    target_name_key="",
    normalize_name_key_func=normalize_name_key,
):
    if isinstance(raw, dict):
        suppliers = _normalize_supplier_scope(raw.get("suppliers", None))
        if not suppliers:
            suppliers = _normalize_supplier_scope(raw.get("supplier", ""))
        if suppliers:
            return list(dict.fromkeys(suppliers))
    try:
        if row_idx is not None and str(row_idx).strip() != "":
            row_idx_int = int(row_idx)
            if row_idx_int in df.index:
                if target_name_key and "Название" in df.columns:
                    current_key = normalize_name_key_func(df.at[row_idx_int, "Название"])
                    if current_key != target_name_key:
                        raise ValueError("stale row")
                supplier = str(df.at[row_idx_int, "Поставщик"] if "Поставщик" in df.columns else "").strip()
                if supplier:
                    return [supplier]
    except Exception:
        pass
    if target_name_key and "Название" in df.columns and "Поставщик" in df.columns:
        suppliers = []
        for _, row in df.iterrows():
            if normalize_name_key_func(row.get("Название", "")) != target_name_key:
                continue
            supplier = str(row.get("Поставщик", "") or "").strip()
            if supplier:
                suppliers.append(supplier)
        unique = list(dict.fromkeys(suppliers))
        if len(unique) == 1:
            return unique
    return []


def _df_has_supplier_scope(df):
    if df is None or "Поставщик" not in df.columns:
        return False
    return any(str(value or "").strip() for value in df["Поставщик"].tolist())


def _matching_row_indices(df, item_name, row_idx, supplier_names, normalize_name_key_func):
    target_name_key = normalize_name_key_func(item_name)
    if not target_name_key or "Название" not in df.columns:
        return []
    try:
        row_idx_int = int(row_idx)
        if row_idx_int in df.index:
            row = df.loc[row_idx_int]
            if (
                normalize_name_key_func(row.get("Название", "")) == target_name_key
                and _row_matches_supplier_scope(row, supplier_names)
            ):
                return [row_idx_int]
    except Exception:
        pass
    matches = []
    for df_idx, row in df.iterrows():
        if normalize_name_key_func(row.get("Название", "")) != target_name_key:
            continue
        if supplier_names and not _row_matches_supplier_scope(row, supplier_names):
            continue
        matches.append(df_idx)
    return matches


def _row_matches_supplier_scope(row, supplier_names):
    suppliers = {str(item or "").strip().upper() for item in (supplier_names or []) if str(item or "").strip()}
    if not suppliers:
        return True
    supplier = str(row.get("Поставщик", "") or "").strip().upper()
    return supplier in suppliers


def _duplicate_id_conflicts(df, oid, target_name_key, item_name, normalize_name_key_func, supplier_names=None):
    if df is None or df.empty or "OnlinerID" not in df.columns:
        return []
    conflicts = []
    oid = normalize_onliner_id(oid)
    if not oid:
        return conflicts
    for df_idx, df_row in df.iterrows():
        if supplier_names and not _row_matches_supplier_scope(df_row, supplier_names):
            continue
        if normalize_onliner_id(df_row.get("OnlinerID", "")) != oid:
            continue
        df_name = str(df_row.get("Название", "") or "").strip()
        df_key = normalize_name_key_func(df_name)
        if target_name_key and df_key == target_name_key:
            continue
        # One supplier can have several lines for the same physical model
        # (for example "DK-03" and "DK-03 LGA1700 Ready"). Keep protection for
        # different models, but allow the same strong article/model token.
        if _same_strong_model(item_name, df_name):
            continue
        conflicts.append({
            "row_idx": int(df_idx) if isinstance(df_idx, int) or str(df_idx).isdigit() else str(df_idx),
            "name": df_name,
            "supplier": str(df_row.get("Поставщик", "") or "").strip(),
        })
    return conflicts


def _manual_binding_duplicate_conflicts(
    manual_bindings,
    oid,
    target_name_key,
    item_name,
    supplier_names=None,
):
    if not isinstance(manual_bindings, dict):
        return []
    oid = normalize_onliner_id(oid)
    target_suppliers = {
        _supplier_key_token(item)
        for item in (supplier_names or [])
        if _supplier_key_token(item)
    }
    conflicts = []
    for raw_key, record in manual_bindings.items():
        if not isinstance(record, dict) or bool(record.get("blocked", False)):
            continue
        if normalize_onliner_id(record.get("id", "")) != oid:
            continue
        key_text = str(raw_key or "").strip()
        record_supplier_tokens = {
            _supplier_key_token(item)
            for item in _normalize_supplier_scope(record.get("suppliers", record.get("supplier", "")))
            if _supplier_key_token(item)
        }
        key_supplier = ""
        base_key = key_text
        if key_text.startswith("supplier:"):
            parts = key_text.split(":", 2)
            if len(parts) == 3:
                key_supplier, base_key = parts[1], parts[2]
                record_supplier_tokens.add(key_supplier)
        if target_suppliers and record_supplier_tokens and target_suppliers.isdisjoint(record_supplier_tokens):
            continue
        if base_key == target_name_key or _same_strong_model(item_name, base_key):
            continue
        conflicts.append({
            "row_idx": "",
            "name": base_key,
            "supplier": next(iter(record_supplier_tokens), ""),
            "source": "durable_binding",
        })
    return conflicts


def _same_strong_model(left, right):
    left_tokens = _strong_model_tokens(left)
    if not left_tokens:
        return False
    return bool(left_tokens & _strong_model_tokens(right))


def _strong_model_tokens(text):
    raw = str(text or "")
    tokens = set()
    for part in re.findall(r"\(([^)]{3,80})\)", raw):
        tokens.update(_model_tokens_from_part(part))
    tokens.update(_model_tokens_from_part(raw))
    return tokens


def _model_tokens_from_part(text):
    out = set()
    for token in re.findall(r"\b[A-Za-zА-Яа-я0-9]+(?:[-_/][A-Za-zА-Яа-я0-9]+)+\b", str(text or "")):
        compact = _compact_model_token(token)
        if _is_strong_model_token(compact):
            out.add(compact)
    return out


def _compact_model_token(token):
    return re.sub(r"[^0-9a-zа-яё]+", "", str(token or "").lower())


def _is_strong_model_token(token):
    token = str(token or "")
    if len(token) < 4:
        return False
    return bool(re.search(r"[a-zа-яё]", token) and re.search(r"\d", token))


def _supplier_key_token(supplier_name):
    token = str(supplier_name or "").strip().lower()
    for old, new in ((" ", "_"), ("-", "_")):
        token = token.replace(old, new)
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_")


def _manual_binding_storage_key(name_key, supplier_names):
    base_key = str(name_key or "").strip()
    suppliers = [str(item or "").strip() for item in (supplier_names or []) if str(item or "").strip()]
    if base_key and len(suppliers) == 1:
        supplier_token = _supplier_key_token(suppliers[0])
        if supplier_token:
            return f"supplier:{supplier_token}:{base_key}"
    return base_key


def _existing_id_name_keys(df, normalize_name_key_func, supplier_names=None):
    id_to_name_keys = {}
    if "Название" not in df.columns:
        return id_to_name_keys
    for _, row in df.iterrows():
        if supplier_names and not _row_matches_supplier_scope(row, supplier_names):
            continue
        existing_oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not existing_oid:
            continue
        existing_name_key = normalize_name_key_func(row.get("Название", ""))
        if not existing_name_key:
            continue
        id_to_name_keys.setdefault(existing_oid, set()).add(existing_name_key)
    return id_to_name_keys


def _remove_review_queue_keys(keys, load_review_queue, save_review_queue, supplier_names=None):
    review_queue = load_review_queue()
    changed = False
    lookup = {str(key or "").strip() for key in (keys or []) if str(key or "").strip()}
    supplier_lookup = {
        _supplier_key_token(item)
        for item in (supplier_names or [])
        if _supplier_key_token(item)
    }
    for key in list(keys):
        if key in review_queue:
            entry = review_queue.get(key)
            if not supplier_lookup or _queue_entry_matches_supplier(key, entry, supplier_lookup):
                review_queue.pop(key, None)
                changed = True
    for queue_key, entry in list((review_queue or {}).items()):
        if not isinstance(entry, dict):
            continue
        match_key = str(entry.get("match_name_key", "") or entry.get("base_name_key", "") or "").strip()
        if (
            match_key
            and match_key in lookup
            and (not supplier_lookup or _queue_entry_matches_supplier(queue_key, entry, supplier_lookup))
        ):
            review_queue.pop(queue_key, None)
            changed = True
    if changed:
        save_review_queue(review_queue)


def _queue_entry_matches_supplier(queue_key, entry, supplier_lookup):
    if not supplier_lookup:
        return True
    key_text = str(queue_key or "").strip()
    if key_text.startswith("supplier:"):
        parts = key_text.split(":", 2)
        return len(parts) == 3 and parts[1] in supplier_lookup
    if not isinstance(entry, dict):
        return False
    raw = entry.get("suppliers", entry.get("supplier", ""))
    entry_suppliers = _normalize_supplier_scope(raw)
    return bool({_supplier_key_token(item) for item in entry_suppliers} & supplier_lookup)


def _write_consolidated(session_dir, df, write_consolidated_df, write_consolidated_json):
    write_consolidated_df(session_dir, df)
    write_consolidated_json(df, Path(session_dir) / "consolidated.json")


def _default_coerce_bool(value, default=False):
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
