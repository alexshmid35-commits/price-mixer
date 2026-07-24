"""Onliner diagnostics and offers API routes."""

from collections.abc import Callable

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_onliner_bp(
    *,
    b2b_test: Callable[[], object],
    b2b_probe: Callable[[], object],
    get_offers: Callable[[str], object],
) -> Blueprint:
    bp = Blueprint("onliner_api", __name__)

    bp.add_url_rule("/api/onliner-b2b-test", "api_onliner_b2b_test", lambda: _as_response(b2b_test()), methods=["POST"])
    bp.add_url_rule("/api/onliner-b2b-probe", "api_onliner_b2b_probe", lambda: _as_response(b2b_probe()), methods=["POST"])
    bp.add_url_rule("/api/onliner-offers/<onliner_id>", "api_onliner_offers", lambda onliner_id: _as_response(get_offers(onliner_id)))

    return bp
