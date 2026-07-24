#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PRICE_MIXER_TEST_PYTHON:-python3}"

"$PYTHON" scripts/check_architecture.py
find static/js -type f -name '*.js' -print0 | xargs -0 -n1 node --check
"$PYTHON" -m ruff check \
  price_mixer/product_schema.py \
  price_mixer/api/operations_routes.py \
  price_mixer/services/session_products.py \
  price_mixer/services/session_page_runtime.py \
  price_mixer/services/session_snapshots.py \
  price_mixer/services/durable_jobs.py \
  price_mixer/services/review_candidates.py \
  price_mixer/services/review_matching \
  price_mixer/workers/durable_worker.py \
  scripts/check_architecture.py \
  tests/unit/test_operations_routes.py \
  tests/unit/test_product_schema.py \
  tests/unit/test_review_matching_engine.py \
  tests/unit/test_session_products.py \
  tests/unit/test_session_snapshots.py
"$PYTHON" -m ruff format --check \
  price_mixer/product_schema.py \
  price_mixer/api/operations_routes.py \
  price_mixer/services/session_products.py \
  price_mixer/services/session_page_runtime.py \
  price_mixer/services/session_snapshots.py \
  price_mixer/services/durable_jobs.py \
  price_mixer/services/review_candidates.py \
  price_mixer/services/review_matching \
  price_mixer/workers/durable_worker.py \
  scripts/check_architecture.py
"$PYTHON" -m mypy \
  price_mixer/product_schema.py \
  price_mixer/api/operations_routes.py \
  price_mixer/services/session_products.py \
  price_mixer/services/session_page_runtime.py \
  price_mixer/services/session_snapshots.py \
  price_mixer/services/durable_jobs.py \
  price_mixer/workers/durable_worker.py \
  price_mixer/services/review_matching/engine.py
"$PYTHON" -m pytest -q tests/unit

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  PRICE_MIXER_TEST_PYTHON="$PYTHON" npm run test:e2e
fi

if [[ "${RUN_BENCHMARK:-0}" == "1" ]]; then
  "$PYTHON" scripts/benchmark_session_products.py \
    --sizes 5000 25000 \
    --repeats 5 \
    --output test-results/session-products-benchmark.json
fi
