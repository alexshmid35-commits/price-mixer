"""Lightweight guards for the current project boundaries."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_app_has_no_direct_http_route_decorators():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    assert not re.search(
        r"^@app\.(?:route|get|post|put|patch|delete)\b",
        app_py,
        flags=re.MULTILINE,
    )


def test_review_matching_is_split_into_category_plugins():
    facade = (
        ROOT / "price_mixer" / "services" / "review_candidates.py"
    ).read_text(encoding="utf-8")
    matching_dir = ROOT / "price_mixer" / "services" / "review_matching"
    categories = {
        path.stem
        for path in matching_dir.glob("*.py")
        if path.stem not in {"__init__", "engine", "features"}
    }

    assert len(facade.splitlines()) <= 50
    assert categories == {
        "board",
        "case",
        "cooler",
        "cpu",
        "gpu",
        "hdd",
        "monitor",
        "peripheral",
        "printer",
        "psu",
        "ram",
        "ssd",
    }


def test_result_template_stays_template_not_script_monolith():
    html = (ROOT / "templates" / "result.html").read_text(encoding="utf-8")

    assert len(html.splitlines()) <= 1700
    assert not re.search(r"^function\s+\w+\(", html, flags=re.MULTILINE)
    assert '<script src="/static/js/result-actions.js"></script>' in html
    assert '<script src="/static/js/result-main-table.js"></script>' in html
    assert '<script src="/static/js/result-validation.js"></script>' in html


def test_result_validation_is_not_mixed_back_into_preview_module():
    preview = (ROOT / "static" / "js" / "result-preview.js").read_text(encoding="utf-8")
    validation = (ROOT / "static" / "js" / "result-validation.js").read_text(encoding="utf-8")

    assert "validate-clean-ids-status" not in preview
    assert "window.startValidateClean = function" not in preview
    assert "validate-clean-ids-status" in validation
    assert "window.startValidateClean = function" in validation


def test_app_upload_housekeeping_stays_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "upload_sessions.py").read_text(encoding="utf-8")

    assert "_upload_sessions_cleanup_old" in app_py
    assert "_upload_sessions_maybe_cleanup_old" in app_py
    assert "def cleanup_old_uploads" in service
    assert "def maybe_cleanup_old_uploads" in service


def test_app_upload_processing_stays_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "processing_pipeline.py").read_text(encoding="utf-8")

    assert "_processing_process_supplier_files" in app_py
    assert "def process_supplier_files" in service
    assert "all_frames = []" not in app_py


def test_app_upload_file_preparation_stays_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "upload_files.py").read_text(encoding="utf-8")

    assert "_upload_files_build_entries" in app_py
    assert "def build_upload_file_entries" in service
    assert "file.save(str(filepath))" not in app_py
    assert "supplier_mapping = {}" not in app_py


def test_app_resolve_worker_stays_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "resolve_pipeline.py").read_text(encoding="utf-8")

    assert "_resolve_start_payload" in app_py
    assert "def start_resolve_payload" in service
    assert "id_to_name = {}" not in app_py
    assert "resolve_onliner_urls(" not in app_py


def test_source_fetch_processing_stays_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "api_sources.py").read_text(encoding="utf-8")
    runtime = (ROOT / "price_mixer" / "services" / "source_runtime.py").read_text(encoding="utf-8")

    assert "SourceRuntime" in app_py
    assert "class SourceRuntime" in runtime
    assert "def source_fetch_start_payload" in service
    assert "def process_source_payload" in service
    assert "def fetch_api_source_worker" in service
    assert "source_fetch_start_payload(" not in app_py
    assert "process_source_payload(" not in app_py


def test_manual_id_actions_stay_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "manual_id_actions.py").read_text(encoding="utf-8")
    runtime = (ROOT / "price_mixer" / "services" / "manual_id_runtime.py").read_text(encoding="utf-8")

    assert "ManualIdRuntime" in app_py
    assert "class ManualIdRuntime" in runtime
    assert "def confirm_manual_id_batch" in service
    assert "def clear_manual_id" in service
    assert "def rollback_last_manual_id_change" in service
    assert "confirm_manual_id_batch(" not in app_py
    assert "rollback_last_manual_id_change(" not in app_py


def test_category_extra_endpoints_stay_in_runtime_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime = (ROOT / "price_mixer" / "services" / "category_extra_runtime.py").read_text(encoding="utf-8")

    assert "CategoryExtraRuntime" in app_py
    assert "class CategoryExtraRuntime" in runtime
    assert "def override_bulk" in runtime
    assert "def autosort_preview" in runtime
    assert "def autosort_apply" in runtime
    assert "def reapply_saved_markups" in runtime
    assert "before_rrc = pd.to_numeric" not in app_py


def test_category_visibility_stays_in_management_runtime():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime = (
        ROOT
        / "price_mixer"
        / "services"
        / "category_management_runtime.py"
    ).read_text(encoding="utf-8")

    assert "CategoryManagementRuntime" in app_py
    assert "class CategoryManagementRuntime" in runtime
    assert "def visibility" in runtime
    app_visibility = app_py.split("def api_category_visibility", 1)[1].split(
        "@_serialized_price_mutation", 1
    )[0]
    assert "_get_category_management_runtime().visibility" in app_visibility
    assert "_category_update_visibility(" not in app_visibility
    assert "with CATEGORY_VISIBILITY_LOCK" not in app_visibility


def test_category_markup_endpoints_stay_in_management_runtime():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime = (
        ROOT
        / "price_mixer"
        / "services"
        / "category_management_runtime.py"
    ).read_text(encoding="utf-8")

    assert "def apply_markup" in runtime
    assert "def markup_preview" in runtime
    app_markup = app_py.split("def api_apply_markup", 1)[1].split(
        "def api_markup_preview", 1
    )[0]
    app_preview = app_py.split("def api_markup_preview", 1)[1].split(
        "def api_category_override_items", 1
    )[0]
    assert "_get_category_management_runtime().apply_markup" in app_markup
    assert "_category_apply_markup_to_df(" not in app_markup
    assert "write_consolidated_json(" not in app_markup
    assert "_get_category_management_runtime().markup_preview" in app_preview
    assert "_category_markup_preview_payload(" not in app_preview
    assert "read_consolidated_df(" not in app_preview


def test_category_override_endpoints_stay_in_management_runtime():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime = (
        ROOT
        / "price_mixer"
        / "services"
        / "category_management_runtime.py"
    ).read_text(encoding="utf-8")

    assert "def category_override_items" in runtime
    assert "def category_override_set" in runtime
    app_items = app_py.split("def api_category_override_items", 1)[1].split(
        "@_serialized_price_mutation", 1
    )[0]
    app_set = app_py.split("def api_category_override_set", 1)[1].split(
        "def api_category_preview_items", 1
    )[0]
    assert "_get_category_management_runtime().category_override_items" in app_items
    assert "_category_override_items_payload(" not in app_items
    assert "_get_category_management_runtime().category_override_set" in app_set
    assert "_category_apply_override_to_df(" not in app_set
    assert "with CATEGORY_OVERRIDE_LOCK" not in app_set
    assert "save_category_overrides(" not in app_set


def test_category_preview_items_stays_in_management_runtime():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime = (
        ROOT
        / "price_mixer"
        / "services"
        / "category_management_runtime.py"
    ).read_text(encoding="utf-8")

    assert "def category_preview_items" in runtime
    app_preview = app_py.split("def api_category_preview_items", 1)[1].split(
        "app.register_blueprint(create_category_management_bp", 1
    )[0]
    assert "_get_category_management_runtime().category_preview_items" in app_preview
    assert "_category_preview_items_payload(" not in app_preview
    assert "read_consolidated_df(" not in app_preview
    assert "load_onliner_market_cache" not in app_preview


def test_id_validation_start_status_stays_in_runtime_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime = (ROOT / "price_mixer" / "services" / "id_validation_runtime.py").read_text(encoding="utf-8")

    assert "IdValidationRuntime" in app_py
    assert "class IdValidationRuntime" in runtime
    assert "def verify_all_start" in runtime
    assert "def validate_clean_start" in runtime
    assert "start_validation_job(" not in app_py
    assert "verify_all_status_snapshot(" not in app_py


def test_local_db_validation_worker_stays_out_of_app_monolith():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    worker = (ROOT / "price_mixer" / "services" / "id_validation_db_worker.py").read_text(encoding="utf-8")

    assert "run_db_validation_worker" in app_py
    assert "def run_db_validation_worker" in worker
    app_worker = app_py.split("def _validate_clean_ids_db_worker", 1)[1].split(
        "def _manual_id_specialized_candidates", 1
    )[0]
    assert "read_consolidated_df(session_dir)" not in app_worker
    assert "run_db_validation_worker(session_dir" in app_worker


def test_api_validation_worker_stays_out_of_app_monolith():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    worker = (ROOT / "price_mixer" / "services" / "id_validation_api_worker.py").read_text(
        encoding="utf-8"
    )

    assert "run_api_validation_worker" in app_py
    assert "def run_api_validation_worker" in worker
    app_worker = app_py.split("def _validate_clean_ids_worker(session_dir)", 1)[1].split(
        "@_serialized_price_mutation", 1
    )[0]
    assert "read_consolidated_json_fast_df(session_dir)" not in app_worker
    assert "run_api_validation_worker(session_dir" in app_worker
    assert "def _validate_clean_ids_worker_legacy" not in app_py


def test_verify_all_worker_stays_out_of_app_monolith():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    worker = (
        ROOT / "price_mixer" / "services" / "id_validation_verify_worker.py"
    ).read_text(encoding="utf-8")

    assert "run_verify_all_worker" in app_py
    assert "def run_verify_all_worker" in worker
    app_worker = app_py.split("def _verify_all_ids_worker(session_dir)", 1)[1].split(
        "def _update_validate_clean_status", 1
    )[0]
    assert "ThreadPoolExecutor" not in app_worker
    assert "run_verify_all_worker(session_dir" in app_worker


def test_ntech_review_scan_stays_in_runtime_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    runtime = (
        ROOT / "price_mixer" / "services" / "ntech_review_runtime.py"
    ).read_text(encoding="utf-8")

    assert "NTechReviewRuntime" in app_py
    assert "class NTechReviewRuntime" in runtime
    app_runtime = app_py.split("def _get_ntech_review_runtime", 1)[1].split(
        "_NTECH_REVIEW_HANDLERS = None", 1
    )[0]
    assert "run_review_queue_scan(" not in app_runtime
    assert "build_review_queue_finish_payload(" not in app_runtime
    assert "_get_ntech_review_runtime().start" in app_runtime


def test_manual_review_queue_operations_stay_out_of_app_monolith():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (
        ROOT / "price_mixer" / "services" / "review_queue.py"
    ).read_text(encoding="utf-8")
    runtime = (
        ROOT / "price_mixer" / "services" / "review_queue_runtime.py"
    ).read_text(encoding="utf-8")

    assert "ReviewQueueRuntime" in app_py
    assert "class ReviewQueueRuntime" in runtime
    assert "def build_list_items" in service
    assert "def migrate_supplier_scope" in service
    assert "_get_review_queue_runtime().list()" in app_py
    assert "_get_review_queue_runtime().pick(payload)" in app_py
    assert "for row_idx, row in frame.iterrows()" not in app_py


def test_ntech_review_presets_and_extra_handlers_stay_out_of_app_monolith():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    presets = (
        ROOT / "price_mixer" / "services" / "ntech_review_presets.py"
    ).read_text(encoding="utf-8")
    extra = (
        ROOT / "price_mixer" / "services" / "ntech_review_extra.py"
    ).read_text(encoding="utf-8")

    assert "NTECH_CATEGORY_REVIEW_CONFIG" in presets
    assert "def build_core_review_start_kwargs" in presets
    assert "def build_supplier_laptop_review_handler" in extra
    assert "def build_generic_category_review_handler" in extra
    assert "_ntech_core_review_start_kwargs(mode)" in app_py
    assert "_ntech_build_laptop_handler(" in app_py
    assert "_NTECH_CATEGORY_REVIEW_CONFIG = {" not in app_py
    assert "pool.extend(db_find_top_candidates" not in app_py


def test_onliner_category_preview_payload_stays_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "onliner_category_preview.py").read_text(encoding="utf-8")

    assert "_onliner_category_preview_payload" in app_py
    assert "def build_onliner_category_preview_payload" in service
    assert "transition_counts = {}" not in app_py


def test_category_reference_payloads_stay_in_service_module():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "price_mixer" / "services" / "category_reference.py").read_text(encoding="utf-8")

    assert "_category_reference_categories_payload" in app_py
    assert "_category_reference_supplier_categories_payload" in app_py
    assert "def build_categories_payload" in service
    assert "def build_supplier_categories_payload" in service
    assert "category_without_id = {}" not in app_py
