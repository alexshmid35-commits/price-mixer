"""Result page template guards."""

from pathlib import Path

from flask import Flask, render_template


def test_duplicate_id_counter_visible_for_multiple_suppliers():
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "templates"))
    stats = {
        "consolidated": 10,
        "suppliers": 2,
        "without_id": 1,
        "duplicate_id_rows": 4,
        "export_rows": 6,
        "show_checks_block": True,
        "snapshot_diff": None,
    }

    with app.app_context():
        html = render_template("result.html", stats=stats)

    assert '<div class="num" id="duplicate-id-count">4</div>' in html
    assert 'id="duplicate-id-count" style="visibility:hidden;"' not in html
    assert '<span id="total-products-count">10</span><span class="stat-slash">/</span><span class="stat-export-num" id="export-products-count">6</span>' in html
    assert 'id="export-category-analytics-toggle" aria-label="Показать категории выгрузки в Google">▾</button>' in html
    assert 'id="export-category-analytics-btn" style="padding:8px 16px;font-size:13px;">Показать</button>' in html
    assert 'id="hidden-category-analytics-btn" aria-label="Показать скрытые категории">▾</button>' in html
    assert 'id="run-all-id-checks-btn"' in html
    assert 'id="autofill-ntech-pc-btn"' in html
    assert 'id="ntech-pc-review-badge"' in html


def test_gsheet_import_button_forces_fresh_download():
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "templates"))
    stats = {
        "consolidated": 10,
        "suppliers": 1,
        "without_id": 1,
        "duplicate_id_rows": 0,
        "export_rows": 8,
        "show_checks_block": True,
        "snapshot_diff": None,
    }

    with app.app_context():
        html = render_template("result.html", stats=stats)

    assert "force_refresh: true" not in html
    onliner_db_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-onliner-db.js"
    assert "force_refresh: true" in onliner_db_js.read_text(encoding="utf-8")


