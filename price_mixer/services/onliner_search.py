import re
import time
from urllib.parse import quote

from price_mixer.services.product_normalization import normalize_onliner_id


def category_path_hints(category_name):
    category = str(category_name or "").strip().lower()
    if category == "процессор":
        return ["/cpu/"]
    if category == "видеокарта":
        return ["/videocard/"]
    if category == "оперативная память":
        return ["/dram/"]
    if category == "материнская плата":
        return ["/motherboard/"]
    if category == "ssd":
        return ["/ssd/"]
    if category == "жесткий диск":
        return ["/hdd/"]
    if category == "блок питания":
        return ["/powersupply/", "/psu/"]
    if category == "корпус":
        return ["/case/"]
    if category == "кулер":
        return ["/cooler/"]
    if category == "монитор":
        return ["/display/"]
    if category == "системный блок":
        return ["/desktop/", "/computer/", "/tgpc/"]
    return []


def search_product_by_name(
    local_name,
    api_get,
    extract_article,
    name_tokens,
    calc_name_match,
):
    name = str(local_name or "").strip()
    if not name:
        return {"id": "", "name": "", "url": "", "score": 0.0, "source": "empty_query"}
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    candidates = []
    article = str(extract_article(name) or "").strip()
    if article:
        candidates.append(article)
    tokens = name_tokens(name)
    if tokens:
        candidates.append(" ".join(tokens[:6]))
    candidates.append(name[:120])

    seen = set()
    queries = []
    for query in candidates:
        query = str(query or "").strip()
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        queries.append(query)

    best = {"id": "", "name": "", "url": "", "score": 0.0, "source": "not_found"}
    for query in queries[:3]:
        try:
            response = api_get(
                f"https://catalog.api.onliner.by/search/products?query={quote(query)}",
                timeout=12,
                headers=headers,
            )
            if not response.ok:
                continue
            products = (response.json() or {}).get("products") or []
            for product in products[:15]:
                pid = normalize_onliner_id(product.get("id", ""))
                product_name = str(product.get("full_name") or product.get("name") or "").strip()
                product_url = str(product.get("html_url") or "").strip()
                if not pid or not product_name:
                    continue
                match = calc_name_match(name, product_name)
                score = float(match.get("score", 0.0) or 0.0)
                if match.get("match"):
                    score = max(score, 0.75)
                if score > float(best.get("score", 0.0)):
                    best = {
                        "id": pid,
                        "name": product_name,
                        "url": product_url,
                        "score": score,
                        "source": "search_name",
                    }
        except Exception:
            continue
        if float(best.get("score", 0.0)) >= 0.78:
            break
    return best


def search_product_by_name_deep(
    local_name,
    category_name="",
    search_by_name=None,
    search_candidates=None,
    fetch_product_info=None,
    load_product_cache=None,
    save_product_cache=None,
    calc_name_match=None,
    article_like_tokens=None,
):
    name = str(local_name or "").strip()
    if not name:
        return {"id": "", "name": "", "url": "", "score": 0.0, "source": "empty_query"}

    best = search_by_name(name)
    best_score = float(best.get("score", 0.0) or 0.0)

    candidates = search_candidates(
        name,
        category_name=category_name,
        query="",
        limit=10,
        max_queries=3,
        timeout_sec=5,
    )
    if not candidates:
        return best

    cache = load_product_cache()
    touched = False
    for candidate in candidates[:4]:
        cid = normalize_onliner_id(candidate.get("id", ""))
        if not cid:
            continue
        info = fetch_product_info(cid, cache=cache, force_refresh=False, use_cache_on_error=True)
        if info.get("source") == "api":
            touched = True
        product_name = str(info.get("name", "") or candidate.get("name", "")).strip()
        product_url = str(info.get("url", "") or candidate.get("url", "")).strip()
        if not product_name:
            continue
        match = calc_name_match(name, product_name)
        score = float(match.get("score", 0.0) or 0.0)
        if match.get("match"):
            score = max(score, 0.80)
        try:
            local_articles = article_like_tokens(name)
            remote_articles = article_like_tokens(product_name)
            if local_articles and remote_articles and local_articles.intersection(remote_articles):
                score = max(score, 0.86)
        except Exception:
            pass
        if score > best_score:
            best_score = score
            best = {
                "id": cid,
                "name": product_name,
                "url": product_url,
                "score": score,
                "source": "search_name_deep",
            }
        if best_score >= 0.86:
            break

    if touched:
        try:
            save_product_cache(cache)
        except Exception:
            pass
    return best


