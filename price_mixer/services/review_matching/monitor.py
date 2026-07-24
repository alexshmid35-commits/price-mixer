"""Category-specific review matching for monitor."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id


def monitor_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_monitor_key()
    cleaned = raw.replace("″", '"').replace("“", '"').replace("”", '"').strip()
    low = cleaned.lower()
    size = ""
    size_match = re.match(r'^\s*(\d{2}(?:\.\d)?)\s*"', cleaned)
    if size_match and size_match.group(1):
        size = size_match.group(1)

    brand = ""
    brand_patterns = [
        ("elsa", r"(?:^|[^a-z0-9])elsa(?=$|[^a-z0-9])"),
        ("lg", r"(?:^|[^a-z0-9])lg(?=$|[^a-z0-9])"),
        ("xiaomi", r"(?:^|[^a-z0-9])xiaomi(?=$|[^a-z0-9])"),
        ("asrock", r"(?:^|[^a-z0-9])asrock(?=$|[^a-z0-9])"),
        ("gigabyte", r"(?:^|[^a-z0-9])gigabyte(?=$|[^a-z0-9])"),
        ("msi", r"(?:^|[^a-z0-9])msi(?=$|[^a-z0-9])"),
        ("asus", r"(?:^|[^a-z0-9])asus(?=$|[^a-z0-9])"),
        ("aoc", r"(?:^|[^a-z0-9])aoc(?=$|[^a-z0-9])"),
        ("acer", r"(?:^|[^a-z0-9])acer(?=$|[^a-z0-9])"),
        ("benq", r"(?:^|[^a-z0-9])benq(?=$|[^a-z0-9])"),
        ("philips", r"(?:^|[^a-z0-9])philips(?=$|[^a-z0-9])"),
        ("viewsonic", r"(?:^|[^a-z0-9])viewsonic(?=$|[^a-z0-9])"),
        ("samsung", r"(?:^|[^a-z0-9])samsung(?=$|[^a-z0-9])"),
        ("dell", r"(?:^|[^a-z0-9])dell(?=$|[^a-z0-9])"),
        ("hp", r"(?:^|[^a-z0-9])hp(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    after_brand = cleaned
    after_brand = re.sub(r"^\s*(игровой\s+)?монитор\s+", "", after_brand, flags=re.IGNORECASE).strip()
    if size:
        after_brand = re.sub(r'^\s*\d{2}(?:\.\d)?\s*"\s*', "", after_brand, flags=re.IGNORECASE).strip()
    if brand:
        after_brand = re.sub(rf"^\s*{re.escape(brand)}\s+", "", after_brand, flags=re.IGNORECASE).strip()

    resolution = ""
    resolution_match = re.search(r"(\d{3,4}\s*x\s*\d{3,4})", cleaned, flags=re.IGNORECASE)
    if resolution_match and resolution_match.group(1):
        resolution = re.sub(r"\s+", "", resolution_match.group(1).lower())

    hz = ""
    hz_match = re.search(r"(\d{2,3})\s*(?:гц|hz)\b", low, flags=re.IGNORECASE)
    if hz_match and hz_match.group(1):
        hz = hz_match.group(1)

    white = bool(re.search(r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|бел", low, flags=re.IGNORECASE))

    model_text = re.split(r"\s*\(", after_brand, maxsplit=1)[0].strip()
    model_text = re.sub(r"\s+", " ", model_text)
    model = re.sub(r"[^a-z0-9]+", "", model_text.lower())
    code = ""
    for code_match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9\-]{4,40})\)", cleaned):
        token = str(code_match.group(1) or "").strip()
        norm = re.sub(r"[^a-z0-9]+", "", token.lower())
        if len(norm) >= 6 and any(ch.isalpha() for ch in norm) and any(ch.isdigit() for ch in norm):
            code = norm
            break
    if not code:
        inline_code = re.search(r"\b((?:p|ela)\d[A-Za-z0-9\-]{4,32})\b", cleaned, flags=re.IGNORECASE)
        if inline_code and inline_code.group(1):
            code = re.sub(r"[^a-z0-9]+", "", inline_code.group(1).lower())

    return {
        "brand": brand,
        "model": model,
        "model_text": model_text.upper(),
        "code": code,
        "size": size,
        "resolution": resolution,
        "hz": hz,
        "white": white,
    }


def empty_monitor_key():
    return {
        "brand": "",
        "model": "",
        "model_text": "",
        "code": "",
        "size": "",
        "resolution": "",
        "hz": "",
        "white": False,
    }


def find_monitor_review_candidates(
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
    local = monitor_brand_model_key(name)
    local_brand = local.get("brand", "")
    local_model = local.get("model", "")
    local_code = str(local.get("code", "") or "").strip()
    if not local_brand or not local_model:
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = []
            model_text = str(local.get("model_text", "") or "").strip()
            brand_sql = local_brand
            if local_code:
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                        "LIMIT 120",
                        (f"%{local_code}%",),
                    ).fetchall()
                )
            if brand_sql and model_text:
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                        "LIMIT 120",
                        (f"%{brand_sql.lower()}%", f"%{model_text.lower()}%"),
                    ).fetchall()
                )
            compact_model = str(local.get("model", "") or "").strip()
            if compact_model and len(rows) < 20:
                tail = re.sub(r"[^a-z0-9]+", "", model_text.lower())
                model_token = model_text.lower()
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? "
                        "LIMIT 120",
                        (f"%{model_token}%",),
                    ).fetchall()
                )
                if tail and tail != model_token:
                    rows.extend(
                        conn.execute(
                            "SELECT ni.onliner_id, ni.raw_name, oc.url "
                            "FROM name_index ni "
                            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                            "WHERE replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '\"', '') LIKE ? "
                            "LIMIT 120",
                            (f"%{tail}%",),
                        ).fetchall()
                    )
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "mon_db_exact"})
    except Exception:
        pass

    for candidate in db_find_top_candidates(name, top_n=15, min_score=0.10, allow_b2b=False):
        pool.append(candidate)
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for candidate in pool:
        if not isinstance(candidate, dict):
            continue
        cid = normalize_onliner_id(candidate.get("id", ""))
        candidate_name = str(candidate.get("name", "") or "").strip()
        if not cid or not candidate_name or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(candidate_name)) != "Монитор":
            continue
        candidate_monitor = monitor_brand_model_key(candidate_name)
        if candidate_monitor.get("brand") != local_brand:
            continue
        candidate_model = candidate_monitor.get("model", "")
        candidate_code = str(candidate_monitor.get("code", "") or "").strip()
        code_exact = bool(local_code and candidate_code and candidate_code == local_code)
        model_exact = candidate_model == local_model
        model_close = bool(
            candidate_model and local_model and (candidate_model in local_model or local_model in candidate_model)
        )
        if not code_exact and not model_exact and not model_close:
            continue

        score = _score_monitor_candidate(candidate, local, candidate_monitor, code_exact, model_exact, model_close)
        seen.add(cid)
        items.append(
            {
                "id": cid,
                "name": candidate_name,
                "url": str(candidate.get("url", "") or "").strip(),
                "score": round(min(0.999, max(0.0, score)), 3),
                "source": str(candidate.get("source", "mon_db")).strip() or "mon_db",
                "code": candidate_code,
                "size": candidate_monitor.get("size", ""),
                "resolution": candidate_monitor.get("resolution", ""),
                "hz": candidate_monitor.get("hz", ""),
                "white": candidate_monitor.get("white"),
            }
        )

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    return items[: max(1, int(top_n))]


def _score_monitor_candidate(candidate, local, candidate_monitor, code_exact, model_exact, model_close):
    score = max(float(candidate.get("score", 0.0) or 0.0), 0.90)
    if code_exact:
        score = max(score, 0.97)
        score += 0.05
    if model_exact:
        score += 0.07
    elif model_close:
        score += 0.04
    if local.get("size") and candidate_monitor.get("size") == local.get("size"):
        score += 0.03
    elif local.get("size") and candidate_monitor.get("size") and candidate_monitor.get("size") != local.get("size"):
        score -= 0.10
    if local.get("resolution") and candidate_monitor.get("resolution") == local.get("resolution"):
        score += 0.03
    elif (
        local.get("resolution")
        and candidate_monitor.get("resolution")
        and candidate_monitor.get("resolution") != local.get("resolution")
    ):
        score -= 0.10
    if local.get("hz") and candidate_monitor.get("hz") == local.get("hz"):
        score += 0.03
    elif local.get("hz") and candidate_monitor.get("hz"):
        try:
            diff_hz = abs(int(local.get("hz")) - int(candidate_monitor.get("hz")))
        except Exception:
            diff_hz = 999
        score += 0.005 if diff_hz <= 20 else -0.07
    if bool(local.get("white")) != bool(candidate_monitor.get("white")):
        score -= 0.05
    return score
