"""Tests for the indexed working-session product store."""

from price_mixer.services.session_products import SessionProductStore


ROWS = [
    ["10", "Monitor Z", 120, "IVEN", "12", "2", 140, 150, 5, "Монитор"],
    ["10", "Monitor A", 100, "Tradex", "24", "1", 130, 145, 6, "Монитор"],
    ["", "Mouse One", 20, "N-Tech", "6", "2", 25, 30, 7, "Мышь"],
    ["", "Mouse Two", 15, "IVEN", "6", "3", 20, 25, 8, "Мышь"],
    ["30", "SSD Alpha", 80, "IVEN", "36", "1", 90, 95, 9, "SSD"],
]


def test_replace_rows_is_idempotent_and_parity_is_exact(tmp_path):
    store = SessionProductStore(tmp_path / "sessions.db", mode="canonical")
    session = tmp_path / "uploads" / "abc123"

    first = store.replace_rows(
        session,
        ROWS,
        source_revision="r1",
        badge_counts={"mouse": 2},
    )
    second = store.replace_rows(
        session,
        ROWS,
        source_revision="r1",
        badge_counts={"mouse": 2},
    )

    assert first["changed"] is True
    assert first["revision"] == 1
    assert second["changed"] is False
    assert second["revision"] == 1
    assert store.parity(session, ROWS)["matches"] is True


def test_same_source_revision_skips_rehash_and_replacement(tmp_path, monkeypatch):
    store = SessionProductStore(tmp_path / "sessions.db", mode="canonical")
    session = tmp_path / "abc123"
    store.replace_rows(session, ROWS, source_revision="r1")

    monkeypatch.setattr(
        "price_mixer.services.session_products.rows_digest",
        lambda _rows: (_ for _ in ()).throw(AssertionError("must not rehash")),
    )

    result = store.replace_rows(session, list(reversed(ROWS)), source_revision="r1")

    assert result["changed"] is False
    assert result["row_count"] == len(ROWS)


def test_query_page_filters_searches_sorts_and_returns_global_meta(tmp_path):
    store = SessionProductStore(tmp_path / "sessions.db", mode="canonical")
    session = tmp_path / "abc123"
    store.replace_rows(
        session,
        ROWS,
        source_revision="r1",
        badge_counts={"mouse": 2},
    )

    payload = store.query_page(
        session,
        draw=4,
        start=0,
        length=100,
        search="monitor",
        order_specs=[(2, "asc")],
    )

    assert payload["draw"] == 4
    assert payload["recordsTotal"] == 5
    assert payload["recordsFiltered"] == 2
    assert [row[2] for row in payload["data"]] == [100, 120]
    assert payload["meta"]["duplicate_ids"] == {"10": [2, 100.0, 120.0]}
    assert payload["meta"]["duplicate_id_count"] == 1
    assert payload["meta"]["duplicate_row_count"] == 2
    assert payload["meta"]["without_id_count"] == 2
    assert payload["meta"]["supplier_count"] == 3
    assert payload["meta"]["badge_counts"] == {"mouse": 2}
    assert payload["meta"]["storage"] == "sqlite"

    article = store.query_page(
        session,
        search="nitor a",
        order_specs=[(1, "asc")],
    )
    assert [row[1] for row in article["data"]] == ["Monitor A"]


def test_query_page_supports_no_id_category_and_duplicate_modes(tmp_path):
    store = SessionProductStore(tmp_path / "sessions.db", mode="canonical")
    session = tmp_path / "abc123"
    store.replace_rows(session, ROWS, source_revision="r1")

    no_id = store.query_page(
        session,
        filter_mode="no_id",
        no_id_category="МЫШЬ",
        order_specs=[(1, "asc")],
    )
    duplicates = store.query_page(
        session,
        filter_mode="duplicate",
        order_specs=[(2, "desc")],
    )

    assert [row[1] for row in no_id["data"]] == ["Mouse One", "Mouse Two"]
    assert [row[2] for row in duplicates["data"]] == [120, 100]


def test_noncanonical_mode_does_not_take_over_page_queries(tmp_path):
    store = SessionProductStore(tmp_path / "sessions.db", mode="dual")
    session = tmp_path / "abc123"
    store.replace_rows(session, ROWS, source_revision="r1")

    assert store.query_page(session) is None
