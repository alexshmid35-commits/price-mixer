"""Category visibility, markup, and override API routes."""

from collections.abc import Callable, Mapping

from flask import Blueprint
from price_mixer.api.response import as_response as _as_response


def create_category_management_bp(
    *,
    handlers: Mapping[str, tuple[Callable[[], object], tuple[str, ...]]],
    name: str = "category_management_api",
) -> Blueprint:
    bp = Blueprint(name, __name__)

    for path, (handler, methods) in handlers.items():
        endpoint = path.strip("/").replace("/", "_").replace("-", "_")
        bp.add_url_rule(
            path,
            endpoint,
            lambda handler=handler: _as_response(handler()),
            methods=list(methods),
        )

    return bp