def search_candidates(
    local_name,
    category_name="",
    query="",
    limit=80,
    max_queries=4,
    timeout_sec=6,
    load_settings=None,
    get_category_rules=None,
    coerce_bool=None,
    api_get=None,
    b2b_search_candidates=None,
    extract_article=None,
    name_tokens=None,
    preferred_brand_token=None,
    normalize_compact_name=None,
    priority_model_queries=None,
    tgpc_pc_code_queries=None,
    is_tgpc_pc_name=None,
    extract_tgpc_pc_code=None,
    model_hint_tokens=None,
    paren_chunks=None,
    article_like_tokens=None,
    token_family_match=None,
    strict_candidate_allowed=None,
    calc_name_match=None,
    query_cache=None,
    query_cache_lock=None,
    query_cache_ttl=3600,
    query_cache_version="v1",
    now_fn=time.time,
):
    app_settings = load_settings()
    search_cfg = (app_settings.get("no_id_search") or {})
    name = str(local_name or "").strip()
    text_query = str(query or "").strip()
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    hints = category_path_hints(category_name)
    limit = max(5, min(int(limit or search_cfg.get("max_candidates", 80) or 80), 150))
    max_queries = max(1, min(int(max_queries or search_cfg.get("max_queries", 4) or 4), 8))
    category_rules = get_category_rules(app_settings)
    category_rule = category_rules.get(str(category_name or "").strip(), {}) if isinstance(category_rules, dict) else {}
    require_category_hint = coerce_bool(search_cfg.get("require_category_hint", False), default=False)
    if not name and not text_query:
        return []

    queries = []
    seen_queries = set()

    def add_query(value):
        search_query = str(value or "").strip()
        key = search_query.lower()
        if not search_query or key in seen_queries:
            return
        seen_queries.add(key)
        queries.append(search_query)

    source_text = name or text_query
    if text_query:
        add_query(text_query)
    for tgpc_query in tgpc_pc_code_queries(source_text):
        add_query(tgpc_query)
    if is_tgpc_pc_name(source_text):
        for tgpc_query in tgpc_pc_code_queries(source_text):
            add_query(f"TGPC {tgpc_query}")
            add_query(f"Компьютеры TGPC {tgpc_query}")
    if coerce_bool(search_cfg.get("prefer_paren_model", True), default=True):
        for model_query in priority_model_queries(name):
            add_query(model_query)
    article = str(extract_article(name) or "").strip()
    if coerce_bool(search_cfg.get("prefer_article_tokens", True), default=True):
        add_query(article)
    token_pool = list(name_tokens(name)[:8])
    if not coerce_bool(search_cfg.get("include_brand_token", True), default=True):
        brand = preferred_brand_token(name)
        brand_norm = normalize_compact_name(brand)
        token_pool = [token for token in token_pool if normalize_compact_name(token) != brand_norm]
    token_query = " ".join(token_pool).strip()
    add_query(token_query)
    if isinstance(category_rule, dict):
        add_query(category_rule.get("query_hint", ""))
    if name:
        add_query(name[:130])
    queries = queries[:max(1, int(max_queries or 1))]

    cache_key = f"{query_cache_version}|{str(category_name or '').strip().lower()}|{(text_query or token_query or name[:80]).strip().lower()}|{int(limit)}"
    now_ts = int(now_fn())
    with query_cache_lock:
        cached = query_cache.get(cache_key)
        if isinstance(cached, dict) and now_ts - int(cached.get("ts", 0)) <= query_cache_ttl:
            return list(cached.get("items") or [])[:limit]

    seen_ids = set()
    candidates = []

    def push_candidate(item):
        if not isinstance(item, dict):
            return
        pid = normalize_onliner_id(item.get("id", ""))
        product_name = str(item.get("name", "") or "").strip()
        if not pid or not product_name or pid in seen_ids:
            return
        score = round(float(item.get("score", 0.0) or 0.0), 3)
        if score < 0.34:
            return
        payload = {
            "id": pid,
            "name": product_name,
            "url": str(item.get("url", "") or "").strip(),
            "score": score,
            "source": str(item.get("source", "") or "api"),
            "reason": str(item.get("reason", "") or ""),
        }
        candidates.append(payload)
        seen_ids.add(pid)

    for candidate in b2b_search_candidates(source_text, category_name=category_name, limit=min(limit, 24)):
        push_candidate(candidate)
        if len(candidates) >= limit:
            break

    local_models = model_hint_tokens(source_text)
    local_paren_models = model_hint_tokens(" ".join(paren_chunks(source_text)))
    local_articles = article_like_tokens(source_text)
    local_text = str(source_text).lower()
    local_has_special_edition = _has_special_edition(local_text)
    local_is_tgpc_pc = is_tgpc_pc_name(source_text)
    local_tgpc_code = extract_tgpc_pc_code(source_text) if local_is_tgpc_pc else ""
    for search_query in queries:
        try:
            response = api_get(
                f"https://catalog.api.onliner.by/search/products?query={quote(search_query)}",
                timeout=max(2, int(timeout_sec or 6)),
                headers=headers,
            )
            if not response.ok:
                continue
            products = (response.json() or {}).get("products") or []
        except Exception:
            continue
        for product in products[:40]:
            pid = normalize_onliner_id(product.get("id", ""))
            product_name = str(product.get("full_name") or product.get("name") or "").strip()
            product_url = str(product.get("html_url") or "").strip()
            if not pid or not product_name or pid in seen_ids:
                continue
            allowed, _reason = strict_candidate_allowed(source_text, product_name)
            if not allowed:
                continue
            if require_category_hint and hints and product_url and not any(hint in product_url for hint in hints):
                continue
            match = calc_name_match(source_text, product_name)
            score = float(match.get("score", 0.0) or 0.0)
            candidate_models = model_hint_tokens(product_name)
            candidate_articles = article_like_tokens(product_name)
            paren_hits = token_family_match(local_paren_models, candidate_models)
            if match.get("match"):
                score = max(score, 0.74)
            if paren_hits:
                score = max(score, 0.95)
            if local_articles and candidate_articles and not token_family_match(local_articles, candidate_articles):
                score = min(score, 0.18)
            elif local_models and candidate_models and not token_family_match(local_models, candidate_models):
                score *= 0.62
            candidate_lower = product_name.lower()
            if local_is_tgpc_pc:
                candidate_is_tgpc = "tgpc" in candidate_lower
                candidate_is_pc_url = bool(product_url and any(hint in product_url for hint in ["/desktop/", "/computer/", "/tgpc/"]))
                if not candidate_is_tgpc and not candidate_is_pc_url:
                    continue
                if not candidate_is_tgpc:
                    score *= 0.70
                if not candidate_is_pc_url:
                    score *= 0.80
                if local_tgpc_code:
                    candidate_code = extract_tgpc_pc_code(product_name)
                    if candidate_code and candidate_code != local_tgpc_code:
                        score = min(score, 0.12)
                    elif not candidate_code and local_tgpc_code not in (product_name + product_url):
                        score = min(score, 0.68)
            if isinstance(category_rule, dict):
                must_contain = [str(item).strip().lower() for item in (category_rule.get("must_contain") or []) if str(item).strip()]
                ignore_words = [str(item).strip().lower() for item in (category_rule.get("ignore_words") or []) if str(item).strip()]
                if must_contain and not any(item in candidate_lower for item in must_contain):
                    score *= 0.55
                if ignore_words and any(item in candidate_lower for item in ignore_words):
                    score *= 0.35
            candidate_has_special_edition = _has_special_edition(candidate_lower)
            candidate_has_color = _has_parenthesized_color(candidate_lower)
            if not local_has_special_edition and candidate_has_special_edition:
                score *= 0.78
            elif not local_has_special_edition and candidate_has_color:
                score = max(score, score + 0.03)
            if hints and product_url and not any(hint in product_url for hint in hints):
                score *= 0.78
            if score < 0.34:
                continue
            push_candidate({
                "id": pid,
                "name": product_name,
                "url": product_url,
                "score": round(float(score), 3),
                "source": "api",
                "reason": str(match.get("reason", "") or ""),
            })
        if len(candidates) >= limit:
            break

    candidates.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
    top_score = float(candidates[0].get("score", 0.0) or 0.0) if candidates else 0.0
    if top_score >= 0.90:
        min_score = 0.52
    elif top_score >= 0.78:
        min_score = 0.46
    else:
        min_score = 0.40
    final_items = [candidate for candidate in candidates if float(candidate.get("score", 0.0) or 0.0) >= min_score][:limit]
    with query_cache_lock:
        query_cache[cache_key] = {"ts": now_ts, "items": final_items}
        if len(query_cache) > 400:
            keys = list(query_cache.keys())[:120]
            for key in keys:
                query_cache.pop(key, None)
    return final_items


def _has_special_edition(text):
    return bool(_SPECIAL_EDITION_RE.search(str(text or "")))


def _has_parenthesized_color(text):
    return bool(_PAREN_COLOR_RE.search(str(text or "")))

_SPECIAL_EDITION_RE = re.compile(r"\b(xbox|playstation|usb)\b", re.IGNORECASE)
_PAREN_COLOR_RE = re.compile(
    r"\((черный|чёрный|белый|зеленый|зелёный|розовый|синий|красный|yellow|pink|white|black|green|blue)\)",
    re.IGNORECASE,
)
