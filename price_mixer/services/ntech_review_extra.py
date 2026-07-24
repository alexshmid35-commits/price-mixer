"""Generic N-Tech and supplier laptop review helpers."""

from __future__ import annotations

import re

from price_mixer.services.ntech_review_queue import (
    no_candidates_review_item,
    queued_review_item,
    skip_review_row,
)


def find_review_candidates(
    product_name,
    top_n=5,
    *,
    db_find_exact_id_for_name,
    db_find_top_candidates,
    normalize_onliner_id,
    candidate_filter=None,
    source_label="category_db",
):
    """Find, normalize and rank candidates for generic/laptop review."""
    name = str(product_name or "").strip()
    if not name:
        return []

    pool = []
    try:
        exact = db_find_exact_id_for_name(name)
        if exact:
            pool.append(exact)
    except Exception:
        pass
    try:
        pool.extend(
            db_find_top_candidates(
                name,
                top_n=30 if candidate_filter else 25,
                min_score=0.18,
                allow_b2b=False,
            )
            or []
        )
    except Exception:
        pass

    items = []
    seen = set()
    for candidate_rank, candidate in enumerate(pool):
        if not isinstance(candidate, dict):
            continue
        candidate_id = normalize_onliner_id(candidate.get("id", ""))
        candidate_name = str(candidate.get("name", "") or "").strip()
        candidate_url = str(candidate.get("url", "") or "").strip()
        if not candidate_id or not candidate_name or candidate_id in seen:
            continue
        if candidate_filter is not None and not candidate_filter(
            candidate_name,
            candidate_url,
        ):
            continue
        try:
            score = float(candidate.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if (
            score < 0.25
            and not str(candidate.get("source", "") or "").startswith("exact")
        ):
            continue
        seen.add(candidate_id)
        item = {
            "id": candidate_id,
            "name": candidate_name,
            "url": candidate_url,
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": (
                str(candidate.get("source", source_label) or source_label).strip()
                or source_label
            ),
        }
        if candidate_filter is not None:
            item["_rank"] = int(candidate_rank)
        items.append(item)

    if candidate_filter is None:
        items.sort(key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        ))
    else:
        items.sort(key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            int(item.get("_rank", 0) or 0),
        ))
        for item in items:
            item.pop("_rank", None)
    return items[:max(1, int(top_n))]


def extract_laptop_model_hint(name):
    text = str(name or "").strip()
    text = re.sub(
        r"^\s*(?:игровой\s+)?ноутбук\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80]


def build_supplier_laptop_review_handler(
    *,
    supplier_label,
    is_laptop_name,
    candidates_func,
    reason,
    reason_label,
    normalize_name_key,
    supplier_scoped_review_queue_key,
):
    def is_target(row, name, category):
        return is_laptop_name(name, category)

    def build_row_result(row_idx, row, name, category, now_ts):
        match_key = normalize_name_key(name)
        if not match_key:
            return skip_review_row()
        supplier_name = str(row.get("Поставщик", "") or "").strip()
        queue_key = supplier_scoped_review_queue_key(match_key, supplier_name)
        candidates = candidates_func(name, top_n=5)
        report_category = category or "Ноутбук"
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": report_category,
                "supplier": supplier_name,
                "generic_issue": "no_candidates",
                "generic_issue_label": (
                    f"Кандидатов ноутбука {supplier_label} в БД не найдено"
                ),
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "match_name_key": match_key,
            "category": report_category,
            "supplier": supplier_name,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": name,
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": reason,
            "reason_label": reason_label,
            "laptop_brand": supplier_label,
            "laptop_model": extract_laptop_model_hint(name),
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": report_category,
            "supplier": supplier_name,
            "generic_issue": "queued",
            "generic_issue_label": (
                "Есть кандидаты, отправлено в ручную очередь"
            ),
            "best_source": (
                str((candidates[0] or {}).get("source", "") or "").strip()
                if candidates
                else ""
            ),
            "candidates": list(candidates),
        }
        return queued_review_item(queue_key, queue_item, report_item)

    return is_target, build_row_result


def build_generic_category_review_handler(
    config,
    *,
    normalize_catalog_category_name,
    normalize_name_key,
    supplier_scoped_review_queue_key,
    candidates_func,
):
    categories = {
        normalize_catalog_category_name(str(category or "").strip())
        for category in (config.get("categories") or set())
        if str(category or "").strip()
    }
    label = str(config.get("label") or "Категория").strip()

    def is_target(row, name, category):
        return bool(name and category in categories)

    def build_row_result(row_idx, row, name, category, now_ts):
        match_key = normalize_name_key(name)
        if not match_key:
            return skip_review_row()
        supplier_name = str(row.get("Поставщик", "") or "").strip()
        queue_key = supplier_scoped_review_queue_key(match_key, supplier_name)
        candidates = candidates_func(name, top_n=5)
        report_category = category or label
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": report_category,
                "supplier": supplier_name,
                "generic_issue": "no_candidates",
                "generic_issue_label": "Кандидатов в БД не найдено",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "match_name_key": match_key,
            "category": report_category,
            "supplier": supplier_name,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": name,
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "ntech_category_manual",
            "reason_label": (
                f"{label} N-Tech: кандидаты найдены, "
                "требуется ручное подтверждение."
            ),
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": report_category,
            "supplier": supplier_name,
            "generic_issue": "queued",
            "generic_issue_label": (
                "Есть кандидаты, отправлено в ручную очередь"
            ),
            "best_source": (
                str((candidates[0] or {}).get("source", "") or "").strip()
                if candidates
                else ""
            ),
            "candidates": list(candidates),
        }
        return queued_review_item(queue_key, queue_item, report_item)

    return is_target, build_row_result
