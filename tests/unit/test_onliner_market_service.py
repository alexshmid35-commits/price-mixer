from price_mixer.services import onliner_market as svc


class FakeResponse:
    def __init__(self, payload=None, ok=True, status_code=200):
        self._payload = payload or {}
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


def test_safe_float_accepts_comma_and_rejects_bad_values():
    assert svc.safe_float("12,50") == 12.5
    assert svc.safe_float(" 7.25 ") == 7.25
    assert svc.safe_float("bad") is None
    assert svc.safe_float(None) is None


def test_extract_position_prices_walks_nested_payload():
    payload = {
        "data": [
            {"position_price": {"amount": "10,5"}},
            {"nested": {"position_price": {"amount": "0"}}},
            {"nested": {"position_price": {"amount": "-1"}}},
            {"nested": [{"position_price": {"amount": "20"}}]},
        ]
    }

    assert svc.extract_position_prices(payload) == [10.5, 20.0]


def test_extract_offer_rows_reads_positions_shops_and_deduplicates():
    payload = {
        "shops": {"7": {"title": "Shop 7", "html_url": "https://shop.test"}},
        "positions": {
            "primary": [
                {
                    "seller_id": "7",
                    "position_price": {"converted": {"BYN": {"amount": "100,45"}}},
                    "product_url": "https://product.test",
                    "stock_status": {"text": "in stock"},
                },
                {
                    "seller_id": "7",
                    "position_price": {"converted": {"BYN": {"amount": "100,45"}}},
                    "product_url": "https://product.test",
                },
            ]
        },
    }

    assert svc.extract_offer_rows(payload) == [
        {
            "seller_name": "Shop 7",
            "seller_id": "7",
            "seller_url": "https://shop.test",
            "price": 100.45,
            "url": "https://product.test",
            "warranty": "",
            "stock": "in stock",
            "updated_at": "",
        }
    ]


def test_extract_offer_rows_falls_back_to_recursive_walk():
    payload = {
        "payload": {
            "seller_name": "Nested seller",
            "price": "55",
            "url": "https://offer.test",
        }
    }

    rows = svc.extract_offer_rows(payload)

    assert len(rows) == 1
    assert rows[0]["seller_name"] == "Nested seller"
    assert rows[0]["price"] == 55.0
    assert rows[0]["url"] == "https://offer.test"


def test_market_stats_from_cache_only_normalizes_id_and_respects_ttl():
    cache = {
        "123": {
            "updated_at": 100,
            "min": "10,5",
            "avg": "11",
            "max": "12.25",
            "offers": "3",
            "min_competitors": "1",
            "avg_competitors": "2",
        }
    }

    assert svc.get_onliner_market_stats_from_cache_only("123.0", cache=cache, now_fn=lambda: 120) == {
        "min": 10.5,
        "avg": 11.0,
        "max": 12.25,
        "offers": 3,
        "min_competitors": 1,
        "avg_competitors": 2,
    }
    assert svc.get_onliner_market_stats_from_cache_only(
        "123",
        cache=cache,
        allow_stale=False,
        now_fn=lambda: 100 + svc.ONLINER_MARKET_CACHE_TTL + 1,
    ) == svc.empty_market_stats()


def test_market_stats_has_values_handles_partial_and_bad_stats():
    assert svc.market_stats_has_values({"min": None, "avg": None, "max": None, "offers": 0}) is False
    assert svc.market_stats_has_values({"offers": "2"}) is True
    assert svc.market_stats_has_values({"min": "1,5"}) is True
    assert svc.market_stats_has_values({"offers": "not-a-number"}) is False
    assert svc.market_stats_has_values(None) is False


def test_cache_load_save_round_trip(monkeypatch, tmp_path):
    market_path = tmp_path / "market.json"
    product_path = tmp_path / "product.json"
    monkeypatch.setattr(svc, "ONLINER_MARKET_CACHE_FILE", market_path)
    monkeypatch.setattr(svc, "ONLINER_PRODUCT_CACHE_FILE", product_path)

    svc.save_onliner_market_cache({"1": {"min": 10}})
    svc.save_onliner_product_cache({"1": {"name": "GPU"}})

    assert svc.load_onliner_market_cache() == {"1": {"min": 10}}
    assert svc.load_onliner_product_cache() == {"1": {"name": "GPU"}}


def test_fetch_onliner_product_payload_uses_search_when_direct_id_mismatches():
    calls = []

    def fake_api_get(url, **kwargs):
        calls.append(url)
        if "/products/123" in url:
            return FakeResponse({"id": "999", "name": "wrong"})
        return FakeResponse({"products": [{"id": "123", "name": "right"}]})

    product, error = svc.fetch_onliner_product_payload("123", api_get=fake_api_get)

    assert product == {"id": "123", "name": "right"}
    assert error == ""
    assert len(calls) == 2


