"""Unit tests for Onliner diagnostics payload helpers."""

from price_mixer.services.onliner_diagnostics import (
    b2b_probe_payload,
    b2b_test_payload,
    offers_payload,
)


class ResponseStub:
    def __init__(self, payload, *, status_code=200, ok=True):
        self._payload = payload
        self.status_code = status_code
        self.ok = ok
        self.content = b"1"

    def json(self):
        return self._payload


def test_b2b_test_payload_returns_token_and_preview():
    body = b2b_test_payload(
        get_token=lambda force_refresh=False: {"token_type": "Bearer", "expires_in": 60},
        b2b_request=lambda method, path: ResponseStub({"shop": "ok"}, status_code=200),
    )

    assert body["status"] == "ok"
    assert body["expires_in"] == 60
    assert body["response_preview"] == {"shop": "ok"}


def test_b2b_probe_payload_walks_sections_manufacturers_products():
    responses = {
        "/sections": ResponseStub({"items": [{"id": "10", "name": "SSD"}]}),
        "/sections/10/manufacturers": ResponseStub({"items": [{"id": "20", "name": "Kingston"}]}),
        "/sections/10/manufacturers/20/products": ResponseStub({"items": [{"id": "30", "name": "NV2"}]}),
    }

    body = b2b_probe_payload(
        get_token=lambda force_refresh=False: {"token_type": "Bearer", "expires_in": 120},
        b2b_request=lambda method, path: responses[path],
    )

    assert body["status"] == "ok"
    assert body["sections_count"] == 1
    assert body["manufacturers_count"] == 1
    assert body["products_count"] == 1
    assert "SSD" in body["message"]


def test_offers_payload_counts_positions_and_unique_sellers():
    product = {"prices": {"offers": {"count": 3}, "url": "https://positions.test"}}

    body = offers_payload(
        "123",
        normalize_onliner_id=lambda value: str(value).strip(),
        fetch_product_payload=lambda oid: (product, ""),
        api_get=lambda url, timeout=0, headers=None: ResponseStub({"positions": "raw"}),
        extract_offer_rows=lambda payload: [
            {"seller_id": "1", "seller_name": "A"},
            {"seller_id": "1", "seller_name": "A"},
            {"seller_id": "2", "seller_name": "B"},
        ],
    )

    assert body["status"] == "ok"
    assert body["offers_count"] == 3
    assert body["positions_count"] == 3
    assert body["unique_sellers_count"] == 2


def test_offers_payload_handles_missing_positions_url():
    body = offers_payload(
        "123",
        normalize_onliner_id=lambda value: str(value).strip(),
        fetch_product_payload=lambda oid: ({"prices": {"offers": {"count": 5}}}, ""),
        api_get=lambda *args, **kwargs: None,
        extract_offer_rows=lambda payload: [],
    )

    assert body["status"] == "ok"
    assert body["offers_count"] == 5
    assert body["positions_count"] == 0
