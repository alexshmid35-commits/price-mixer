"""Category-specific review matching for ssd."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id


def ssd_brand_model_key(
    text,
    normalize_compact_name=None,
    raw_paren_article_tokens=None,
    is_spec_code=None,
):
    raw = str(text or "").strip()
    if not raw:
        return empty_ssd_key()
    normalize_compact_name = normalize_compact_name or _ssd_norm
    raw_paren_article_tokens = raw_paren_article_tokens or (lambda value: [])
    is_spec_code = is_spec_code or (lambda value: False)

    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("adata", r"(?:^|[^a-z0-9])a-?data|(?:^|[^a-z0-9])adata|(?:^|[^a-z0-9])xpg(?=$|[^a-z0-9])"),
        ("team", r"(?:^|[^a-z0-9])team(?=$|[^a-z0-9])"),
        ("netac", r"(?:^|[^a-z0-9])netac(?=$|[^a-z0-9])"),
        ("samsung", r"(?:^|[^a-z0-9])samsung(?=$|[^a-z0-9])"),
        ("kingston", r"(?:^|[^a-z0-9])kingston(?=$|[^a-z0-9])"),
        ("crucial", r"(?:^|[^a-z0-9])crucial(?=$|[^a-z0-9])"),
        ("wd", r"(?:^|[^a-z0-9])wd(?:$|[^a-z0-9])|western\s*digital"),
        ("transcend", r"(?:^|[^a-z0-9])transcend(?=$|[^a-z0-9])"),
        ("patriot", r"(?:^|[^a-z0-9])patriot(?=$|[^a-z0-9])"),
        ("hp", r"(?:^|[^a-z0-9])hp(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    code = _extract_ssd_code(raw, raw_paren_article_tokens, is_spec_code)

    model = ""
    for pattern in [
        r"\b(sa\d{3,4})\b",
        r"\b(su\d{3,4})\b",
        r"\b(n\d{3,4}[a-z]?)\b",
        r"\b(nv\d{3,5}(?:-q)?)\b",
        r"\b(sd\d{2,4})\b",
        r"\b(bx\d{3,4})\b",
        r"\b(a\d{3,4})\b",
        r"\b(skc\d{3,5})\b",
        r"\b(snv\d+[a-z0-9]*)\b",
        r"\b(n\d{3,4}[a-z]?)\b",
        r"\b(91\d{2}\s*pro\s*series)\b",
        r"\b(mars\s*980\s*blade)\b",
        r"\b(mars\s*980\s*pro)\b",
        r"\b(fury\s*renegade\s*g5)\b",
        r"\b(cardea\s*z\d{3})\b",
        r"\b(g\d{2}\s*pro)\b",
        r"\b(nv\d{3,5})\b",
        r"\b(p\d{1,4})\b",
        r"\b(sd\d{2,4})\b",
        r"\b(z\s*slim)\b",
    ]:
        match = re.search(pattern, low, flags=re.IGNORECASE)
        if match and match.group(1):
            model = normalize_compact_name(match.group(1))
            break

    capacity = ""
    capacity_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(tb|gb|тб|гб)\b", low, flags=re.IGNORECASE)
    if capacity_match and capacity_match.group(1) and capacity_match.group(2):
        unit = capacity_match.group(2).lower()
        if unit == "тб":
            unit = "tb"
        elif unit == "гб":
            unit = "gb"
        capacity = f"{capacity_match.group(1)}{unit}"

    external = bool(re.search(r"внешн|portable|usb", low, flags=re.IGNORECASE))
    return {"brand": brand, "code": code, "model": model, "capacity": capacity, "external": external}


def empty_ssd_key():
    return {"brand": "", "code": "", "model": "", "capacity": "", "external": False}


def find_ssd_review_candidates(
    product_name,
    top_n=5,
    db_connection=None,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    normalize_compact_name=None,
    raw_paren_article_tokens=None,
    is_spec_code=None,
):
    name = str(product_name or "").strip()
    if not name:
        return []
    key_kwargs = {
        "normalize_compact_name": normalize_compact_name,
        "raw_paren_article_tokens": raw_paren_article_tokens,
        "is_spec_code": is_spec_code,
    }
    local = ssd_brand_model_key(name, **key_kwargs)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_model = str(local.get("model", "") or "").strip()
    local_capacity = str(local.get("capacity", "") or "").strip()
    local_external = bool(local.get("external"))
    if not local_code and not local_brand:
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = []
            if local_code:
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                        "LIMIT 150",
                        (f"%{local_code}%",),
                    ).fetchall()
                )
            if local_brand and len(rows) < 80:
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
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "ssd_db_seed"})
    except Exception:
        pass

    if db_find_top_candidates:
        for candidate in db_find_top_candidates(name, top_n=25, min_score=0.10, allow_b2b=False):
            pool.append(candidate)

    if db_find_exact_id_for_name:
        exact = db_find_exact_id_for_name(name)
        if exact:
            pool = [exact] + list(pool or [])

    exact_items = []
    soft_items = []
    seen = set()
    for candidate in pool:
        classified = _classify_ssd_candidate(
            candidate,
            seen,
            local_brand,
            local_code,
            local_model,
            local_capacity,
            local_external,
            key_kwargs,
        )
        if not classified:
            continue
        seen.add(classified["id"])
        if classified.pop("_exact_code", False):
            exact_items.append(classified)
        else:
            soft_items.append(classified)

    exact_items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    soft_items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    items = exact_items if exact_items else soft_items
    return items[: max(1, int(top_n))]


def _classify_ssd_candidate(
    candidate,
    seen,
    local_brand,
    local_code,
    local_model,
    local_capacity,
    local_external,
    key_kwargs,
):
    if not isinstance(candidate, dict):
        return None
    cid = normalize_onliner_id(candidate.get("id", ""))
    candidate_name = str(candidate.get("name", "") or "").strip()
    if not cid or not candidate_name or cid in seen:
        return None
    if "ssd" not in candidate_name.lower():
        return None

    candidate_ssd = ssd_brand_model_key(candidate_name, **key_kwargs)
    candidate_code = str(candidate_ssd.get("code", "") or "").strip()
    candidate_brand = str(candidate_ssd.get("brand", "") or "").strip()
    candidate_model = str(candidate_ssd.get("model", "") or "").strip()
    candidate_capacity = str(candidate_ssd.get("capacity", "") or "").strip()
    candidate_external = bool(candidate_ssd.get("external"))

    if local_brand and candidate_brand and candidate_brand != local_brand:
        return None

    exact_code = bool(local_code and candidate_code and candidate_code == local_code)
    model_match = bool(local_model and candidate_model and candidate_model == local_model)
    capacity_match = bool(local_capacity and candidate_capacity and candidate_capacity == local_capacity)
    external_mismatch = local_external != candidate_external

    if exact_code:
        score = 1.0
        if model_match:
            score += 0.01
        if capacity_match:
            score += 0.01
    else:
        if local_code and candidate_code and candidate_code != local_code:
            return None
        if not (model_match or capacity_match):
            return None
        if local_code and not candidate_code and not (model_match and capacity_match):
            return None
        score = max(float(candidate.get("score", 0.0) or 0.0), 0.82)
        if model_match:
            score += 0.08
        if capacity_match:
            score += 0.07
        if local_code and not candidate_code:
            score -= 0.05
    if external_mismatch:
        score -= 0.08

    return {
        "id": cid,
        "name": candidate_name,
        "url": str(candidate.get("url", "") or "").strip(),
        "score": round(min(0.999, max(0.0, score)), 3),
        "source": str(candidate.get("source", "ssd_db")).strip()
        or ("ssd_db_code_exact" if exact_code else "ssd_db_fallback"),
        "code": candidate_code,
        "model": candidate_model,
        "capacity": candidate_capacity,
        "_exact_code": exact_code,
    }


def _ssd_norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_strong_ssd_code(value):
    norm = _ssd_norm(value)
    if len(norm) < 8:
        return False
    if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
        return False
    blocked = {
        "ssd",
        "nvme",
        "m2",
        "pcie",
        "sata",
        "usb",
        "typec",
        "mbps",
        "tb",
        "gb",
        "rtl",
        "oem",
        "bulk",
        "series",
    }
    return norm not in blocked


def _extract_ssd_code(raw, raw_paren_article_tokens, is_spec_code):
    for code_match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{4,80})\)", raw):
        token = str(code_match.group(1) or "").strip()
        if _is_strong_ssd_code(token):
            return _ssd_norm(token)

    for token in raw_paren_article_tokens(raw):
        if _is_strong_ssd_code(token):
            return _ssd_norm(token)

    for token in re.findall(r"\b([A-Za-z0-9][A-Za-z0-9.\-/]{6,40})\b", raw):
        if is_spec_code(_ssd_norm(token).upper()):
            continue
        if _is_strong_ssd_code(token):
            return _ssd_norm(token)
    return ""