def test_result_template_uses_static_bootstrap_script():
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "templates"))
    stats = {
        "consolidated": 10,
        "suppliers": 1,
        "without_id": 1,
        "duplicate_id_rows": 0,
        "export_rows": 8,
        "show_checks_block": True,
        "snapshot_diff": None,
    }

    with app.app_context():
        html = render_template("result.html", stats=stats)

    assert '<script src="/static/js/result-utils.js"></script>' in html
    assert '<script src="/static/js/result-page.js"></script>' in html
    assert '<script src="/static/js/result-stats.js"></script>' in html
    assert '<script src="/static/js/result-badges.js"></script>' in html
    assert '<script src="/static/js/result-candidates.js"></script>' in html
    assert '<script src="/static/js/result-noid.js"></script>' in html
    assert '<script src="/static/js/result-main-table.js"></script>' in html
    assert '<script src="/static/js/result-id-checks.js"></script>' in html
    assert '<script src="/static/js/result-pricing.js"></script>' in html
    assert '<script src="/static/js/result-preview.js"></script>' in html
    assert '<script src="/static/js/result-validation.js"></script>' in html
    assert '<script src="/static/js/result-quality.js"></script>' in html
    assert '<script src="/static/js/result-review-queue.js"></script>' in html
    assert '<script src="/static/js/result-verify-ids.js"></script>' in html
    assert '<script src="/static/js/result-onliner-db.js"></script>' in html
    assert '<script src="/static/js/result-snapshot.js"></script>' in html
    assert '<script src="/static/js/result-actions.js"></script>' in html
    assert '<link rel="stylesheet" href="/static/css/result.css">' in html
    assert "function onResultPageReady" not in html
    assert "var CATEGORY_PRIORITY_JS" not in html
    assert "function updateStatsCounters" not in html
    assert "function renderExportCategoryAnalytics" not in html
    assert "function refreshActionBadges" not in html
    assert "function updateNtechCheckCategoryBadges" not in html
    assert "function normalizeTextForAiMatch" not in html
    assert "function isAiTextMatch" not in html
    assert "function highlightCandidateName" not in html
    assert "function fetchNoIdCandidates" not in html
    assert "function renderNoIdInlinePicker" not in html
    assert "function applyNoIdCandidate" not in html
    assert "function initMainTableFallback" not in html
    assert "function renderMainTableFallback" not in html
    assert "function renderMainPriceCell" not in html
    assert "function escapeHtml" not in html
    assert "function initNoIdFilterUI" not in html
    assert "function initOnlinerDbWidget" not in html
    assert "function initSnapshotFilterUI" not in html
    assert "function runDuplicateIdCheck" not in html
    assert "function renderDuplicateIdCandidates" not in html
    assert "function getSelectedValues" not in html
    assert "function initMarkupUI" not in html
    assert "function loadCategories" not in html
    assert "function movePreviewItemsToCategory" not in html
    assert "function openPreviewModal" not in html
    assert "function renderPreviewModalRows" not in html
    assert "function startMarketRefresh" not in html
    assert "function moveSelectedItemsToCategoryFromFullList" not in html
    assert "window.startValidateClean = function" not in html
    assert "function highlightCpuModelMatch" not in html
    assert "function queueCandidateTone" not in html
    assert "window.loadReviewQueue = function" not in html
    assert "function _doReviewPick" not in html
    assert "function ensureQualityCheckCardUI" not in html
    assert "function runPreExportQualityCheck" not in html
    assert "function reapplySavedMarkupsFromQuality" not in html
    assert "function runVerifyAllIds" not in html
    assert "function renderVerifyAllIdsStatus" not in html
    assert ".quality-card-head" not in html

    utils_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-utils.js"
    utils_text = utils_js.read_text(encoding="utf-8")
    assert "function escapeHtml" in utils_text
    assert "function toggleDuplicateIdCheckCard" in utils_text

    static_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-page.js"
    assert "window.CATEGORY_PRIORITY_JS" in static_js.read_text(encoding="utf-8")

    stats_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-stats.js"
    stats_text = stats_js.read_text(encoding="utf-8")
    assert "function updateStatsCounters" in stats_text
    assert "function renderExportCategoryAnalytics" in stats_text

    badges_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-badges.js"
    badges_text = badges_js.read_text(encoding="utf-8")
    assert "function refreshActionBadges" in badges_text
    assert "function updateNtechCheckCategoryBadges" in badges_text

    candidates_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-candidates.js"
    candidates_text = candidates_js.read_text(encoding="utf-8")
    assert "function normalizeTextForAiMatch" in candidates_text
    assert "function isAiTextMatch" in candidates_text
    assert "function highlightCandidateName" in candidates_text
    assert "function fetchNoIdCandidates" in candidates_text

    noid_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-noid.js"
    noid_text = noid_js.read_text(encoding="utf-8")
    assert "function renderNoIdInlinePicker" in noid_text
    assert "function applyNoIdCandidate" in noid_text

    main_table_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-main-table.js"
    main_table_text = main_table_js.read_text(encoding="utf-8")
    assert "function initMainTableFallback" in main_table_text
    assert "function applyMainTableServerMeta" in main_table_text
    assert "function renderMainTableFallback" in main_table_text
    assert "function renderMainPriceCell" in main_table_text

    id_checks_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-id-checks.js"
    id_checks_text = id_checks_js.read_text(encoding="utf-8")
    assert "function runDuplicateIdCheck" in id_checks_text
    assert "function renderDuplicateIdCandidates" in id_checks_text

    pricing_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-pricing.js"
    pricing_text = pricing_js.read_text(encoding="utf-8")
    assert "function getSelectedValues" in pricing_text
    assert "function initMarkupUI" in pricing_text
    assert "function loadCategories" in pricing_text
    assert "function movePreviewItemsToCategory" not in pricing_text

    preview_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-preview.js"
    preview_text = preview_js.read_text(encoding="utf-8")
    assert "function openPreviewModal" in preview_text
    assert "function renderPreviewModalRows" in preview_text
    assert "function startMarketRefresh" in preview_text
    assert "function moveSelectedItemsToCategoryFromFullList" not in preview_text
    assert "window.startValidateClean = function" not in preview_text

    validation_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-validation.js"
    validation_text = validation_js.read_text(encoding="utf-8")
    assert "window.startValidateClean = function" in validation_text
    assert "validate-clean-ids-status" in validation_text

    review_queue_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-review-queue.js"
    review_queue_text = review_queue_js.read_text(encoding="utf-8")
    assert "function highlightCpuModelMatch" in review_queue_text
    assert "function queueCandidateTone" in review_queue_text
    assert "window.loadReviewQueue = function" in review_queue_text
    assert "function _doReviewPick" in review_queue_text

    onliner_db_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-onliner-db.js"
    assert "function initOnlinerDbWidget" in onliner_db_js.read_text(encoding="utf-8")

    snapshot_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-snapshot.js"
    assert "function initSnapshotFilterUI" in snapshot_js.read_text(encoding="utf-8")

    actions_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-actions.js"
    actions_text = actions_js.read_text(encoding="utf-8")
    assert "function initNoIdFilterUI" in actions_text
    assert "function reportIssueKey" in actions_text
    assert "(item && item.generic_issue)" in actions_text
    assert "item.generic_issue_label" in actions_text

    quality_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-quality.js"
    quality_text = quality_js.read_text(encoding="utf-8")
    assert "function ensureQualityCheckCardUI" in quality_text
    assert "function runPreExportQualityCheck" in quality_text
    assert "function reapplySavedMarkupsFromQuality" in quality_text

    verify_ids_js = Path(__file__).resolve().parents[2] / "static" / "js" / "result-verify-ids.js"
    verify_ids_text = verify_ids_js.read_text(encoding="utf-8")
    assert "function runVerifyAllIds" in verify_ids_text
    assert "function renderVerifyAllIdsStatus" in verify_ids_text

    static_css = Path(__file__).resolve().parents[2] / "static" / "css" / "result.css"
    assert ".quality-card-head" in static_css.read_text(encoding="utf-8")


def test_experimental_noid_report_removes_only_completed_row():
    script_path = Path(__file__).resolve().parents[2] / "static" / "js" / "result-experimental-noid.js"
    script = script_path.read_text(encoding="utf-8")

    assert "function applyDecisionLocally(button, action)" in script
    assert "ID сохранён" in script
    assert "item.classList.add('decision-removing')" in script
    assert "return loadStatus({skipItemRefresh: true})" in script
    assert 'data-item-key="' in script
