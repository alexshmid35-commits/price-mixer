"""Category-specific review matching for ram."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id


def ram_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_ram_key()
    low = raw.lower()
    ddr = ""
    ddr_match = re.search(r"\bddr\s*([345]|iii|iv|v)\b", low, flags=re.IGNORECASE)
    if ddr_match and ddr_match.group(1):
        token = str(ddr_match.group(1) or "").lower()
        if token in {"v", "5"}:
            ddr = "ddr5"
        elif token in {"iv", "4"}:
            ddr = "ddr4"
        elif token in {"iii", "3"}:
            ddr = "ddr3"

    brand = ""
    for value, pattern in [
        ("kingston", r"(?:^|[^a-z0-9])kingston(?=$|[^a-z0-9])"),
        ("gskill", r"(?:^|[^a-z0-9])g\.?skill(?=$|[^a-z0-9])"),
        ("netac", r"(?:^|[^a-z0-9])netac(?=$|[^a-z0-9])"),
        ("team", r"(?:^|[^a-z0-9])team(?=$|[^a-z0-9])"),
        ("adata", r"(?:^|[^a-z0-9])a-?data|(?:^|[^a-z0-9])adata|(?:^|[^a-z0-9])xpg(?=$|[^a-z0-9])"),
        ("patriot", r"(?:^|[^a-z0-9])patriot(?=$|[^a-z0-9])"),
        ("corsair", r"(?:^|[^a-z0-9])corsair(?=$|[^a-z0-9])"),
        ("crucial", r"(?:^|[^a-z0-9])crucial(?=$|[^a-z0-9])"),
    ]:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    sku = _extract_ram_sku(raw)

    capacity_gb = ""
    capacity_match = re.search(r"(\d{1,3})\s*(?:g|г)\s*(?:b|б)\b", low, flags=re.IGNORECASE)
    if capacity_match and capacity_match.group(1):
        capacity_gb = capacity_match.group(1)
    if not capacity_gb:
        capacity_match = re.search(r"\b(\d{1,2})\s*[xх]\s*(\d{1,3})\s*(?:g|г)\s*(?:b|б)\b", low, flags=re.IGNORECASE)
        if capacity_match and capacity_match.group(1) and capacity_match.group(2):
            try:
                capacity_gb = str(int(capacity_match.group(1)) * int(capacity_match.group(2)))
            except Exception:
                capacity_gb = ""

    kit_modules = ""
    kit_match = re.search(
        r"kitof\s*(\d+)|kit\s*[xх]\s*(\d+)|(\d+)\s*[xх]\s*\d+\s*(?:g|г)\s*(?:b|б)", low, flags=re.IGNORECASE
    )
    if kit_match:
        for group in kit_match.groups():
            if group:
                kit_modules = group
                break

    mhz = ""
    mhz_match = re.search(r"(\d{4,5})\s*mhz", low, flags=re.IGNORECASE)
    if mhz_match and mhz_match.group(1):
        mhz = mhz_match.group(1)

    cl = ""
    cl_match = re.search(r"\bcl\s*([0-9]{2})\b", low, flags=re.IGNORECASE)
    if cl_match and cl_match.group(1):
        cl = cl_match.group(1)

    series = ""
    for key, pattern in [
        ("furybeastrgb", r"fury\s*beast\s*rgb"),
        ("furybeast", r"fury\s*beast"),
        ("furyrenegade", r"fury\s*renegade"),
        ("tridentzneorgb", r"trident\s*z5\s*neo\s*rgb"),
        ("tridentz5rgb", r"trident\s*z5\s*rgb"),
        ("tridentzrgb", r"trident\s*z\s*rgb"),
        ("tridentz", r"trident\s*z"),
        ("flarex5", r"flare\s*x5"),
        ("ripjawsv", r"ripjaws\s*v"),
        ("ripjawsm5neo", r"ripjaws\s*m5\s*neo\s*rgb"),
        ("ripjawsm5", r"ripjaws\s*m5\s*rgb"),
        ("aegis", r"(?:^|[^a-z0-9])aegis(?=$|[^a-z0-9])"),
        ("shadowiii", r"shadow\s*iii"),
        ("shadowii", r"shadow\s*ii"),
        ("shadows", r"shadow\s*s"),
        ("tcreateexpert", r"t-?create\s*expert"),
        ("vengeancelpx", r"vengeance\s*lpx"),
        ("lancerbladergb", r"lancer\s*blade\s*rgb"),
        ("lancerneonrgb", r"lancer\s*neon\s*rgb"),
        ("basic", r"(?:^|[^a-z0-9])basic(?=$|[^a-z0-9])"),
        ("signatureline", r"signature\s*(premium\s*)?line"),
    ]:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    white = bool(re.search(r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|\bбел(?:ый|ая|ое|ые)?\b", low, flags=re.IGNORECASE))
    rgb = bool(re.search(r"(?:^|[^a-z0-9])rgb(?=$|[^a-z0-9])", low, flags=re.IGNORECASE))
    ecc = bool(re.search(r"(?:^|[^a-z0-9])ecc(?=$|[^a-z0-9])", low, flags=re.IGNORECASE))
    reg = bool(re.search(r"registered|reg\b|rdimm|lrdimm", low, flags=re.IGNORECASE))

    return {
        "ddr": ddr,
        "brand": brand,
        "sku": sku,
        "capacity_gb": capacity_gb,
        "kit_modules": kit_modules,
        "mhz": mhz,
        "cl": cl,
        "series": series,
        "white": white,
        "rgb": rgb,
        "ecc": ecc,
        "reg": reg,
    }


def empty_ram_key():
    return {
        "ddr": "",
        "brand": "",
        "sku": "",
        "capacity_gb": "",
        "kit_modules": "",
        "mhz": "",
        "cl": "",
        "series": "",
        "white": False,
        "rgb": False,
        "ecc": False,
        "reg": False,
    }


def find_ram_review_candidates(
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
    local = ram_brand_model_key(name)
    if not local.get("brand") or not local.get("ddr"):
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = []
            sku_query = str(local.get("sku", "") or "").strip()
            brand_query = str(local.get("brand", "") or "").strip()
            if sku_query:
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '+', '') LIKE ? "
                        "LIMIT 120",
                        (f"%{sku_query}%",),
                    ).fetchall()
                )
            if brand_query and len(rows) < 20:
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? "
                        "LIMIT 120",
                        (f"%{brand_query.lower()}%",),
                    ).fetchall()
                )
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "ram_db_exact"})
    except Exception:
        pass

    for candidate in db_find_top_candidates(name, top_n=20, min_score=0.10, allow_b2b=False):
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
        if normalize_catalog_category_name(infer_category(candidate_name)) != "Оперативная память":
            continue
        candidate_ram = ram_brand_model_key(candidate_name)
        if candidate_ram.get("brand") != local.get("brand"):
            continue

        score = _score_ram_candidate(candidate, local, candidate_ram)
        if score is None:
            continue

        seen.add(cid)
        items.append(
            {
                "id": cid,
                "name": candidate_name,
                "url": str(candidate.get("url", "") or "").strip(),
                "score": round(min(0.999, max(0.0, score)), 3),
                "source": str(candidate.get("source", "ram_db")).strip() or "ram_db",
                "sku": candidate_ram.get("sku", ""),
                "mhz": candidate_ram.get("mhz", ""),
                "capacity_gb": candidate_ram.get("capacity_gb", ""),
            }
        )

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    local_sku = str(local.get("sku", "") or "").strip()
    if local_sku:
        exact_items = [item for item in items if str(item.get("sku", "") or "").strip() == local_sku]
        if exact_items:
            items = exact_items
    return items[: max(1, int(top_n))]


def _ram_norm_sku(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_strong_ram_sku(value):
    norm = _ram_norm_sku(value)
    if len(norm) < 8:
        return False
    if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
        return False
    blocked = {
        "ddr3",
        "ddr4",
        "ddr5",
        "rgb",
        "argb",
        "mhz",
        "cl",
        "kitof2",
        "kitof4",
        "intel",
        "amd",
        "oem",
        "box",
    }
    return norm not in blocked


def _extract_ram_sku(raw):
    sku = ""
    sku_match = re.search(r"\(([A-Za-z0-9+\-\/ ]{6,80})\)", raw)
    if sku_match and sku_match.group(1):
        sku = _ram_norm_sku(sku_match.group(1))
    if not sku:
        sku_patterns = [
            r"(KF[0-9A-Z\-\/]{7,})",
            r"(KSM[0-9A-Z\-\/]{6,})",
            r"(KVR[0-9A-Z\-\/]{6,})",
            r"(KCS[0-9A-Z\-\/]{6,})",
            r"(F[45]-[0-9A-Z\-\/]{8,})",
            r"(NT[SA-Z0-9\-\/]{8,})",
            r"(TT[CA-Z0-9\-\/]{8,})",
            r"(AX[0-9A-Z\-\/]{8,})",
            r"(PS[DPV][0-9A-Z\-\/]{7,})",
            r"(CM[A-Z0-9\-\/]{8,})",
            r"(PVV[A-Z0-9\-\/]{6,})",
            r"(PVE[A-Z0-9\-\/]{6,})",
            r"(VEU[A-Z0-9\-\/]{6,})",
        ]
        for pattern in sku_patterns:
            inline_match = re.search(pattern, raw, flags=re.IGNORECASE)
            if inline_match and inline_match.group(1):
                sku = _ram_norm_sku(inline_match.group(1))
                break
    if not sku:
        for token in reversed(re.findall(r"\b([A-Za-z0-9\-\/]{8,24})\b", raw)):
            if _is_strong_ram_sku(token):
                sku = _ram_norm_sku(token)
                break
    return sku


def _score_ram_candidate(candidate, local, candidate_ram):
    score = max(float(candidate.get("score", 0.0) or 0.0), 0.90)
    local_sku = str(local.get("sku", "") or "").strip()
    local_has_strong_sku = bool(local_sku and len(local_sku) >= 8)
    candidate_sku = str(candidate_ram.get("sku", "") or "").strip()
    local_ddr = str(local.get("ddr", "") or "").strip()
    candidate_ddr = str(candidate_ram.get("ddr", "") or "").strip()
    exact_sku = False
    if local_sku:
        if candidate_sku == local_sku:
            exact_sku = True
            score = 1.0
        elif candidate_sku:
            return None
        elif local_has_strong_sku:
            return None
    if local_ddr and candidate_ddr and candidate_ddr != local_ddr and not exact_sku:
        return None
    if local_ddr and not candidate_ddr and not exact_sku:
        return None
    for field, delta, penalty in [
        ("capacity_gb", 0.03, -0.10),
        ("kit_modules", 0.025, -0.08),
        ("mhz", 0.03, -0.08),
        ("cl", 0.02, -0.05),
        ("series", 0.04, -0.08),
    ]:
        if local.get(field) and candidate_ram.get(field) == local.get(field):
            score += delta
        elif local.get(field) and candidate_ram.get(field) and candidate_ram.get(field) != local.get(field):
            score += penalty
    for flag_key in ["white", "rgb", "ecc", "reg"]:
        if bool(local.get(flag_key)) != bool(candidate_ram.get(flag_key)):
            score -= 0.05
    if exact_sku:
        score = 1.0
    return score
