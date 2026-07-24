"""Manual review queue API routes."""

from collections.abc import Callable, Mapping

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_review_queue_bp(
    *,
    start_handlers: Mapping[str, Callable[[], object]],
    list_queue: Callable[[], object],
    pick: Callable[[], object],
    clear: Callable[[], object],
) -> Blueprint:
    bp = Blueprint("review_queue_api", __name__)

    for path, handler in start_handlers.items():
        endpoint = path.strip("/").replace("/", "_").replace("-", "_")
        bp.add_url_rule(path, endpoint, lambda handler=handler: _as_response(handler()), methods=["POST"])

    bp.add_url_rule("/api/review-queue", "api_review_queue", lambda: _as_response(list_queue()))
    bp.add_url_rule("/api/review-queue-pick", "api_review_queue_pick", lambda: _as_response(pick()), methods=["POST"])
    bp.add_url_rule("/api/review-queue-clear", "api_review_queue_clear", lambda: _as_response(clear()), methods=["POST"])

    return bp
