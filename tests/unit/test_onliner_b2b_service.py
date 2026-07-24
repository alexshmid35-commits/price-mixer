"""Unit tests for Onliner B2B service helpers."""

from price_mixer.services import onliner_b2b
from price_mixer.services.onliner_b2b import (
    b2b_cache_get,
    b2b_cache_set,
    b2b_market_stats_error,
    b2b_section_tokens,
    b2b_row_price_value,
    fetch_market_stats_b2b,
    market_stats_from_b2b_position_rows,
    normalize_b2b_dict_items,
    onliner_b2b_get_token,
    resolve_catalog_path_for_product,
    search_candidates,
)


class _TokenResponse:
    content = b"{}"

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return dict(self.payload)


def test_normalize_b2b_dict_items_handles_nested_payloads():
    payload = {"sections": {"10": {"name": "SSD"}, "20": "CPU"}}

    assert normalize_b2b_dict_items(payload) == [
        {"name": "SSD", "id": "10"},
        {"id": "20", "name": "CPU"},
    ]


def test_b2b_cache_round_trip_with_key(monkeypatch):
    onliner_b2b.B2B_CATALOG_CACHE["products"] = {}
    monkeypatch.setattr(onliner_b2b.time, "time", lambda: 1000)

    b2b_cache_set("products", [{"id": "1"}], key="s|m")

    assert b2b_cache_get("products", key="s|m", ttl=60) == [{"id": "1"}]


def test_b2b_cache_expires(monkeypatch):
    onliner_b2b.B2B_CATALOG_CACHE["sections"] = {"ts": 1000, "items": [{"id": "1"}]}
    monkeypatch.setattr(onliner_b2b.time, "time", lambda: 2000)

    assert b2b_cache_get("sections", ttl=60) is None


def test_onliner_b2b_get_token_uses_cache(monkeypatch):
    onliner_b2b.B2B_TOKEN_CACHE.update({"access_token": "cached", "expires_at": 2000})
    monkeypatch.setattr(onliner_b2b.time, "time", lambda: 1000)
    monkeypatch.setattr(onliner_b2b, "get_onliner_b2b_settings", lambda: {
        "enabled": True,
        "client_id": "id",
        "client_secret": "secret",
    })

    token = onliner_b2b_get_token()

    assert token["access_token"] == "cached"
    assert token["source"] == "cache"


def test_onliner_b2b_get_token_requests_oauth(monkeypatch):
    calls = []
    onliner_b2b.B2B_TOKEN_CACHE.update({"access_token": "", "expires_at": 0})
    monkeypatch.setattr(onliner_b2b.time, "time", lambda: 1000)
    monkeypatch.setattr(onliner_b2b, "get_onliner_b2b_settings", lambda: {
        "enabled": True,
        "client_id": "id",
        "client_secret": "secret",
        "token_url": "https://b2b.example/oauth",
        "verify_ssl": False,
        "timeout_sec": 7,
    })

    def _post(url, **kwargs):
        kwargs["url"] = url
        calls.append(kwargs)
        return _TokenResponse({"access_token": "fresh", "expires_in": 120, "token_type": "Bearer"})

    monkeypatch.setattr(onliner_b2b.requests, "post", _post)

    token = onliner_b2b_get_token(force_refresh=True)

    assert token["access_token"] == "fresh"
    assert token["source"] == "oauth"
    assert onliner_b2b.B2B_TOKEN_CACHE["access_token"] == "fresh"
    assert calls[0]["url"] == "https://b2b.example/oauth"
    assert calls[0]["data"] == {"grant_type": "client_credentials"}
    assert calls[0]["verify"] is False


def test_b2b_row_price_value_prefers_promo_price():
    assert b2b_row_price_value({"pricePromo": {"amount": "99,50"}, "price": "120"}) == 99.5
    assert b2b_row_price_value({"price": {"converted": {"amount": 42}}}) == 42.0
    assert b2b_row_price_value({"price": 0}) is None


def test_market_stats_from_b2b_position_rows():
    stats = market_stats_from_b2b_position_rows([
        {"price": "100"},
        {"pricePromo": "102"},
        {"price": "130"},
    ])

    assert stats["min"] == 100.0
    assert stats["avg"] == 110.67
    assert stats["max"] == 130.0
    assert stats["offers"] == 3
    assert stats["_error"] is False


