"""Unit tests for the Onliner market runtime facade."""

from price_mixer.services import onliner_market_runtime as runtime_mod
from price_mixer.services.onliner_market_runtime import OnlinerMarketRuntime


def _runtime(**overrides):
    base = {
        "api_get": lambda *args, **kwargs: None,
        "get_product_by_id": lambda oid: None,
        "infer_category": lambda name: "",
        "get_b2b_settings": lambda: {},
        "fetch_b2b_stats": lambda oid, product_name="", category_name="": {},
        "read_consolidated_df": lambda session_dir: None,
        "ensure_category_column": lambda df: df,
        "row_category": lambda row: "",
        "load_id_cache": lambda: {},
        "load_auto_refresh_settings": lambda: {},
        "save_auto_refresh_settings": lambda settings: None,
        "get_last_session_dir": lambda: None,
    }
    base.update(overrides)
    return OnlinerMarketRuntime(**base)


def test_runtime_fetch_market_stats_wires_catalog_and_b2b(monkeypatch):
    calls = []

    def fake_fetch(onliner_id, **kwargs):
        calls.append((onliner_id, kwargs))
        return {"min": 10, "offers": 1}

    monkeypatch.setattr(runtime_mod.market_service, "fetch_onliner_market_stats", fake_fetch)
    runtime = _runtime(
        api_get="api",
        get_b2b_settings=lambda: {"enabled": True},
        fetch_b2b_stats=lambda oid, product_name="", category_name="": {"min": 1},
    )

    assert runtime.fetch_market_stats("123", product_name="SSD", category_name="SSD") == {"min": 10, "offers": 1}
    assert calls == [("123", {
        "product_name": "SSD",
        "category_name": "SSD",
        "api_get": "api",
        "get_b2b_settings": runtime.get_b2b_settings,
        "fetch_b2b_stats": runtime.fetch_b2b_stats,
    })]


def test_runtime_cached_stats_uses_db_and_category_callbacks(monkeypatch):
    calls = []

    def fake_cached(onliner_id, **kwargs):
        calls.append((onliner_id, kwargs))
        return {"avg": 12}

    monkeypatch.setattr(runtime_mod.market_service, "get_onliner_market_stats_cached", fake_cached)
    runtime = _runtime(get_product_by_id=lambda oid: {"name": "SSD"}, infer_category=lambda name: "SSD")

    assert runtime.get_market_stats_cached("123", cache={}) == {"avg": 12}
    assert calls[0][0] == "123"
    assert calls[0][1]["cache"] == {}
    assert calls[0][1]["get_product_by_id"] is runtime.get_product_by_id
    assert calls[0][1]["infer_category_fn"] is runtime.infer_category
    assert calls[0][1]["fetch_market_stats"] == runtime.fetch_market_stats


def test_runtime_auto_refresh_loop_passes_refresh_dependencies(monkeypatch):
    captured = {}

    def fake_loop(**kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(runtime_mod.refresh_service, "auto_market_refresh_loop", fake_loop)
    runtime = _runtime(
        load_auto_refresh_settings=lambda: {"enabled": True},
        save_auto_refresh_settings=lambda settings: None,
        get_last_session_dir=lambda: "/tmp/session",
    )

    assert runtime.auto_market_refresh_loop() == {"status": "ok"}
    assert captured["load_settings"] is runtime.load_auto_refresh_settings
    assert captured["save_settings"] is runtime.save_auto_refresh_settings
    assert captured["collect_known_ids"] == runtime.collect_known_onliner_ids
    assert captured["get_id_hints"] == runtime.market_id_hints_from_session
    assert captured["fetch_market_stats"] == runtime.fetch_market_stats
