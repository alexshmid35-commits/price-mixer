"""Gunicorn configuration for the current Price Mixer architecture."""

import os


bind = os.getenv("PRICE_MIXER_BIND", "127.0.0.1:5001")

# XLSX and API-source jobs are durable and external. A few interactive
# mutation locks/statuses are still process-local, so the supported profile
# intentionally remains one threaded web worker.
workers = 1
worker_class = "gthread"
threads = int(os.getenv("PRICE_MIXER_THREADS", "4"))

timeout = int(os.getenv("PRICE_MIXER_REQUEST_TIMEOUT", "900"))
graceful_timeout = int(
    os.getenv("PRICE_MIXER_GRACEFUL_TIMEOUT", "120")
)
keepalive = 5

preload_app = False
daemon = False
# Flask middleware emits the canonical access log without query strings.
accesslog = None
errorlog = "-"
capture_output = True
loglevel = os.getenv("PRICE_MIXER_LOG_LEVEL", "info")
proc_name = "price-mixer"

forwarded_allow_ips = os.getenv(
    "PRICE_MIXER_FORWARDED_ALLOW_IPS", "127.0.0.1"
)
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190