def test_b2b_market_stats_error_shape():
    payload = b2b_market_stats_error("bad")

    assert payload["min"] is None
    assert payload["offers"] == 0
    assert payload["_error"] is True
    assert payload["_error_reason"] == "bad"


def test_fetch_market_stats_b2b_rejects_disabled_settings():
    stats = fetch_market_stats_b2b(
        "123",
        get_settings=lambda: {"enabled": False},
    )

    assert stats["_error"] is True
    assert stats["_error_reason"] == "b2b выключен в настройках"


def test_fetch_market_stats_b2b_resolves_and_fetches_positions():
    calls = []

    stats = fetch_market_stats_b2b(
        "123.0",
        product_name="SSD",
        category_name="SSD",
        get_settings=lambda: {"enabled": True, "client_id": "id", "client_secret": "secret"},
        resolve_catalog_path=lambda oid, product_name="", category_name="": calls.append((oid, product_name, category_name)) or ("s1", "m1"),
        fetch_positions=lambda section_id, manufacturer_id, oid: [
            {"price": "10"},
            {"price": "12"},
        ],
    )

    assert calls == [("123", "SSD", "SSD")]
    assert stats["min"] == 10.0
    assert stats["offers"] == 2
    assert stats["_error"] is False


def test_fetch_market_stats_b2b_reports_position_errors():
    stats = fetch_market_stats_b2b(
        "123",
        get_settings=lambda: {"enabled": True, "client_id": "id", "client_secret": "secret"},
        resolve_catalog_path=lambda oid, product_name="", category_name="": ("s1", "m1"),
        fetch_positions=lambda section_id, manufacturer_id, oid: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert stats["_error"] is True
    assert stats["_error_reason"] == "b2b positions: boom"


def test_b2b_section_tokens_uses_category_aliases():
    assert "ssd" in b2b_section_tokens("SSD", "")
    assert "блок питания" in b2b_section_tokens("", "Блок питания 750W")


def test_resolve_catalog_path_returns_cached_path():
    result = resolve_catalog_path_for_product(
        "123",
        product_name="SSD",
        get_settings=lambda: {"enabled": True},
        cache_get=lambda bucket, key=None, ttl=0: ["10", "20"],
    )

    assert result == ("10", "20")


def test_resolve_catalog_path_uses_db_name_and_full_product_scan():
    writes = []

    result = resolve_catalog_path_for_product(
        "123.0",
        get_settings=lambda: {"enabled": True},
        get_product_by_id=lambda oid: {"name": "Samsung SSD 980"},
        preferred_brand_token=lambda name: "Samsung",
        extract_article=lambda name: "",
        priority_model_queries=lambda name: ["980"],
        name_tokens=lambda name: name.lower().split(),
        get_sections=lambda: [{"id": "s1", "name": "SSD накопители"}],
        get_manufacturers=lambda section_id: [{"id": "m1", "name": "Samsung"}],
        get_products=lambda section_id, manufacturer_id, title="": [{"id": "123", "name": "Samsung SSD 980"}] if title == "" else [],
        cache_get=lambda bucket, key=None, ttl=0: None,
        cache_set=lambda bucket, items, key=None: writes.append((bucket, items, key)),
    )

    assert result == ("s1", "m1")
    assert writes == [("product_path", ["s1", "m1"], "123")]


def test_resolve_catalog_path_falls_back_to_query_search():
    queries = []

    def _get_products(section_id, manufacturer_id, title=""):
        queries.append(title)
        if title == "980":
            return [{"id": "123", "name": "Samsung SSD 980"}]
        return []

    result = resolve_catalog_path_for_product(
        "123",
        product_name="Samsung SSD 980",
        get_settings=lambda: {"enabled": True},
        preferred_brand_token=lambda name: "Samsung",
        extract_article=lambda name: "",
        priority_model_queries=lambda name: ["980"],
        name_tokens=lambda name: name.lower().split(),
        get_sections=lambda: [{"id": "s1", "name": "SSD накопители"}],
        get_manufacturers=lambda section_id: [{"id": "m1", "name": "Samsung"}],
        get_products=_get_products,
        cache_get=lambda bucket, key=None, ttl=0: None,
        cache_set=lambda bucket, items, key=None: None,
    )

    assert result == ("s1", "m1")
    assert queries[:2] == ["", "980"]


def test_resolve_catalog_path_returns_empty_when_b2b_disabled():
    assert resolve_catalog_path_for_product("123", product_name="SSD", get_settings=lambda: {"enabled": False}) == (None, None)


def test_search_candidates_scores_and_upserts_match():
    upserts = []

    result = search_candidates(
        "Samsung SSD 980",
        category_name="SSD",
        get_settings=lambda: {"enabled": True},
        get_sections=lambda: [{"id": "s1", "name": "SSD накопители"}],
        get_manufacturers=lambda section_id: [{"id": "m1", "name": "Samsung"}],
        get_products=lambda section_id, manufacturer_id, title="": [{"id": "123", "name": "Samsung SSD 980"}],
        preferred_brand_token=lambda name: "Samsung",
        extract_article=lambda name: "",
        priority_model_queries=lambda name: ["980"],
        name_tokens=lambda name: name.lower().split(),
        article_like_tokens=lambda name: set(),
        strict_candidate_allowed=lambda left, right: (True, ""),
        calc_name_match=lambda left, right: {"score": 0.7, "match": True, "reason": "exact-ish"},
        get_product_by_id=lambda oid: {"url": "https://catalog.onliner.by/ssd/123"},
        normalize_compact_name=lambda value: str(value).lower().replace(" ", ""),
        upsert_product=lambda oid, name, url, source: upserts.append((oid, name, url, source)),
    )

    assert result == [{
        "id": "123",
        "name": "Samsung SSD 980",
        "url": "https://catalog.onliner.by/ssd/123",
        "score": 0.76,
        "source": "b2b",
        "reason": "exact-ish",
    }]
    assert upserts == [("123", "Samsung SSD 980", "https://catalog.onliner.by/ssd/123", "b2b")]


def test_search_candidates_article_mismatch_penalizes_candidate():
    result = search_candidates(
        "Samsung SSD 980 MZ-V8V1T0BW",
        category_name="SSD",
        get_settings=lambda: {"enabled": True},
        get_sections=lambda: [{"id": "s1", "name": "SSD накопители"}],
        get_manufacturers=lambda section_id: [{"id": "m1", "name": "Samsung"}],
        get_products=lambda section_id, manufacturer_id, title="": [{"id": "123", "name": "Samsung SSD 980"}],
        get_articles=lambda section_id, manufacturer_id, product_id: ["OTHER"],
        preferred_brand_token=lambda name: "Samsung",
        extract_article=lambda name: "MZ-V8V1T0BW",
        priority_model_queries=lambda name: ["980"],
        name_tokens=lambda name: name.lower().split(),
        article_like_tokens=lambda name: {"mz-v8v1t0bw"},
        strict_candidate_allowed=lambda left, right: (True, ""),
        calc_name_match=lambda left, right: {"score": 0.5, "match": False, "reason": "partial"},
        normalize_compact_name=lambda value: str(value).lower(),
    )

    assert result == []


def test_search_candidates_article_match_boosts_candidate():
    result = search_candidates(
        "Samsung SSD 980 MZ-V8V1T0BW",
        category_name="SSD",
        get_settings=lambda: {"enabled": True},
        get_sections=lambda: [{"id": "s1", "name": "SSD накопители"}],
        get_manufacturers=lambda section_id: [{"id": "m1", "name": "Samsung"}],
        get_products=lambda section_id, manufacturer_id, title="": [{"id": "123", "name": "Samsung SSD 980"}],
        get_articles=lambda section_id, manufacturer_id, product_id: ["MZ-V8V1T0BW"],
        preferred_brand_token=lambda name: "Samsung",
        extract_article=lambda name: "MZ-V8V1T0BW",
        priority_model_queries=lambda name: ["980"],
        name_tokens=lambda name: name.lower().split(),
        article_like_tokens=lambda name: {"mz-v8v1t0bw"},
        strict_candidate_allowed=lambda left, right: (True, ""),
        calc_name_match=lambda left, right: {"score": 0.5, "match": False, "reason": "partial"},
        normalize_compact_name=lambda value: str(value).lower(),
    )

    assert result[0]["score"] == 0.98


def test_search_candidates_returns_empty_when_disabled_or_blank():
    assert search_candidates("SSD", get_settings=lambda: {"enabled": False}) == []
    assert search_candidates("", get_settings=lambda: {"enabled": True}) == []
