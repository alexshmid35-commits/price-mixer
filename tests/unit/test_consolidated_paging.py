"""Tests for server-side consolidated table paging."""

from price_mixer.services import consolidated_paging as svc


ROWS = [
    ["10", "SSD B", 120, "IVEN", "12", "2", 140, 150, 5, "SSD"],
    ["10", "SSD A", 100, "Tradex", "24", "1", 120, 130, 3, "SSD"],
    ["", "Mouse", 20, "N-Tech", "6", "2", 30, 35, 8, "Мышь"],
    ["", "Cable", 5, "N-Tech", "", "2", 10, 12, 9, "Кабели"],
    ["20", "Monitor", 500, "IVEN", "36", "1", 550, 600, 2, "Монитор"],
]


def test_build_consolidated_page_paginates_and_returns_global_meta():
    payload = svc.build_consolidated_page(
        ROWS,
        draw=4,
        start=1,
        length=10,
        order_specs=[(1, "asc")],
        badge_counts_builder=lambda rows: {"mouse": 1},
    )

    assert payload["draw"] == 4
    assert payload["recordsTotal"] == 5
    assert payload["recordsFiltered"] == 5
    assert payload["data"][0][1] == "Monitor"
    assert payload["meta"]["duplicate_ids"] == {"10": [2, 100.0, 120.0]}
    assert payload["meta"]["without_id_count"] == 2
    assert payload["meta"]["supplier_count"] == 3
    assert payload["meta"]["badge_counts"] == {"mouse": 1}


def test_build_consolidated_page_filters_no_id_category_and_search():
    payload = svc.build_consolidated_page(
        ROWS,
        filter_mode="no_id",
        no_id_category="Мышь",
        search="mouse",
    )

    assert payload["recordsTotal"] == 5
    assert payload["recordsFiltered"] == 1
    assert payload["data"][0][1] == "Mouse"


def test_build_consolidated_page_filters_duplicates_export_and_snapshot():
    duplicate = svc.build_consolidated_page(ROWS, filter_mode="duplicate")
    exported = svc.build_consolidated_page(ROWS, filter_mode="export", export_indexes={2, 8})
    snapshot = svc.build_consolidated_page(ROWS, filter_mode="snapshot", snapshot_names={"Cable"})

    assert [row[0] for row in duplicate["data"]] == ["10", "10"]
    assert {row[8] for row in exported["data"]} == {2, 8}
    assert [row[1] for row in snapshot["data"]] == ["Cable"]


def test_build_consolidated_page_uses_numeric_multi_column_sort():
    payload = svc.build_consolidated_page(
        ROWS,
        filter_mode="duplicate",
        order_specs=[(0, "asc"), (2, "asc")],
    )

    assert [row[2] for row in payload["data"]] == [100, 120]


def test_paging_cache_reuses_meta_and_sorted_query_between_pages():
    calls = []
    cache = svc.ConsolidatedPagingCache(
        max_entries=2,
        max_queries_per_entry=3,
    )

    first = cache.build_page(
        ("session", 1),
        ROWS,
        start=0,
        length=10,
        order_specs=[(1, "asc")],
        badge_counts_builder=lambda rows: calls.append(len(rows)) or {"all": len(rows)},
    )
    second = cache.build_page(
        ("session", 1),
        list(ROWS),
        start=2,
        length=10,
        order_specs=[(1, "asc")],
        badge_counts_builder=lambda rows: calls.append(len(rows)) or {"all": len(rows)},
    )

    assert calls == [5]
    assert first["meta"] == second["meta"]
    assert first["data"][0][1] == "Cable"
    assert second["data"][0][1] == "Mouse"


def test_paging_cache_clear_rebuilds_entry():
    calls = []
    cache = svc.ConsolidatedPagingCache()
    kwargs = {
        "badge_counts_builder": lambda rows: calls.append(True) or {},
    }

    cache.build_page("session", ROWS, **kwargs)
    cache.clear()
    cache.build_page("session", ROWS, **kwargs)

    assert calls == [True, True]
