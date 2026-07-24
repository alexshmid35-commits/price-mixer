#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PRICE_MIXER_TEST_PYTHON:-python3}"

"$PYTHON" scripts/check_architecture.py
find static/js -type f -name '*.js' -print0 | xargs -0 -n1 node --check
"$PYTHON" -m ruff check \
  price_mixer/product_schema.py \
  price_mixer/services/__init__.py \
  price_mixer/api/operations_routes.py \
  price_mixer/services/export_delivery.py \
  price_mixer/services/export_runtime.py \
  price_mixer/services/session_data_runtime.py \
  price_mixer/services/session_products.py \
  price_mixer/services/session_read_model.py \
  price_mixer/services/sqlite_runtime.py \
  price_mixer/services/static_assets.py \
  price_mixer/services/session_page_runtime.py \
  price_mixer/services/session_snapshots.py \
  price_mixer/services/durable_jobs.py \
  price_mixer/services/category_repair_runtime.py \
  price_mixer/services/manual_id_search_runtime.py \
  price_mixer/services/processing_pipeline.py \
  price_mixer/services/service_container.py \
  price_mixer/services/sorting_reparse_runtime.py \
  price_mixer/services/upload_runtime.py \
  price_mixer/services/review_candidates.py \
  price_mixer/services/review_matching \
  price_mixer/workers/durable_worker.py \
  scripts/profile_sqlite.py \
  scripts/benchmark_matching_workers.py \
  scripts/benchmark_local.py \
  scripts/check_architecture.py \
  tests/unit/test_operations_routes.py \
  tests/unit/test_category_repair_runtime.py \
  tests/unit/test_manual_id_search_runtime.py \
  tests/unit/test_product_schema.py \
  tests/unit/test_service_container.py \
  tests/unit/test_sorting_reparse_runtime.py \
  tests/unit/test_upload_runtime.py \
  tests/unit/test_review_matching_engine.py \
  tests/unit/test_export_delivery.py \
  tests/unit/test_export_runtime.py \
  tests/unit/test_session_data_runtime.py \
  tests/unit/test_session_products.py \
  tests/unit/test_session_read_model.py \
  tests/unit/test_sqlite_runtime.py \
  tests/unit/test_sqlite_profile.py \
  tests/unit/test_static_assets.py \
  tests/unit/test_session_snapshots.py
"$PYTHON" -m ruff format --check \
  price_mixer/product_schema.py \
  price_mixer/services/__init__.py \
  price_mixer/api/operations_routes.py \
  price_mixer/services/export_delivery.py \
  price_mixer/services/export_runtime.py \
  price_mixer/services/session_data_runtime.py \
  price_mixer/services/session_products.py \
  price_mixer/services/session_read_model.py \
  price_mixer/services/sqlite_runtime.py \
  price_mixer/services/static_assets.py \
  price_mixer/services/session_page_runtime.py \
  price_mixer/services/session_snapshots.py \
  price_mixer/services/durable_jobs.py \
  price_mixer/services/category_repair_runtime.py \
  price_mixer/services/manual_id_search_runtime.py \
  price_mixer/services/processing_pipeline.py \
  price_mixer/services/service_container.py \
  price_mixer/services/sorting_reparse_runtime.py \
  price_mixer/services/upload_runtime.py \
  price_mixer/services/review_candidates.py \
  price_mixer/services/review_matching \
  price_mixer/workers/durable_worker.py \
  scripts/profile_sqlite.py \
  scripts/benchmark_matching_workers.py \
  scripts/benchmark_local.py \
  scripts/check_architecture.py
"$PYTHON" -m mypy \
  price_mixer/product_schema.py \
  price_mixer/services/__init__.py \
  price_mixer/api/operations_routes.py \
  price_mixer/services/export_delivery.py \
  price_mixer/services/export_runtime.py \
  price_mixer/services/session_data_runtime.py \
  price_mixer/services/session_products.py \
  price_mixer/services/session_read_model.py \
  price_mixer/services/sqlite_runtime.py \
  price_mixer/services/static_assets.py \
  price_mixer/services/session_page_runtime.py \
  price_mixer/services/session_snapshots.py \
  price_mixer/services/durable_jobs.py \
  price_mixer/services/category_repair_runtime.py \
  price_mixer/services/manual_id_search_runtime.py \
  price_mixer/services/processing_pipeline.py \
  price_mixer/services/service_container.py \
  price_mixer/services/sorting_reparse_runtime.py \
  price_mixer/services/upload_runtime.py \
  price_mixer/workers/durable_worker.py \
  scripts/profile_sqlite.py \
  scripts/benchmark_matching_workers.py \
  scripts/benchmark_local.py \
  price_mixer/services/review_matching/engine.py
"$PYTHON" -m pytest -q tests/unit

if [[ "${RUN_E2E:-0}" == "1" ]]; then
  PRICE_MIXER_TEST_PYTHON="$PYTHON" npm run test:e2e
fi

if [[ "${RUN_BENCHMARK:-0}" == "1" ]]; then
  "$PYTHON" scripts/benchmark_local.py \
    --sizes 5000,25000,100000 \
    --repeats 5 \
    --output test-results/local-benchmark.json
  "$PYTHON" scripts/benchmark_session_products.py \
    --sizes 5000 25000 \
    --repeats 5 \
    --output test-results/session-products-benchmark.json
fi
