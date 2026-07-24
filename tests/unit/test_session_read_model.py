import time
from concurrent.futures import ThreadPoolExecutor

from price_mixer.services.session_products import SessionProductStore
from price_mixer.services.session_read_model import (
    SessionReadModel,
    build_dashboard_payload,
    result_context,
    stats_context,
)


def _normalize_id(value):
    return str(value or "").strip()


def _normalize_category(value):
    return str(value or "").strip()


def _category_sort_key(value):
    return str(value or "").casefold()


def test_read_model_caches_by_revision_and_can_invalidate_one_session():
    model = SessionReadModel()
    calls = []

    def builder():
        calls.append(True)
        return {"total": len(calls)}

    assert model.get_or_build("a", ("r", 1), builder) == {"total": 1}
    assert model.get_or_build("a", ("r", 1), builder) == {"total": 1}
    assert len(calls) == 1

    model.invalidate("a")
    assert model.get_or_build("a", ("r", 1), builder) == {"total": 2}
    assert model.get_or_build("a", ("r", 2), builder) == {"total": 3}


def test_read_model_reuses_sql_projection_after_process_cache_is_lost(tmp_path):
    store = SessionProductStore(tmp_path / "sessions.db", mode="canonical")
    session = tmp_path / "abc"
    store.replace_rows(
        session,
        [["1", "A", 10, "IVEN", "12", "2", 12, 13, 0, "Монитор"]],
        source_revision="r1",
    )
    revision = ("sql", 1)
    first = SessionReadModel(store=store)

    assert first.get_or_build(session, revision, lambda: {"total": 1}) == {
        "total": 1,
    }
    second = SessionReadModel(store=store)
    assert second.get_or_build(
        session,
        revision,
        lambda: (_ for _ in ()).throw(AssertionError("must use SQLite")),
    ) == {"total": 1}


def test_read_model_coalesces_concurrent_builds():
    model = SessionReadModel()
    calls = []

    def builder():
        calls.append(True)
        time.sleep(0.05)
        return {"total": 9}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _item: model.get_or_build("session", ("r", 1), builder),
                range(8),
            )
        )

    assert results == [{"total": 9}] * 8
    assert len(calls) == 1


def test_dashboard_projection_builds_all_counters_in_one_payload():
    full_rows = [
        ["10", "Monitor A", 100, "IVEN", "12", "2", 125, 130, 0, "Монитор"],
        ["10", "Monitor A cheaper", 90, "Tradex", "12", "2", 120, 125, 1, "Монитор"],
        ["", "Mouse B", 20, "IVEN", "6", "2", 20.5, 25, 2, "Мышь"],
        ["", "Mouse hidden", 10, "Tradex", "6", "2", 20, 25, 3, "Скрытая"],
    ]
    visible_rows = full_rows[:3]
    export_rows = [
        {"key": 1, "category": "Монитор"},
        {"key": 2, "category": "Мышь"},
    ]

    payload = build_dashboard_payload(
        full_rows=full_rows,
        visible_rows=visible_rows,
        export_rows=export_rows,
        hidden_categories={"Скрытая"},
        normalize_onliner_id=_normalize_id,
        normalize_category=_normalize_category,
        category_sort_key=_category_sort_key,
    )

    assert payload["total"] == 4
    assert payload["suppliers"] == 2
    assert payload["with_id"] == 2
    assert payload["without_id"] == 2
    assert payload["duplicate_id_rows"] == 2
    assert payload["export_rows"] == 2
    assert payload["without_id_category_counts"] == [
        {"category": "Мышь", "count": 1},
        {"category": "Скрытая", "count": 1},
    ]
    assert payload["hidden_category_counts"] == [
        {"category": "Скрытая", "count": 1},
    ]
    assert payload["hidden_rows"] == 1
    assert payload["quality_suspicious_price_count"] == 1


def test_result_and_stats_contexts_add_only_request_specific_state():
    dashboard = {"without_id": 7}
    snapshot = {"new_without_id_count": 3}

    result = result_context(
        dashboard,
        show_checks_block=False,
        snapshot_diff=snapshot,
    )
    stats = stats_context(dashboard, snapshot_diff=snapshot)

    assert result["show_checks_block"] is False
    assert result["snapshot_diff"] == snapshot
    assert stats["new_without_id_count"] == 3
    assert stats["id_pick_badge_count"] == 3
    assert dashboard == {"without_id": 7}
