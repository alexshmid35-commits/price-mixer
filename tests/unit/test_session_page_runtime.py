"""Contract tests for SQL-first session paging and its fallback."""

from price_mixer.services.consolidated_paging import ConsolidatedPagingCache
from price_mixer.services.session_page_runtime import SessionPageRuntime
from price_mixer.services.session_products import SessionProductStore


ROWS = [
    ["1", "Monitor A", 100, "IVEN", "12", "2", 120, 130, 4, "Монитор"],
    ["", "Mouse B", 20, "Tradex", "6", "2", 25, 30, 5, "Мышь"],
]


def test_runtime_uses_sql_after_verified_sync(tmp_path):
    runtime = SessionPageRuntime(
        store=SessionProductStore(tmp_path / "sessions.db", mode="canonical"),
        compatibility_cache=ConsolidatedPagingCache(),
    )

    payload = runtime.build_page(
        tmp_path / "abc",
        ROWS,
        source_revision=("r1",),
        page_arguments={"filter_mode": "all", "search": "", "order_specs": []},
        badge_counts_builder=lambda _rows: {"ready": 1},
    )

    assert payload["recordsTotal"] == 2
    assert payload["meta"]["storage"] == "sqlite"
    assert payload["meta"]["revision"] == 1


def test_runtime_falls_back_when_sql_sync_fails(tmp_path, monkeypatch):
    store = SessionProductStore(tmp_path / "sessions.db", mode="canonical")
    runtime = SessionPageRuntime(
        store=store,
        compatibility_cache=ConsolidatedPagingCache(),
    )
    monkeypatch.setattr(
        store,
        "reconcile_rows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broken")),
    )

    payload = runtime.build_page(
        tmp_path / "abc",
        ROWS,
        source_revision=("r1",),
        page_arguments={"filter_mode": "all", "search": "", "order_specs": []},
        badge_counts_builder=lambda _rows: {},
    )

    assert payload["recordsTotal"] == 2
    assert payload["meta"]["storage"] == "compatibility"


def test_runtime_stores_full_rows_but_pages_only_visible_rows(tmp_path):
    store = SessionProductStore(tmp_path / "sessions.db", mode="canonical")
    runtime = SessionPageRuntime(
        store=store,
        compatibility_cache=ConsolidatedPagingCache(),
    )

    payload = runtime.build_page(
        tmp_path / "abc",
        ROWS[:1],
        canonical_rows=ROWS,
        canonical_source_revision=("all", "r1"),
        source_revision=("visible", "r1"),
        page_arguments={
            "filter_mode": "all",
            "search": "",
            "order_specs": [],
            "hidden_categories": {"Мышь"},
        },
        badge_counts_builder=lambda _rows: {},
    )

    assert payload["recordsTotal"] == 1
    assert [row[1] for row in payload["data"]] == ["Monitor A"]
    assert len(store.read_rows(tmp_path / "abc")) == 2
