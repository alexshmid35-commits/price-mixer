"""Helpers for N-Tech review queue endpoints."""

import time

NTECH_SUPPLIER_NAMES = {"N-TECH", "NTECH"}


def skip_review_row():
    return {"action": "skip"}


def no_model_review_item(report_item):
    return {"action": "no_model", "report_item": report_item}


def no_candidates_review_item(report_item):
    return {"action": "no_candidates", "report_item": report_item}


def queued_review_item(name_key, queue_item, report_item):
    return {
        "action": "queued",
        "name_key": name_key,
        "queue_item": queue_item,
        "report_item": report_item,
    }


def run_review_queue_scan(
    df,
    queue,
    *,
    now_ts,
    is_target_row,
    build_row_result,
    row_category,
    normalize_catalog_category_name,
    normalize_onliner_id,
    ntech_supplier_names=None,
):
    supplier_names = {
        str(name or "").strip().upper()
        for name in (ntech_supplier_names or NTECH_SUPPLIER_NAMES)
        if str(name or "").strip()
    }
    scanned = 0
    queued = 0
    no_model = 0
    no_candidates = 0
    skipped_with_id = 0
    skipped_non_ntech = 0
    report_items = []

    for row_idx, row in df.iterrows():
        supplier = str(row.get("Поставщик", "") or "").strip()
        if supplier.upper() not in supplier_names:
            skipped_non_ntech += 1
            continue

        name = str(row.get("Название", "") or "").strip()
        category = normalize_catalog_category_name(str(row_category(row) or "").strip())
        if not is_target_row(row=row, name=name, category=category):
            continue

        if normalize_onliner_id(row.get("OnlinerID", "")):
            skipped_with_id += 1
            continue

        if not name:
            continue

        scanned += 1
        row_result = build_row_result(
            row_idx=row_idx,
            row=row,
            name=name,
            category=category,
            now_ts=now_ts,
        ) or skip_review_row()
        action = str(row_result.get("action", "skip") or "skip")
        if action == "skip":
            continue
        if action == "no_model":
            no_model += 1
            report_items.append(row_result.get("report_item", {}))
            continue
        if action == "no_candidates":
            no_candidates += 1
            report_items.append(row_result.get("report_item", {}))
            continue
        if action == "queued":
            name_key = str(row_result.get("name_key", "") or "").strip()
            if not name_key:
                continue
            queue[name_key] = dict(row_result.get("queue_item", {}) or {})
            report_items.append(row_result.get("report_item", {}))
            queued += 1

    return {
        "scanned": int(scanned),
        "queued": int(queued),
        "no_model": int(no_model),
        "no_candidates": int(no_candidates),
        "skipped_with_id": int(skipped_with_id),
        "skipped_non_ntech": int(skipped_non_ntech),
        "report_items": report_items,
    }


def build_review_queue_finish_payload(
    report_mode,
    report_title,
    report_items,
    scanned,
    queued,
    no_candidates,
    skipped_with_id,
    skipped_non_ntech,
    success_message,
    empty_message,
    report_subtitle,
    empty_report_subtitle,
    now_ts,
    no_model=None,
    finished_at=None,
):
    report_items = list(report_items or [])
    scanned = int(scanned)
    queued = int(queued)
    no_candidates = int(no_candidates)
    skipped_with_id = int(skipped_with_id)
    skipped_non_ntech = int(skipped_non_ntech)
    has_no_model = no_model is not None
    no_model_value = int(no_model or 0)

    base_report = {
        "matches": [],
        "no_match": report_items,
        "report_mode": report_mode,
        "report_title": report_title,
        "report_subtitle": report_subtitle,
    }

    if scanned <= 0:
        payload = {
            "status": "ok",
            "scanned": 0,
            "queued": 0,
            "no_candidates": 0,
            "skipped_with_id": skipped_with_id,
            "skipped_non_ntech": skipped_non_ntech,
            "message": empty_message,
            **base_report,
        }
        if has_no_model:
            payload["no_model"] = 0
        status = _build_autofill_status(
            total=0,
            skipped=0,
            started_at=now_ts,
            finished_at=finished_at,
            message=empty_message,
            report_mode=report_mode,
            report_title=report_title,
            report_subtitle=empty_report_subtitle,
            no_match=[],
        )
        return payload, status

    payload = {
        "status": "ok",
        "scanned": scanned,
        "queued": queued,
        "no_candidates": no_candidates,
        "skipped_with_id": skipped_with_id,
        "skipped_non_ntech": skipped_non_ntech,
        "message": success_message,
        **base_report,
    }
    if has_no_model:
        payload["no_model"] = no_model_value

    status = _build_autofill_status(
        total=scanned,
        skipped=no_candidates + no_model_value,
        started_at=now_ts,
        finished_at=finished_at,
        message=success_message,
        report_mode=report_mode,
        report_title=report_title,
        report_subtitle=report_subtitle,
        no_match=report_items,
    )
    return payload, status


def _build_autofill_status(
    total,
    skipped,
    started_at,
    finished_at,
    message,
    report_mode,
    report_title,
    report_subtitle,
    no_match,
):
    return {
        "running": False,
        "total": int(total),
        "done": int(total),
        "applied": 0,
        "skipped": int(skipped),
        "percent": 100,
        "started_at": int(started_at),
        "finished_at": int(time.time() if finished_at is None else finished_at),
        "message": message,
        "matches": [],
        "no_match": list(no_match or []),
        "report_mode": report_mode,
        "report_title": report_title,
        "report_subtitle": report_subtitle,
    }
