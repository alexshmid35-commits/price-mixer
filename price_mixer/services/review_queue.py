"""Pure helpers for supplier-scoped manual review queue operations."""

from __future__ import annotations

import re


def unique_supplier_names(entry):
    supplier_names = []
    if isinstance(entry, dict):
        for key in ("supplier", "supplier_name"):
            value = str(entry.get(key, "") or "").strip()
            if value:
                supplier_names.append(value)
        for key in ("suppliers", "supplier_names"):
            value = entry.get(key)
            if isinstance(value, str):
                supplier_names.extend(
                    part.strip()
                    for part in re.split(r"[,;\n]+", value)
                    if part.strip()
                )
            elif isinstance(value, (list, tuple, set)):
                supplier_names.extend(
                    str(part or "").strip()
                    for part in value
                    if str(part or "").strip()
                )
    if supplier_names:
        return list(dict.fromkeys(supplier_names))

    reason = str((entry or {}).get("reason", "") or "").strip()
    return {
        "iven_laptop_manual": ["IVEN"],
        "iven_zakaz_laptop_manual": ["IVEN_zakaz"],
        "tradex_laptop_manual": ["Tradex"],
    }.get(reason, [])


def canonical_supplier_name(supplier):
    text = str(supplier or "").strip()
    compact = text.lower().replace("-", "").replace("_", "").replace(" ", "")
    return {
        "ntech": "N-Tech",
        "iven": "IVEN",
        "ivenzakaz": "IVEN_zakaz",
        "tradex": "Tradex",
        "tgpc": "TGPC",
    }.get(compact, text)


def supplier_scoped_key(name_key, supplier):
    key = str(name_key or "").strip()
    supplier_name = canonical_supplier_name(supplier)
    supplier_token = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(supplier_name or "").strip().lower(),
    ).strip("_")
    if supplier_token and key:
        return f"supplier:{supplier_token}:{key}"
    return key


def match_name_key(queue_key, entry):
    if isinstance(entry, dict):
        for key in ("match_name_key", "base_name_key"):
            value = str(entry.get(key, "") or "").strip()
            if value:
                return value
    return str(queue_key or "").strip()


def migrate_supplier_scope(queue):
    """Move legacy queue entries under supplier keys without changing decisions."""
    if not isinstance(queue, dict):
        return {}, False
    migrated = dict(queue)
    changed = False
    for queue_key, raw_entry in list(queue.items()):
        if str(queue_key or "").startswith("supplier:") or not isinstance(
            raw_entry, dict
        ):
            continue
        supplier_names = unique_supplier_names(raw_entry)
        if len(supplier_names) != 1:
            continue
        base_key = match_name_key(queue_key, raw_entry)
        scoped_key = supplier_scoped_key(base_key, supplier_names[0])
        if not scoped_key or scoped_key == queue_key:
            continue
        entry = dict(raw_entry)
        entry.setdefault("match_name_key", base_key)
        entry.setdefault("supplier", supplier_names[0])
        migrated.setdefault(scoped_key, entry)
        migrated.pop(queue_key, None)
        changed = True
    return migrated, changed


def supplier_name_lookup(supplier_names):
    return {
        str(supplier or "").strip().upper()
        for supplier in (supplier_names or [])
        if str(supplier or "").strip()
    }


def row_matches_supplier_names(row, supplier_names):
    suppliers = supplier_name_lookup(supplier_names)
    if not suppliers:
        return True
    supplier = str(row.get("Поставщик", "") or "").strip().upper()
    return supplier in suppliers


def build_list_items(queue, frame, *, normalize_name_key, normalize_onliner_id):
    """Attach current row indexes and identify queue entries already resolved."""
    name_to_row = {}
    name_to_has_id = {}
    supplier_name_to_row = {}
    supplier_name_to_has_id = {}
    if frame is not None:
        for row_idx, row in frame.iterrows():
            normalized_name = normalize_name_key(str(row.get("Название", "")))
            if not normalized_name:
                continue
            name_to_row[normalized_name] = int(row_idx)
            name_to_has_id[normalized_name] = bool(
                normalize_onliner_id(row.get("OnlinerID", ""))
            )
            supplier = str(row.get("Поставщик", "") or "").strip().upper()
            if supplier:
                key = (normalized_name, supplier)
                supplier_name_to_row[key] = int(row_idx)
                supplier_name_to_has_id[key] = bool(
                    normalize_onliner_id(row.get("OnlinerID", ""))
                )

    result = []
    stale_keys = set()
    for queue_key, entry in queue.items():
        base_key = match_name_key(queue_key, entry)
        supplier_names = unique_supplier_names(entry)
        supplier_lookup = supplier_name_lookup(supplier_names)
        if supplier_lookup:
            has_id = any(
                supplier_name_to_has_id.get((base_key, supplier))
                for supplier in supplier_lookup
            )
            row_idx = next(
                (
                    supplier_name_to_row.get((base_key, supplier))
                    for supplier in supplier_lookup
                    if supplier_name_to_row.get((base_key, supplier)) is not None
                ),
                None,
            )
        else:
            has_id = name_to_has_id.get(base_key)
            row_idx = name_to_row.get(base_key)
        if has_id:
            stale_keys.add(queue_key)
            continue
        item = dict(entry)
        item["name_key"] = queue_key
        item["match_name_key"] = base_key
        item["row_idx"] = row_idx
        result.append(item)

    result.sort(key=lambda item: item.get("added_at", 0), reverse=True)
    return result, stale_keys


def manual_binding_id_conflict(
    manual_bindings,
    name_key,
    onliner_id,
    supplier_names=None,
    *,
    normalize_onliner_id,
    manual_binding_scoped_key,
):
    oid = normalize_onliner_id(onliner_id)
    if not oid or not isinstance(manual_bindings, dict):
        return None
    current_key = str(name_key or "").strip()
    current_keys = {current_key}
    target_suppliers = supplier_name_lookup(supplier_names)
    supplier_names_list = [
        str(item or "").strip()
        for item in (supplier_names or [])
        if str(item or "").strip()
    ]
    if len(supplier_names_list) == 1:
        scoped_key = manual_binding_scoped_key(
            current_key, supplier_names_list[0]
        )
        if scoped_key:
            current_keys.add(scoped_key)
    for other_key, record in manual_bindings.items():
        other_key = str(other_key or "").strip()
        if (
            not other_key
            or other_key in current_keys
            or not isinstance(record, dict)
        ):
            continue
        record_suppliers = supplier_name_lookup(unique_supplier_names(record))
        if (
            target_suppliers
            and record_suppliers
            and target_suppliers.isdisjoint(record_suppliers)
        ):
            continue
        if normalize_onliner_id(record.get("id", "")) == oid:
            return other_key
    return None


def dataframe_id_conflict_for_supplier(
    frame,
    name_key,
    onliner_id,
    supplier_names,
    *,
    normalize_name_key,
    normalize_onliner_id,
):
    oid = normalize_onliner_id(onliner_id)
    if frame is None or frame.empty or not oid:
        return None
    current_key = str(name_key or "").strip()
    for row_idx, row in frame.iterrows():
        if not row_matches_supplier_names(row, supplier_names):
            continue
        if normalize_onliner_id(row.get("OnlinerID", "")) != oid:
            continue
        other_key = normalize_name_key(str(row.get("Название", "") or ""))
        if other_key and other_key != current_key:
            return {
                "row_idx": int(row_idx),
                "name": str(row.get("Название", "") or "").strip(),
                "supplier": str(row.get("Поставщик", "") or "").strip(),
            }
    return None
