"""Payload builders for Onliner ID reporting endpoints."""

from price_mixer.services.product_normalization import normalize_onliner_id


def build_id_replace_candidates_payload(
    payload,
    settings=None,
    db_get_product_by_id=None,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    specialized_candidates=None,
    score_candidate=None,
    candidate_allowed=None,
    category_path_hints=None,
    coerce_bool=None,
):
    settings = settings or {}
    no_id_cfg = settings.get("no_id_search") or {}
    payload = payload if isinstance(payload, dict) else {}
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "")).strip()
    query = str(payload.get("query", "")).strip()
    current_id = normalize_onliner_id(payload.get("onliner_id", ""))
    coerce_bool = coerce_bool or _default_coerce_bool
    exclude_current = coerce_bool(payload.get("exclude_current", False), default=False)
    limit = _candidate_limit(payload.get("limit", 80), no_id_cfg.get("max_candidates", 80))

    if not name and not query:
        return {"items": []}

    items = []
    seen = set()
    if current_id and not exclude_current:
        current = _current_id_candidate(
            current_id,
            category,
            db_get_product_by_id=db_get_product_by_id,
            category_path_hints=category_path_hints,
        )
        items.append(current)
        seen.add(current_id)

    local_candidates = []
    local_name = query or name
    if callable(specialized_candidates) and not query:
        specialized = specialized_candidates(local_name, category=category, top_n=limit)
        if isinstance(specialized, list):
            local_candidates.extend(specialized)
    if callable(db_find_exact_id_for_name):
        exact = db_find_exact_id_for_name(local_name)
        if isinstance(exact, dict):
            local_candidates.append(exact)
    if callable(db_find_top_candidates):
        local_top = db_find_top_candidates(local_name, top_n=limit, min_score=0.12, allow_b2b=False)
        if isinstance(local_top, list):
            local_candidates.extend(local_top)

    ranked_candidates = {}
    for candidate in local_candidates:
        if not isinstance(candidate, dict):
            continue
        cid = normalize_onliner_id(candidate.get("id", ""))
        if not cid:
            continue
        candidate = dict(candidate)
        if callable(candidate_allowed):
            allowed, _reason = candidate_allowed(local_name, str(candidate.get("name", "") or ""))
            if not allowed:
                continue
        if callable(score_candidate):
            candidate_name = str(candidate.get("name", "") or "").strip()
            candidate_url = str(candidate.get("url", "") or "").strip()
            comparisons = [score_candidate(local_name, candidate_name) or {}]
            if candidate_url:
                comparisons.append(score_candidate(local_name, f"{candidate_name} {candidate_url}") or {})
            comparison = max(
                comparisons,
                key=lambda item: (bool(item.get("match", False)), float(item.get("score", 0.0) or 0.0)),
            )
            comparison_score = float(comparison.get("score", 0.0) or 0.0)
            original_score = float(candidate.get("score", 0.0) or 0.0)
            comparison_reason = str(comparison.get("reason", "") or "")
            hard_mismatch_reasons = {
                "article_conflict",
                "apple_article_conflict",
                "category_mismatch",
                "model_variant_conflict",
                "numeric_article_conflict",
                "motherboard_brand_mismatch",
                "motherboard_model_mismatch",
                "strict_article_conflict",
                "tgpc_code_mismatch",
                "tgpc_gpu_mismatch",
            }
            if comparison_reason in hard_mismatch_reasons:
                continue
            if bool(comparison.get("match", False)):
                candidate["score"] = round((0.85 * comparison_score) + (0.15 * original_score), 3)
                candidate["reason"] = comparison_reason or candidate.get("reason", "")
        previous = ranked_candidates.get(cid)
        if previous is None or float(candidate.get("score", 0.0) or 0.0) > float(previous.get("score", 0.0) or 0.0):
            ranked_candidates[cid] = candidate

    local_candidates = sorted(
        ranked_candidates.values(),
        key=lambda candidate: -float(candidate.get("score", 0.0) or 0.0),
    )

    for candidate in local_candidates:
        cid = normalize_onliner_id(candidate.get("id", ""))
        if not cid or cid in seen:
            continue
        item = {
            "id": cid,
            "name": str(candidate.get("name", "")).strip(),
            "url": str(candidate.get("url", "")).strip(),
            "score": round(float(candidate.get("score", 0.0) or 0.0), 3),
            "source": str(candidate.get("source", "") or "local_db").strip(),
        }
        reason = str(candidate.get("reason", "") or "").strip()
        if reason:
            item["reason"] = reason
        items.append(item)
        seen.add(cid)
        if len(items) >= limit:
            break

    return {"items": items[:limit]}


def build_duplicate_onliner_ids_payload(df, build_duplicate_onliner_id_issues):
    if df.empty:
        return {
            "status": "ok",
            "problem_ids": 0,
            "problem_rows": 0,
            "items": [],
            "message": "В текущем прайсе нет строк для проверки.",
        }

    problem_ids, issues = build_duplicate_onliner_id_issues(df)
    if not issues:
        return {
            "status": "ok",
            "problem_ids": 0,
            "problem_rows": 0,
            "items": [],
            "message": "Одинаковых OnlinerID у разных товаров не найдено.",
        }

    return {
        "status": "ok",
        "problem_ids": int(problem_ids),
        "problem_rows": int(len(issues)),
        "items": issues,
        "message": f"Найдено одинаковых OnlinerID: {problem_ids}. Строк для проверки: {len(issues)}.",
    }


def _candidate_limit(raw_limit, raw_max_candidates):
    try:
        limit = int(raw_limit)
    except Exception:
        limit = 80
    try:
        max_candidates = int(raw_max_candidates or 80)
    except Exception:
        max_candidates = 80
    return max(10, min(limit, max_candidates, 150))


def _current_id_candidate(current_id, category, db_get_product_by_id=None, category_path_hints=None):
    item = db_get_product_by_id(current_id) if callable(db_get_product_by_id) else {}
    item = item or {}
    cur_name = str(item.get("name", "")).strip()
    cur_url = str(item.get("url", "")).strip()
    hints = category_path_hints(category) if callable(category_path_hints) else []
    if hints and cur_url and not any(hint in cur_url for hint in hints):
        cur_name = ""
        cur_url = ""
    return {
        "id": current_id,
        "name": cur_name or f"Текущий ID {current_id}",
        "url": cur_url,
        "score": 0.0,
        "source": "current",
    }


def _default_coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)
