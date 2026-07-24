"""Server-side filtering, sorting, and paging for the consolidated table."""

from __future__ import annotations

import math


NUMERIC_COLUMNS = {2, 6, 7, 8}


def build_consolidated_page(
    rows,
    *,
    draw=0,
    start=0,
    length=100,
    search="",
    order_specs=None,
    filter_mode="all",
    no_id_category="",
    export_indexes=None,
    snapshot_names=None,
    badge_counts_builder=None,
):
    source = [row for row in (rows or []) if isinstance(row, list)]
    duplicate_meta, no_id_category_counts, supplier_count = _build_meta(source)
    duplicate_ids = set(duplicate_meta)
    export_indexes = {str(value) for value in (export_indexes or set())}
    snapshot_names = {str(value or "").strip() for value in (snapshot_names or set()) if str(value or "").strip()}

    mode = str(filter_mode or "all").strip().lower()
    selected_category = str(no_id_category or "").strip().casefold()
    filtered = []
    for row in source:
        oid = _cell_text(row, 0)
        if mode == "no_id":
            if oid:
                continue
            category = _cell_text(row, 9) or "Без категории"
            if selected_category and category.casefold() != selected_category:
                continue
        elif mode == "duplicate":
            if not oid or oid not in duplicate_ids:
                continue
        elif mode == "export":
            if _cell_text(row, 8) not in export_indexes:
                continue
        elif mode == "snapshot":
            if _cell_text(row, 1) not in snapshot_names:
                continue
        filtered.append(row)

    query = str(search or "").strip().casefold()
    if query:
        filtered = [row for row in filtered if _row_matches_search(row, query)]

    specs = _clean_order_specs(order_specs)
    for column, descending in reversed(specs):
        filtered.sort(key=lambda row, col=column: _sort_key(row, col), reverse=descending)

    filtered_count = len(filtered)
    page_start = max(0, int(start or 0))
    page_length = min(500, max(10, int(length or 100)))
    page = filtered[page_start : page_start + page_length]
    badge_counts = badge_counts_builder(source) if callable(badge_counts_builder) else {}

    return {
        "draw": max(0, int(draw or 0)),
        "recordsTotal": len(source),
        "recordsFiltered": filtered_count,
        "data": page,
        "meta": {
            "duplicate_ids": duplicate_meta,
            "without_id_category_counts": no_id_category_counts,
            "without_id_count": sum(item["count"] for item in no_id_category_counts),
            "supplier_count": supplier_count,
            "badge_counts": badge_counts if isinstance(badge_counts, dict) else {},
        },
    }


def _build_meta(rows):
    id_stats = {}
    category_counts = {}
    suppliers = set()
    for row in rows:
        supplier = _cell_text(row, 3)
        if supplier:
            suppliers.add(supplier)
        oid = _cell_text(row, 0)
        if not oid:
            category = _cell_text(row, 9) or "Без категории"
            category_counts[category] = int(category_counts.get(category, 0)) + 1
            continue
        price = _number(row[2] if len(row) > 2 else None)
        stats = id_stats.setdefault(oid, [0, None, None])
        stats[0] += 1
        if price is not None:
            stats[1] = price if stats[1] is None else min(stats[1], price)
            stats[2] = price if stats[2] is None else max(stats[2], price)

    duplicates = {oid: values for oid, values in id_stats.items() if values[0] > 1}
    categories = [
        {"category": category, "count": count}
        for category, count in sorted(category_counts.items(), key=lambda item: item[0].casefold())
    ]
    return duplicates, categories, max(1, len(suppliers))


def _clean_order_specs(order_specs):
    cleaned = []
    for raw_column, raw_direction in order_specs or []:
        try:
            column = int(raw_column)
        except Exception:
            continue
        if column < 0 or column > 9:
            continue
        cleaned.append((column, str(raw_direction or "asc").lower() == "desc"))
    return cleaned or [(1, False)]


def _sort_key(row, column):
    value = row[column] if len(row) > column else ""
    if column in NUMERIC_COLUMNS:
        number = _number(value)
        return (number is None, number if number is not None else math.inf)
    return (_cell_text(row, column) == "", _cell_text(row, column).casefold())


def _row_matches_search(row, query):
    for column in range(min(10, len(row))):
        if query in _cell_text(row, column).casefold():
            return True
    return False


def _cell_text(row, column):
    if len(row) <= column or row[column] is None:
        return ""
    return str(row[column]).strip()


def _number(value):
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
    except Exception:
        return None
    return number if math.isfinite(number) else None
