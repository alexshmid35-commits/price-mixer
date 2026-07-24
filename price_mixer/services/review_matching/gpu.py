"""Category-specific review matching for gpu."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id


def gpu_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_gpu_key()
    low = raw.lower()
    gpu_brand = (
        "nvidia"
        if "geforce" in low or "rtx" in low or "gtx" in low
        else ("amd" if "radeon" in low or re.search(r"(?:^|[^a-z0-9])rx\s*\d{3,4}", low) else "")
    )
    vendor = ""
    vendor_patterns = [
        ("gigabyte", r"(?:^|[^a-z0-9])gigabyte(?=$|[^a-z0-9])"),
        ("sapphire", r"(?:^|[^a-z0-9])sapphire(?=$|[^a-z0-9])"),
        ("asus", r"(?:^|[^a-z0-9])asus(?=$|[^a-z0-9])"),
        ("msi", r"(?:^|[^a-z0-9])msi(?=$|[^a-z0-9])"),
        ("palit", r"(?:^|[^a-z0-9])palit(?=$|[^a-z0-9])"),
        ("gainward", r"(?:^|[^a-z0-9])gainward(?=$|[^a-z0-9])"),
        ("zotac", r"(?:^|[^a-z0-9])zotac(?=$|[^a-z0-9])"),
        ("inno3d", r"(?:^|[^a-z0-9])inno3d(?=$|[^a-z0-9])"),
        ("ocpc", r"(?:^|[^a-z0-9])ocpc(?=$|[^a-z0-9])"),
        ("colorful", r"(?:^|[^a-z0-9])colorful(?=$|[^a-z0-9])"),
    ]
    for value, pattern in vendor_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            vendor = value
            break

    gpu_model = ""
    for pattern in [
        r"(rtx\s*\d{4}(?:\s*ti)?)",
        r"(gtx\s*\d{3,4}(?:\s*ti)?)",
        r"(gt\s*\d{3,4})",
        r"(rx\s*\d{3,4}\s*xt?)",
        r"(rx\s*\d{3,4})",
    ]:
        match = re.search(pattern, low, flags=re.IGNORECASE)
        if match and match.group(1):
            gpu_model = re.sub(r"[^a-z0-9]+", "", match.group(1).lower())
            break

    sku = ""
    sku_match = re.search(r"\(([A-Za-z0-9+\- ]{6,40})\)", raw)
    if sku_match and sku_match.group(1):
        sku = re.sub(r"[^a-z0-9]+", "", sku_match.group(1).lower())
    if not sku:
        for pattern in [
            r"(gv-[a-z0-9+\- ]{6,40})",
            r"(ne[a-z0-9+\-]{8,40})",
            r"(zt-[a-z0-9+\-]{6,40})",
            r"(ocvn[a-z0-9+\-]{6,40})",
            r"(113\d{2}-\d{2}-\d{2}g)",
        ]:
            inline_sku = re.search(pattern, low, flags=re.IGNORECASE)
            if inline_sku and inline_sku.group(1):
                sku = re.sub(r"[^a-z0-9]+", "", inline_sku.group(1).lower())
                break

    memory_gb = ""
    memory_match = re.search(r"(\d{1,2})\s*gb\b", low, flags=re.IGNORECASE)
    if memory_match and memory_match.group(1):
        memory_gb = memory_match.group(1)

    white = bool(re.search(r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|\bбел(?:ый|ая|ое|ые)?\b", low, flags=re.IGNORECASE))
    oc = bool(re.search(r"(?:^|[^a-z0-9])oc(?=$|[^a-z0-9])", low, flags=re.IGNORECASE))

    series = ""
    series_tokens = [
        ("aoruselite", r"aorus\s*elite"),
        ("aero", r"(?:^|[^a-z0-9])aero(?=$|[^a-z0-9])"),
        ("eaglemax", r"eagle\s*max"),
        ("eagleocice", r"eagle\s*oc\s*ice"),
        ("eagleoc", r"eagle\s*oc"),
        ("eagleice", r"eagle\s*ice"),
        ("eagle", r"(?:^|[^a-z0-9])eagle(?=$|[^a-z0-9])"),
        ("windforcemax", r"windforce\s*max"),
        ("windforceoc", r"windforce\s*oc"),
        ("windforce", r"windforce"),
        ("gamingocice", r"gaming\s*oc\s*ice"),
        ("gamingoc", r"gaming\s*oc"),
        ("gaming", r"(?:^|[^a-z0-9])gaming(?=$|[^a-z0-9])"),
        ("pulseoc", r"pulse\s*oc"),
        ("pulse", r"(?:^|[^a-z0-9])pulse(?=$|[^a-z0-9])"),
        ("pure", r"(?:^|[^a-z0-9])pure(?=$|[^a-z0-9])"),
        ("nitro", r"nitro\+?"),
        ("dualoc", r"dual\s*oc"),
        ("dual", r"(?:^|[^a-z0-9])dual(?=$|[^a-z0-9])"),
        ("stormxoc", r"stormx\s*oc"),
        ("stormx", r"(?:^|[^a-z0-9])stormx(?=$|[^a-z0-9])"),
        ("infinity3oc", r"infinity\s*3\s*oc"),
        ("infinity3", r"infinity\s*3"),
        ("infinity2oc", r"infinity\s*2\s*oc"),
        ("infinity2", r"infinity\s*2"),
        ("gamingprosoc", r"gamingpro-s\s*oc|gaming\s*pro-s\s*oc"),
        ("gamingpros", r"gamingpro-s|gaming\s*pro-s"),
        ("gamingprooc", r"gamingpro\s*oc|gaming\s*pro\s*oc"),
        ("gamingpro", r"gamingpro|gaming\s*pro"),
        ("zoneedition", r"zone\s*edition"),
        ("ventus", r"(?:^|[^a-z0-9])ventus(?=$|[^a-z0-9])"),
    ]
    for key, pattern in series_tokens:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    return {
        "gpu_brand": gpu_brand,
        "vendor": vendor,
        "gpu_model": gpu_model,
        "series": series,
        "sku": sku,
        "memory_gb": memory_gb,
        "white": white,
        "oc": oc,
    }


def empty_gpu_key():
    return {
        "gpu_brand": "",
        "vendor": "",
        "gpu_model": "",
        "series": "",
        "sku": "",
        "memory_gb": "",
        "white": False,
        "oc": False,
    }


def find_gpu_review_candidates(
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
    local = gpu_brand_model_key(name)
    if not local.get("vendor") or not local.get("gpu_model"):
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = []
            model_query = local.get("gpu_model", "")
            vendor_query = local.get("vendor", "")
            sku_query = str(local.get("sku", "") or "").strip()
            if vendor_query and model_query:
                spaced_model = re.sub(r"([a-z]+)(\d)", r"\1 \2", model_query)
                if sku_query:
                    rows.extend(
                        conn.execute(
                            "SELECT ni.onliner_id, ni.raw_name, oc.url "
                            "FROM name_index ni "
                            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                            "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '+', ''), '(', '') LIKE ? "
                            "LIMIT 80",
                            (f"%{sku_query.replace('+', '')}%",),
                        ).fetchall()
                    )
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                        "LIMIT 160",
                        (f"%{vendor_query.lower()}%", f"%{spaced_model.lower()}%"),
                    ).fetchall()
                )
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '+', '') LIKE ? "
                        "LIMIT 160",
                        (f"%{model_query.replace('+', '')}%",),
                    ).fetchall()
                )
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "gpu_db_exact"})
    except Exception:
        pass

    for candidate in db_find_top_candidates(name, top_n=18, min_score=0.10, allow_b2b=False):
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
        if normalize_catalog_category_name(infer_category(candidate_name)) != "Видеокарта":
            continue
        candidate_gpu = gpu_brand_model_key(candidate_name)
        if candidate_gpu.get("vendor") != local.get("vendor"):
            continue
        if candidate_gpu.get("gpu_brand") != local.get("gpu_brand"):
            continue
        if candidate_gpu.get("gpu_model") != local.get("gpu_model"):
            continue

        score = _score_gpu_candidate(candidate, local, candidate_gpu)
        if score is None:
            continue

        seen.add(cid)
        items.append(
            {
                "id": cid,
                "name": candidate_name,
                "url": str(candidate.get("url", "") or "").strip(),
                "score": round(min(0.999, max(0.0, score)), 3),
                "source": str(candidate.get("source", "gpu_db")).strip() or "gpu_db",
                "series": candidate_gpu.get("series", ""),
                "sku": candidate_gpu.get("sku", ""),
                "memory_gb": candidate_gpu.get("memory_gb", ""),
                "white": candidate_gpu.get("white"),
            }
        )

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    return items[: max(1, int(top_n))]


def _score_gpu_candidate(candidate, local, candidate_gpu):
    score = max(float(candidate.get("score", 0.0) or 0.0), 0.90)
    local_sku = str(local.get("sku", "") or "").strip()
    candidate_sku = str(candidate_gpu.get("sku", "") or "").strip()
    if local_sku:
        if candidate_sku == local_sku:
            score = 1.0
        elif candidate_sku:
            if local.get("vendor") == "gigabyte":
                return None
            score -= 0.14
    if local.get("series") and candidate_gpu.get("series") == local.get("series"):
        score += 0.05
    elif local.get("series") and candidate_gpu.get("series") and candidate_gpu.get("series") != local.get("series"):
        score -= 0.10
    if local.get("memory_gb") and candidate_gpu.get("memory_gb") == local.get("memory_gb"):
        score += 0.04
    elif (
        local.get("memory_gb")
        and candidate_gpu.get("memory_gb")
        and candidate_gpu.get("memory_gb") != local.get("memory_gb")
    ):
        score -= 0.12
    if local.get("white") != candidate_gpu.get("white"):
        score -= 0.06
    if local.get("oc") and candidate_gpu.get("oc"):
        score += 0.015
    elif local.get("oc") != candidate_gpu.get("oc"):
        score -= 0.04
    if local.get("sku") and candidate_gpu.get("sku") == local.get("sku"):
        score += 0.06
    elif local.get("sku") and candidate_gpu.get("sku") and local.get("sku") != candidate_gpu.get("sku"):
        score -= 0.08
    return score
