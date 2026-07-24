"""Category-specific review matching for printer."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.services.review_matching.case import case_code_match


def printer_mfp_norm_article(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def looks_like_printer_or_mfp_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    return bool(re.search(r"\bпринтер\b|\bпринтеры\b|\bмфу\b|\bmfp\b", low, flags=re.IGNORECASE))


def printer_mfp_catalog_category_ok(raw_name, infer_category=None, normalize_catalog_category_name=None):
    raw_name = str(raw_name or "").strip()
    if not raw_name:
        return False
    low = raw_name.lower()
    if re.search(r"\bпринтер\b|\bпринтеры\b|\bмфу\b|\bmfp\b|\bmultifunction\b", low, flags=re.IGNORECASE):
        return True
    if not infer_category or not normalize_catalog_category_name:
        return False
    try:
        category = normalize_catalog_category_name(infer_category(raw_name))
    except Exception:
        category = ""
    return category == "Принтер и МФУ"


def printer_mfp_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_printer_mfp_key()
    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("canon", r"\bcanon\b"),
        ("pantum", r"\bpantum\b"),
        ("hp", r"(?:^|[^a-z0-9])hp(?=$|[^a-z0-9])"),
        ("epson", r"\bepson\b"),
        ("brother", r"\bbrother\b"),
        ("xerox", r"\bxerox\b"),
        ("kyocera", r"\bkyocera\b"),
        ("ricoh", r"\bricoh\b"),
        ("samsung", r"\bsamsung\b"),
        ("lexmark", r"\blexmark\b"),
        ("oki", r"\boki\b"),
        ("sharp", r"\bsharp\b"),
        ("konica", r"\bkonica\b"),
        ("develop", r"\bdevelop\b"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    work = re.sub(r"^\s*(?:принтер|мфу)\s+", "", raw, flags=re.IGNORECASE).strip()
    if brand:
        work = re.sub(rf"^.*?\b{re.escape(brand)}\b\s*", "", work, count=1, flags=re.IGNORECASE).strip()

    head = work.split("(", 1)[0].strip()
    head = re.split(r",\s*(?:лазерный|струйный|цветн|черно|формат)", head, 1, flags=re.IGNORECASE)[0].strip()
    model_display = head[:160] if head else ""
    model_compact = re.sub(r"[^a-z0-9]+", "", head.lower())
    article = _extract_printer_mfp_article(raw)

    return {
        "brand": brand,
        "article": article,
        "model_compact": model_compact,
        "model_display": model_display,
    }


def empty_printer_mfp_key():
    return {"brand": "", "article": "", "model_compact": "", "model_display": ""}


def find_printer_review_candidates(
    product_name,
    top_n=5,
    db_connection=None,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    infer_category=None,
    normalize_catalog_category_name=None,
):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = printer_mfp_brand_model_key(name)
    local_article = str(local.get("article", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_model = str(local.get("model_compact", "") or "").strip()
    if not local_brand and not local_article and len(local_model) < 5:
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = _fetch_printer_seed_rows(conn, local_article, local_brand, local_model)
            seed_best = {}
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid:
                    continue
                if not printer_mfp_catalog_category_ok(raw_name, infer_category, normalize_catalog_category_name):
                    continue
                prev = seed_best.get(oid)
                if prev is None:
                    seed_best[oid] = (raw_name, url, True)
                    continue
                prev_name, _prev_url, _prev_ok = prev
                if len(str(raw_name or "")) > len(str(prev_name or "")):
                    seed_best[oid] = (raw_name, url, True)
            for oid, (raw_name, url, _category_ok) in seed_best.items():
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "printer_db_seed"})
    except Exception:
        pass

    if db_find_top_candidates:
        for candidate in db_find_top_candidates(name, top_n=25, min_score=0.10, allow_b2b=False):
            pool.append(candidate)
    if db_find_exact_id_for_name:
        exact = db_find_exact_id_for_name(name)
        if exact:
            pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for candidate in pool:
        classified = _classify_printer_candidate(
            candidate,
            seen,
            local_article,
            local_brand,
            local_model,
            infer_category,
            normalize_catalog_category_name,
        )
        if not classified:
            continue
        seen.add(classified["id"])
        items.append(classified)

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    if local_article:
        exact_items = [
            item for item in items if case_code_match(local_article, str(item.get("code", "") or "").strip())
        ]
        if exact_items:
            items = exact_items
    return items[: max(1, int(top_n))]


def _fetch_printer_seed_rows(conn, local_article, local_brand, local_model):
    rows = []
    if local_article:
        rows.extend(
            conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                "LIMIT 180",
                (f"%{local_article}%",),
            ).fetchall()
        )
    if local_brand and len(rows) < 90:
        rows.extend(
            conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE lower(ni.raw_name) LIKE ? "
                "LIMIT 220",
                (f"%{local_brand.lower()}%",),
            ).fetchall()
        )
    if local_model and len(local_model) >= 6 and len(rows) < 140:
        rows.extend(
            conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                "LIMIT 180",
                (f"%{local_model}%",),
            ).fetchall()
        )
    return rows


def _classify_printer_candidate(
    candidate,
    seen,
    local_article,
    local_brand,
    local_model,
    infer_category,
    normalize_catalog_category_name,
):
    if not isinstance(candidate, dict):
        return None
    cid = normalize_onliner_id(candidate.get("id", ""))
    candidate_name = str(candidate.get("name", "") or "").strip()
    if not cid or not candidate_name or cid in seen:
        return None
    if not printer_mfp_catalog_category_ok(candidate_name, infer_category, normalize_catalog_category_name):
        return None

    candidate_local = printer_mfp_brand_model_key(candidate_name)
    candidate_article = str(candidate_local.get("article", "") or "").strip()
    candidate_model = str(candidate_local.get("model_compact", "") or "").strip()
    candidate_brand = str(candidate_local.get("brand", "") or "").strip()
    if local_brand and candidate_brand and local_brand != candidate_brand:
        return None

    match_ok = False
    if local_article:
        if (candidate_article and case_code_match(local_article, candidate_article)) or (
            local_article in printer_mfp_norm_article(candidate_name)
        ):
            match_ok = True
    if not match_ok and local_model and len(local_model) >= 5 and candidate_model:
        if local_model in candidate_model or candidate_model in local_model or local_model == candidate_model:
            match_ok = True
    if not match_ok:
        return None

    score = max(float(candidate.get("score", 0.0) or 0.0), 0.86)
    if local_article and candidate_article and case_code_match(local_article, candidate_article):
        score = 0.999
    elif local_model and candidate_model and (local_model in candidate_model or candidate_model in local_model):
        score = max(score, 0.95)

    return {
        "id": cid,
        "name": candidate_name,
        "url": str(candidate.get("url", "") or "").strip(),
        "score": round(min(0.999, max(0.0, score)), 3),
        "source": str(candidate.get("source", "printer_db")).strip() or "printer_db",
        "code": candidate_article or candidate_model,
    }


def _extract_printer_mfp_article(raw):
    for code_match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{4,40})\)", raw):
        token = str(code_match.group(1) or "").strip()
        if re.match(r"^\d+\s*x\s*\d+", token, flags=re.IGNORECASE):
            continue
        if re.search(r"(?:dpi|мм|стр/мин|lan|wifi)", token, flags=re.IGNORECASE):
            continue
        article = printer_mfp_norm_article(token)
        if len(article) < 6:
            continue
        if not any(ch.isdigit() for ch in article) or not any(ch.isalpha() for ch in article):
            continue
        return article
    return ""
