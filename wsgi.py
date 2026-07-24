"""Gunicorn WSGI entrypoint for the Price Mixer production profile."""

from __future__ import annotations

import os

from werkzeug.middleware.proxy_fix import ProxyFix

from app import app, init_onliner_db
from price_mixer.services.production_config import (
    require_valid_production_environment,
)


require_valid_production_environment(os.environ)
init_onliner_db()

if str(os.getenv("PRICE_MIXER_TRUST_PROXY", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
    )

application = app
