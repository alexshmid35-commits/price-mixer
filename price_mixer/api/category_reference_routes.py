"""Category and supplier reference API routes."""

from __future__ import annotations

from typing import Callable

from flask import Blueprint, request
from price_mixer.api.response import as_response as _as_response


def create_category_reference_bp(
    *,
    get_categories: Callable[[], dict | tuple[dict, int]],
    get_category_catalog: Callable[[], dict | tuple[dict, int]],
    get_suppliers: Callable[[], dict | tuple[dict, int]],
    get_supplier_categories: Callable[[str], dict | tuple[dict, int]],
    get_onliner_category_preview: Callable[[], dict | tuple[dict, int]] | None = None,
) -> Blueprint:
    bp = Blueprint("category_reference_api", __name__)

    @bp.route("/api/categories")
    def api_categories():
        return _as_response(get_categories())

    @bp.route("/api/category-catalog")
    def api_category_catalog():
        return _as_response(get_category_catalog())

    @bp.route("/api/suppliers")
    def api_suppliers():
        return _as_response(get_suppliers())

    @bp.route("/api/supplier-categories")
    def api_supplier_categories():
        return _as_response(get_supplier_categories(str(request.args.get("supplier", "")).strip()))

    if get_onliner_category_preview is not None:
        @bp.route("/api/onliner-category-preview")
        def api_onliner_category_preview():
            return _as_response(get_onliner_category_preview())

    return bp