def test_fetch_onliner_market_stats_catalog_api_computes_positions_stats():
    def fake_api_get(url, **kwargs):
        if "/products/123" in url:
            return FakeResponse({
                "id": "123",
                "prices": {
                    "price_min": {"amount": "50"},
                    "offers": {"count": 0},
                    "url": "https://positions.test/123",
                },
            })
        return FakeResponse({
            "positions": [
                {"position_price": {"amount": "10"}},
                {"position_price": {"amount": "20"}},
                {"nested": {"position_price": {"amount": "40"}}},
            ]
        })

    stats = svc.fetch_onliner_market_stats_catalog_api("123", api_get=fake_api_get)

    assert stats["min"] == 10.0
    assert stats["avg"] == 23.33
    assert stats["max"] == 40.0
    assert stats["offers"] == 3
    assert stats["min_competitors"] == 1
    assert stats["_error"] is False


def test_fetch_onliner_market_stats_falls_back_to_b2b_when_catalog_empty():
    def fake_api_get(url, **kwargs):
        return FakeResponse(ok=False, status_code=404)

    def fake_b2b(oid, product_name="", category_name=""):
        return {"min": 9, "avg": 10, "max": 11, "offers": 2}

    stats = svc.fetch_onliner_market_stats(
        "123",
        product_name="GPU",
        category_name="Видеокарта",
        api_get=fake_api_get,
        get_b2b_settings=lambda: {"enabled": True, "client_id": "id", "client_secret": "secret"},
        fetch_b2b_stats=fake_b2b,
    )

    assert stats == {"min": 9, "avg": 10, "max": 11, "offers": 2}


def test_get_onliner_market_stats_cached_uses_db_hints_and_updates_cache():
    cache = {}
    calls = []

    def fake_fetch(oid, product_name="", category_name=""):
        calls.append((oid, product_name, category_name))
        return {"min": 10, "avg": 12, "max": 14, "offers": 3}

    stats = svc.get_onliner_market_stats_cached(
        "123",
        cache=cache,
        get_product_by_id=lambda oid: {"name": "RTX 4070", "url": ""},
        infer_category_fn=lambda name: "Видеокарта",
        fetch_market_stats=fake_fetch,
        now_fn=lambda: 100,
    )

    assert stats["avg"] == 12
    assert cache["123"]["updated_at"] == 100
    assert calls == [("123", "RTX 4070", "Видеокарта")]


def test_get_onliner_market_stats_bulk_reuses_fresh_cache_and_saves_pending():
    cache = {"1": {"updated_at": 100, "min": "5", "avg": "6", "max": "7", "offers": "1"}}
    saved = []
    calls = []

    def fake_fetch(oid, product_name="", category_name=""):
        calls.append((oid, product_name, category_name))
        return {"min": 10, "avg": 11, "max": 12, "offers": 2}

    result = svc.get_onliner_market_stats_bulk(
        ["1", "2"],
        max_workers=1,
        id_hints={"2": {"name": "SSD", "category": "SSD"}},
        fetch_market_stats=fake_fetch,
        load_cache=lambda: cache,
        save_cache=lambda data: saved.append(dict(data)),
        now_fn=lambda: 120,
    )

    assert result["1"]["avg"] == 6.0
    assert result["2"]["avg"] == 11
    assert calls == [("2", "SSD", "SSD")]
    assert saved and saved[0]["2"]["updated_at"] == 120


def test_fetch_onliner_product_info_prefers_db_and_caches_result():
    cache = {}

    result = svc.fetch_onliner_product_info(
        "123",
        cache=cache,
        api_get=lambda url, **kwargs: FakeResponse(ok=False, status_code=500),
        get_product_by_id=lambda oid: {"name": "Local product", "url": "https://local.test"},
        now_fn=lambda: 200,
    )

    assert result == {"name": "Local product", "url": "https://local.test", "source": "db"}
    assert cache["123"] == {"updated_at": 200, "name": "Local product", "url": "https://local.test"}


def test_fetch_onliner_product_info_accepts_direct_key_match():
    cache = {}

    def fake_api_get(url, **kwargs):
        return FakeResponse({
            "id": "999",
            "key": "abc",
            "full_name": "Direct product",
            "html_url": "https://product.test",
        })

    result = svc.fetch_onliner_product_info(
        "abc",
        cache=cache,
        api_get=fake_api_get,
        get_product_by_id=lambda oid: None,
        now_fn=lambda: 300,
    )

    assert result == {"name": "Direct product", "url": "https://product.test", "source": "api"}
    assert cache["abc"]["name"] == "Direct product"
