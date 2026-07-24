"""Category autosort helpers."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math


def predict_openai_category(
    product_name,
    categories,
    local_hint="",
    api_key="",
    model="gpt-4o-mini",
    timeout_sec=9,
    cache=None,
    cache_lock=None,
    requests_post=None,
):
    if not str(api_key or "").strip():
        return "", 0.0, "no_api_key"

    name = str(product_name or "").strip()
    valid_categories = [str(category).strip() for category in (categories or []) if str(category).strip()]
    if not name or not valid_categories:
        return "", 0.0, "bad_input"

    cache_key = build_category_cache_key(name, valid_categories)
    cached = _cache_get(cache, cache_lock, cache_key)
    if isinstance(cached, dict):
        return (
            str(cached.get("category", "")).strip(),
            float(cached.get("confidence", 0.0) or 0.0),
            str(cached.get("reason", "cache")).strip() or "cache",
        )
    if not callable(requests_post):
        return "", 0.0, "no_http_client"

    system_prompt = (
        "You are a strict product categorization assistant for IT goods. "
        "Pick ONLY one category from the provided list. "
        "If uncertain, return empty category with low confidence. "
        "Respond as compact JSON only."
    )
    user_prompt = {
        "task": "categorize_product",
        "product_name": name,
        "allowed_categories": valid_categories,
        "local_hint": str(local_hint or "").strip(),
        "output_format": {
            "category": "string from allowed_categories or empty",
            "confidence": "number 0..1",
            "reason": "short string",
        },
    }

    try:
        response = requests_post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
            },
            timeout=timeout_sec,
        )
        if not response.ok:
            return "", 0.0, f"http_{response.status_code}"
        category, confidence, reason = _parse_category_response(response, valid_categories)
        _cache_set(cache, cache_lock, cache_key, {
            "category": category,
            "confidence": confidence,
            "reason": reason,
        })
        return category, confidence, reason
    except Exception:
        return "", 0.0, "exception"


def build_category_cache_key(name, valid_categories):
    return f"{str(name or '').strip().lower()}|{'|'.join(sorted(valid_categories or []))}"[:1500]


def _parse_category_response(response, valid_categories):
    payload = response.json() or {}
    choices = payload.get("choices") or []
    if not choices:
        return "", 0.0, "no_choices"
    content = str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()
    if not content:
        return "", 0.0, "empty_content"
    parsed = json.loads(content)
    category = str((parsed or {}).get("category", "")).strip()
    confidence = float((parsed or {}).get("confidence", 0.0) or 0.0)
    reason = str((parsed or {}).get("reason", "ai")).strip() or "ai"
    if category not in valid_categories:
        return "", 0.0, "category_out_of_allowed"
    return category, max(0.0, min(1.0, confidence)), reason


def _cache_get(cache, cache_lock, key):
    if cache is None:
        return None
    if cache_lock is None:
        return cache.get(key)
    with cache_lock:
        return cache.get(key)


def _cache_set(cache, cache_lock, key, value):
    if cache is None:
        return
    if cache_lock is None:
        _cache_set_unlocked(cache, key, value)
        return
    with cache_lock:
        _cache_set_unlocked(cache, key, value)


def _cache_set_unlocked(cache, key, value):
    cache[key] = value
    if len(cache) > 2500:
        for old_key in list(cache.keys())[:400]:
            cache.pop(old_key, None)


def build_autosort_preview_payload(
    df,
    payload,
    *,
    overrides,
    openai_api_key,
    max_items,
    max_workers,
    predict_category,
    name_tokens,
    row_category,
    build_item_category_key,
    build_item_category_keys,
    normalize_onliner_id,
    category_sort_key,
):
    categories = (payload or {}).get("categories", [])
    selected = {str(c).strip() for c in categories if str(c).strip()} if isinstance(categories, list) else set()
    try:
        min_confidence = float((payload or {}).get("min_confidence", 0.64))
    except Exception:
        min_confidence = 0.64
    min_confidence = max(0.50, min(0.95, min_confidence))

    if df is None or df.empty or "Название" not in df.columns:
        return {"items": [], "checked": 0, "skipped": 0}

    category_token_counts, category_item_counts = _build_local_category_model(
        df,
        overrides,
        name_tokens=name_tokens,
        row_category=row_category,
    )
    token_category_df = _token_category_document_frequency(category_token_counts)

    checked = 0
    skipped = 0
    ai_checked = 0
    ai_suggested = 0
    ai_unavailable = 0
    proposals = {}
    conflict_keys = set()
    ai_candidates = []

    for _, row in df.iterrows():
        current_category = row_category(row, overrides)
        if selected and current_category not in selected:
            continue
        checked += 1

        name = str(row.get("Название", "")).strip()
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        target_category, confidence = _predict_local_category(
            name,
            category_token_counts,
            category_item_counts,
            token_category_df,
            name_tokens=name_tokens,
        )
        ai_candidates.append({
            "row": row,
            "name": name,
            "oid": oid,
            "current_category": current_category,
            "local_target": target_category,
            "local_confidence": confidence,
        })

    if ai_candidates:
        valid_categories = sorted(
            [str(c).strip() for c in category_item_counts if str(c).strip()],
            key=category_sort_key,
        )
        ai_batch = ai_candidates[:max_items]

        prepared = []
        for item in ai_batch:
            row = item.get("row")
            if row is None:
                skipped += 1
                continue
            name = str(item.get("name", "")).strip()
            current_category = str(item.get("current_category", "")).strip()
            local_target = str(item.get("local_target", "")).strip()
            local_confidence = float(item.get("local_confidence", 0.0) or 0.0)

            row_keys = build_item_category_keys(row)
            if any(str(overrides.get(k, "")).strip() for k in row_keys):
                skipped += 1
                continue

            item_key = build_item_category_key(row)
            if not item_key:
                skipped += 1
                continue

            local_hint = (
                f"local_target={local_target}; local_confidence={round(local_confidence, 3)}; "
                f"current_category={current_category}"
            )
            prepared.append({
                "item": item,
                "row": row,
                "name": name,
                "item_key": item_key,
                "current_category": current_category,
                "local_hint": local_hint,
                "valid_categories": valid_categories,
            })

        ai_checked += len(prepared)
        if not openai_api_key and prepared:
            ai_unavailable += len(prepared)

        if prepared:
            workers = max(1, min(int(max_workers), len(prepared)))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_ask_autosort_ai, predict_category, entry) for entry in prepared]
                for fut in as_completed(futs):
                    entry, ai_category, ai_confidence, ai_reason = fut.result()
                    item = entry["item"]
                    row = entry["row"]
                    item_key = entry["item_key"]
                    name = entry["name"]
                    current_category = entry["current_category"]

                    if not ai_category or ai_confidence < max(0.56, min_confidence):
                        skipped += 1
                        continue
                    if ai_category == current_category:
                        skipped += 1
                        continue

                    existing = proposals.get(item_key)
                    if existing and str(existing.get("target_category", "")).strip() != ai_category:
                        conflict_keys.add(item_key)
                        continue
                    if existing:
                        continue

                    proposals[item_key] = {
                        "item_key": item_key,
                        "onliner_id": str(item.get("oid", "")).strip(),
                        "name": name,
                        "supplier": str(row.get("Поставщик", "")).strip(),
                        "current_category": current_category,
                        "target_category": ai_category,
                        "catalog_category": "",
                        "source": f"AI classifier ({ai_reason})",
                        "confidence": round(float(ai_confidence), 3),
                    }
                    ai_suggested += 1

    for key in list(conflict_keys):
        proposals.pop(key, None)

    items = _autosort_proposal_items(
        df,
        proposals,
        build_item_category_keys=build_item_category_keys,
        category_sort_key=category_sort_key,
    )
    return {
        "items": items,
        "checked": int(checked),
        "skipped": int(skipped + len(conflict_keys)),
        "ai_checked": int(ai_checked),
        "ai_suggested": int(ai_suggested),
        "ai_unavailable": int(ai_unavailable),
    }


def apply_autosort_items(
    df,
    items,
    *,
    overrides,
    build_item_category_keys,
    row_category,
):
    if not isinstance(items, list) or not items:
        return {"status": "error", "message": "Нет выбранных позиций"}, df, overrides

    target_by_key = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_key = str(item.get("item_key", "")).strip()
        target_category = str(item.get("target_category", "")).strip()
        if item_key and target_category:
            target_by_key[item_key] = target_category
    if not target_by_key:
        return {"status": "error", "message": "Нет корректных данных для применения"}, df, overrides

    for item_key, target_category in target_by_key.items():
        overrides[item_key] = target_category

    updated_rows = 0
    target_key_set = set(target_by_key.keys())
    for i, row in df.iterrows():
        row_keys = set(build_item_category_keys(row))
        matched = [target_by_key[k] for k in row_keys if k in target_key_set]
        if not matched:
            continue
        target_category = matched[0]
        if len(matched) > 1:
            target_category = sorted(matched)[0]
        current_category = str(df.at[i, "Категория"]).strip() if "Категория" in df.columns else row_category(row, overrides)
        if current_category != target_category:
            df.at[i, "Категория"] = target_category
            updated_rows += 1
        for row_key in row_keys:
            overrides[row_key] = target_category

    return {
        "status": "ok",
        "updated_keys": int(len(target_by_key)),
        "updated_rows": int(updated_rows),
    }, df, overrides


def _build_local_category_model(df, overrides, *, name_tokens, row_category):
    category_token_counts = {}
    category_item_counts = {}
    for _, row in df.iterrows():
        category = row_category(row, overrides)
        if not category:
            continue
        tokens = set(name_tokens(row.get("Название", "")))
        if not tokens:
            continue
        bucket = category_token_counts.setdefault(category, {})
        for token in tokens:
            bucket[token] = int(bucket.get(token, 0)) + 1
        category_item_counts[category] = int(category_item_counts.get(category, 0)) + 1
    return category_token_counts, category_item_counts


def _token_category_document_frequency(category_token_counts):
    token_category_df = {}
    for token_map in category_token_counts.values():
        for token in token_map.keys():
            token_category_df[token] = int(token_category_df.get(token, 0)) + 1
    return token_category_df


def _predict_local_category(
    name,
    category_token_counts,
    category_item_counts,
    token_category_df,
    *,
    name_tokens,
):
    tokens = set(name_tokens(name))
    if not tokens:
        return "", 0.0

    best_cat = ""
    best_score = 0.0
    second_score = 0.0
    total_cats = max(1, len(category_token_counts))

    for category, token_map in category_token_counts.items():
        category_size = int(category_item_counts.get(category, 0))
        if category_size < 2:
            continue

        raw = 0.0
        hit = 0
        for token in tokens:
            count = int(token_map.get(token, 0))
            if count <= 0:
                continue
            hit += 1
            idf = math.log1p((1.0 + total_cats) / (1.0 + int(token_category_df.get(token, 0))))
            raw += (count / max(1.0, float(category_size))) * (1.0 + float(idf))

        if hit == 0:
            continue

        coverage = hit / max(1.0, float(len(tokens)))
        score = (0.72 * raw) + (0.28 * coverage)

        if score > best_score:
            second_score = best_score
            best_score = score
            best_cat = category
        elif score > second_score:
            second_score = score

    if not best_cat:
        return "", 0.0

    gap = max(0.0, best_score - second_score)
    confidence = min(0.99, (best_score / (best_score + 0.8)) * 0.82 + min(0.17, gap))
    return best_cat, round(float(confidence), 3)


def _ask_autosort_ai(predict_category, entry):
    ai_category, ai_confidence, ai_reason = predict_category(
        entry["name"],
        entry.get("valid_categories", None) or [],
        local_hint=entry["local_hint"],
    )
    return entry, ai_category, ai_confidence, ai_reason


def _autosort_proposal_items(df, proposals, *, build_item_category_keys, category_sort_key):
    conflict_keys = set()
    proposal_keys = set(proposals.keys())
    affected_rows = dict.fromkeys(proposal_keys, 0)
    if proposal_keys:
        for _, row in df.iterrows():
            row_keys = set(build_item_category_keys(row))
            for key in proposal_keys.intersection(row_keys):
                affected_rows[key] += 1

    items = []
    for item_key, rec in proposals.items():
        if item_key in conflict_keys:
            continue
        out = dict(rec)
        out["affected_rows"] = int(affected_rows.get(item_key, 1) or 1)
        items.append(out)
    items.sort(key=lambda x: (
        category_sort_key(x.get("target_category", "")),
        category_sort_key(x.get("current_category", "")),
        str(x.get("name", "")).lower(),
    ))
    return items
