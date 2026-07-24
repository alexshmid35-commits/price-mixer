"""Server-side filtering, sorting, and paging for the consolidated table."""

from __future__ import annotations

from collections import OrderedDict
import math
import threading


NUMERIC_COLUMNS = {2, 6, 7, 8}


class ConsolidatedPagingCache:
    """Bounded cache for table metadata and repeated page queries."""

    def __init__(self, *, max_entries=4, max_queries_per_entry=12):
        self.max_entries = max(1, int(max_entries))
        self.max_queries_per_entry = max(1, int(max_queries_per_entry))
        self._entries = OrderedDict()
        self._lock = threading.RLock()

    def clear(self):
        with self._lock:
            self._entries.clear()

    def build_page(self, cache_key, rows, **kwargs):
        key = _hashable_cache_key(cache_key)
        badge_counts_builder = kwargs.pop("badge_counts_builder", None)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _build_entry(rows, badge_counts_builder)
                self._entries[key] = entry
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
            else:
                self._entries.move_to_end(key)
            return _build_page_from_entry(
                entry,
                max_queries=self.max_queries_per_entry,
                **kwargs,
            )


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
    entry = _build_entry(rows, badge_counts_builder)
    return _build_page_from_entry(
        entry,
        draw=draw,
        start=start,
        length=length,
        search=search,
        order_specs=order_specs,
        filter_mode=filter_mode,
        no_id_category=no_id_category,
        export_indexes=export_indexes,
        snapshot_names=snapshot_names,
        max_queries=0,
    )


def _build_entry(rows, badge_counts_builder):
    source = tuple(row for row in (rows or []) if isinstance(row, list))
    duplicate_meta, no_id_category_counts, supplier_count = _build_meta(source)
    return {
        "source": source,
        "duplicate_meta": duplicate_meta,
        "duplicate_ids": frozenset(duplicate_meta),
        "no_id_category_counts": no_id_category_counts,
        "supplier_count": supplier_count,
        "badge_counts": (
            badge_counts_builder(source)
            if callable(badge_counts_builder)
            else {}
        ),
        "search_text": tuple(_search_text(row) for row in source),
        "sort_keys": {},
        "queries": OrderedDict(),
    }


def _build_page_from_entry(
    entry,
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
    max_queries=0,
):
    source = entry["source"]
    duplicate_ids = entry["duplicate_ids"]
    export_indexes = {str(value) for value in (export_indexes or set())}
    snapshot_names = {str(value or "").strip() for value in (snapshot_names or set()) if str(value or "").strip()}
    mode = str(filter_mode or "all").strip().lower()
    selected_category = str(no_id_category or "").strip().casefold()
    query = str(search or "").strip().casefold()
    specs = _clean_order_specs(order_specs)
    query_key = (
        mode,
        selected_category,
        frozenset(export_indexes),
        frozenset(snapshot_names),
        query,
        tuple(specs),
    )
    queries = entry["queries"]
    filtered_indexes = queries.get(query_key)
    if filtered_indexes is None:
        filtered_indexes = _filter_and_sort_indexes(
            entry,
            mode=mode,
            selected_category=selected_category,
            export_indexes=export_indexes,
            snapshot_names=snapshot_names,
            query=query,
            specs=specs,
        )
        if max_queries > 0:
            queries[query_key] = filtered_indexes
            while len(queries) > max_queries:
                queries.popitem(last=False)
    elif max_queries > 0:
        queries.move_to_end(query_key)

    filtered_count = len(filtered_indexes)
    page_start = max(0, int(start or 0))
    page_length = min(500, max(10, int(length or 100)))
    page = [
        source[index]
        for index in filtered_indexes[page_start : page_start + page_length]
    ]
    page_ids = {
        _cell_text(row, 0)
        for row in page
        if _cell_text(row, 0)
    }
    page_duplicate_meta = {
        onliner_id: entry["duplicate_meta"][onliner_id]
        for onliner_id in page_ids
        if onliner_id in entry["duplicate_meta"]
    }

    return {
        "draw": max(0, int(draw or 0)),
        "recordsTotal": len(source),
        "recordsFiltered": filtered_count,
        "data": page,
        "meta": {
            "duplicate_ids": page_duplicate_meta,
            "duplicate_id_count": len(entry["duplicate_meta"]),
            "duplicate_row_count": sum(
                values[0]
                for values in entry["duplicate_meta"].values()
            ),
            "without_id_category_counts": entry["no_id_category_counts"],
            "without_id_count": sum(
                item["count"]
                for item in entry["no_id_category_counts"]
            ),
            "supplier_count": entry["supplier_count"],
            "badge_counts": (
                entry["badge_counts"]
                if isinstance(entry["badge_counts"], dict)
                else {}
            ),
        },
    }


def _filter_and_sort_indexes(
    entry,
    *,
    mode,
    selected_category,
    export_indexes,
    snapshot_names,
    query,
    specs,
):
    source = entry["source"]
    duplicate_ids = entry["duplicate_ids"]
    search_text = entry["search_text"]
    filtered = []
    for index, row in enumerate(source):
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
        if query and query not in search_text[index]:
            continue
        filtered.append(index)

    for column, descending in reversed(specs):
        keys = _entry_sort_keys(entry, column)
        filtered.sort(
            key=lambda index, values=keys: values[index],
            reverse=descending,
        )
    return tuple(filtered)


def _entry_sort_keys(entry, column):
    keys = entry["sort_keys"].get(column)
    if keys is None:
        keys = tuple(_sort_key(row, column) for row in entry["source"])
        entry["sort_keys"][column] = keys
    return keys


def _search_text(row):
    return "\x1f".join(
        _cell_text(row, column).casefold()
        for column in range(min(10, len(row)))
    )


def _hashable_cache_key(value):
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value


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
