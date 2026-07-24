"""API source fetch/process routes."""

from collections.abc import Callable, Mapping

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_source_bp(
    *,
    handlers: Mapping[str, tuple[Callable[[], object], tuple[str, ...]]],
) -> Blueprint:
    bp = Blueprint("source_api", __name__)

    for path, (handler, methods) in handlers.items():
        endpoint = path.strip("/").replace("/", "_").replace("-", "_")
        bp.add_url_rule(
            path,
            endpoint,
            lambda handler=handler: _as_response(handler()),
            methods=list(methods),
        )

    return bp
