"""Flask API routes blueprint.

New routes should be added here. Legacy routes in app.py will be migrated
incrementally to this module.
"""

from flask import Blueprint, jsonify

bp = Blueprint("api", __name__, url_prefix="")


@bp.route("/api/health")
def health_check():
    """Return basic health status."""
    return jsonify({"status": "ok", "service": "price-mixer"})


@bp.route("/api/version")
def version():
    """Return current API version."""
    return jsonify({"version": "2.0.0-refactor", "module": "price_mixer.api"})
