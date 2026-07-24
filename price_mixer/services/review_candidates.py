import re

from price_mixer.services.product_normalization import normalize_onliner_id


def cpu_brand_model_key(text, normalize_compact_name):
    raw = str(text or "").strip()
    if not raw:
        return "", ""
    low = raw.lower()
    brand = ""
    if "intel" in low or "xeon" in low or "pentium" in low or "celeron" in low:
        brand = "intel"
    elif "amd" in low or "ryzen" in low or "athlon" in low:
        brand = "amd"

    patterns = [
        r"\b(i[3579]-\d{4,5}[a-z]{0,3})\b",
        r"\b(core\s*ultra\s*[3579]\s*\d{3,4}[a-z]{0,3})\b",
        r"\b(ryzen\s*[3579]\s*(?:pro\s*)?\d{3,5}[a-z0-9]{0,4})\b",
        r"\b(pentium\s+(?:gold\s+)?[a-z]?\d{3,5}[a-z]{0,2})\b",
        r"\b(celeron\s+[a-z]?\d{3,5}[a-z]{0,2})\b",
        r"\b(athlon\s*(?:pro\s*)?[a-z]?\d{3,5}[a-z]{0,3})\b",
        r"\b(xeon\s+[a-z]{0,2}-?\d{3,5}[a-z]{0,3}(?:\s*v?\d)?)\b",
        r"\b(epyc\s+\d{3,4}[a-z]{0,2})\b",
    ]
    model = ""
    m_epyc_model = re.search(r"\bmodel\s+(\d{3,4}[a-z]{0,2})\b", low, flags=re.IGNORECASE)
    if m_epyc_model and m_epyc_model.group(1) and ("epyc" in low):
        model = normalize_compact_name("epyc " + m_epyc_model.group(1))
    for pattern in patterns:
        if model:
            break
        match = re.search(pattern, low, flags=re.IGNORECASE)
        if match and match.group(1):
            model = normalize_compact_name(match.group(1))
            break
    if model.startswith("pentiumgold"):
        model = "pentium" + model[len("pentiumgold"):]
    return brand, model


def cpu_article_code(text, normalize_compact_name):
    raw = str(text or "").strip()
    if not raw:
        return ""
    for match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{5,40})\)", raw):
        token = str(match.group(1) or "").strip()
        norm = normalize_compact_name(token)
        if len(norm) < 8:
            continue
        if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
            continue
        if re.match(r"^\d{2,4}$", norm):
            continue
        if norm in {"oem", "box", "tray", "multipack"}:
            continue
        return norm
    return ""


def cpu_package_type(text):
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    if re.search(r"(?:^|[^a-z0-9])(box|boxed)(?=$|[^a-z0-9])", raw, flags=re.IGNORECASE):
        return "box"
    if re.search(r"(?:^|[^a-z0-9])(oem|tray)(?=$|[^a-z0-9])", raw, flags=re.IGNORECASE):
        return "oem"
    return ""


def looks_like_cpu_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.match(r"^\s*процессор\b", low, flags=re.IGNORECASE):
        return True
    cpu_markers = [
        r"(?:^|[^a-z0-9])intel(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])amd(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])ryzen(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])epyc(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])xeon(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])pentium(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])celeron(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])athlon(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])core\s*ultra(?=$|[^a-z0-9])",
        r"socket[-\s]?\d{3,5}",
    ]
    if any(re.search(pattern, low, flags=re.IGNORECASE) for pattern in cpu_markers):
        if re.search(r"\bпэвм\b|\bсистемный блок\b|\bкомпьютер\b", low, flags=re.IGNORECASE):
            return False
        return True
    return False


def find_cpu_review_candidates(
    product_name,
    top_n=5,
    db_connection=None,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    normalize_compact_name=None,
    infer_category=None,
    normalize_catalog_category_name=None,
):
    name = str(product_name or "").strip()
    if not name:
        return []
    local_brand, local_model = cpu_brand_model_key(name, normalize_compact_name)
    if not local_brand or not local_model:
        return []
    local_package = cpu_package_type(name)
    local_code = cpu_article_code(name, normalize_compact_name)
    pool = []
    try:
        with db_connection() as conn:
            rows = []
            if local_code:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE ni.raw_name LIKE ? "
                    "LIMIT 80",
                    (f"%{local_code}%",),
                ).fetchall())
            if len(rows) < 80:
                numbers = re.findall(r"\d{4,5}[a-z]?", name, flags=re.IGNORECASE)
                for number in numbers[:2]:
                    if not local_brand:
                        continue
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE ni.raw_name LIKE ? AND ni.raw_name LIKE ? "
                        "LIMIT 80",
                        (f"%{local_brand}%", f"%{number}%"),
                    ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.93, "source": "cpu_db_seed"})
    except Exception:
        pass

    pool.extend(db_find_top_candidates(name, top_n=16, min_score=0.10, allow_b2b=False))
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
        if normalize_catalog_category_name(infer_category(candidate_name)) != "Процессор":
            continue
        candidate_brand, candidate_model = cpu_brand_model_key(candidate_name, normalize_compact_name)
        if candidate_brand != local_brand or candidate_model != local_model:
            continue
        candidate_package = cpu_package_type(candidate_name)
        package_delta = _cpu_package_score_delta(local_package, candidate_package)
        base_score = max(float(candidate.get("score", 0.0) or 0.0), 0.94)
        final_score = round(min(0.999, max(0.0, base_score + package_delta)), 3)
        seen.add(cid)
        items.append({
            "id": cid,
            "name": candidate_name,
            "url": str(candidate.get("url", "") or "").strip(),
            "score": final_score,
            "source": str(candidate.get("source", "cpu_db")).strip() or "cpu_db",
            "package": candidate_package,
        })
    items.sort(key=lambda item: (
        0 if local_package and item.get("package") == local_package else 1,
        0 if local_package == "oem" and item.get("package") == "" else 1,
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]


def _cpu_package_score_delta(local_package, candidate_package):
    if local_package == "oem":
        if candidate_package == "oem":
            return 0.03
        if candidate_package == "box":
            return -0.12
        return 0.01
    if local_package == "box":
        if candidate_package == "box":
            return 0.03
        if candidate_package == "oem":
            return -0.12
        return 0.01
    if candidate_package:
        return 0.005
    return 0.0


def board_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_board_key()
    cleaned = re.sub(r"^\s*MB\s+", "", raw, flags=re.IGNORECASE).strip()
    low = cleaned.lower()
    brand = ""
    brand_patterns = [
        ("asrock", r"\basrock\b"),
        ("gigabyte", r"\bgigabyte\b"),
        ("asus", r"\basus\b"),
        ("msi", r"\bmsi\b"),
        ("biostar", r"\bbiostar\b"),
        ("colorful", r"\bcolorful\b"),
        ("maxsun", r"\bmaxsun\b"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    socket = ""
    socket_match = re.search(r"\b(?:socket|soc)[-\s]?([a-z0-9-]+)\b", low, flags=re.IGNORECASE)
    if socket_match and socket_match.group(1):
        socket = re.sub(r"[^a-z0-9]+", "", socket_match.group(1).lower())

    chipset = ""
    chipset_match = re.search(r"\(([a-z0-9-]{2,12})\)", low, flags=re.IGNORECASE)
    if chipset_match and chipset_match.group(1):
        chip_candidate = re.sub(r"[^a-z0-9]+", "", chipset_match.group(1).lower())
        if re.match(r"^[a-z]\d{2,4}[a-z0-9]*$", chip_candidate):
            chipset = chip_candidate

    ddr = ""
    ddr_match = re.search(r"\bddr\s*([345])\b", low, flags=re.IGNORECASE)
    if ddr_match and ddr_match.group(1):
        ddr = f"ddr{ddr_match.group(1)}"

    model = ""
    model_text = ""
    if brand:
        model_text = re.split(r"\b(?:socket|soc)[-\s]?[a-z0-9-]+\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
        model_text = re.sub(rf"^\s*{re.escape(brand)}\s+", "", model_text, flags=re.IGNORECASE).strip()
        model_text = re.sub(r"\([^)]+\)\s*$", "", model_text).strip()
        model_text = re.sub(r"\s+", " ", model_text)
        model = re.sub(r"[^a-z0-9]+", "", model_text.lower())

    model_feature_source = model_text.lower()
    wifi = bool(
        re.search(r"(?:^|[^a-z0-9])wi[\s-]?fi(?:\s*\d+[a-z]*)?(?=$|[^a-z0-9])", model_feature_source, flags=re.IGNORECASE)
        or re.search(r"(?:^|[^a-z0-9])ax(?=$|[^a-z0-9])", model_feature_source, flags=re.IGNORECASE)
    )

    features = set()
    feature_patterns = [
        ("d4", r"(?:^|[^a-z0-9])d4(?=$|[^a-z0-9])"),
        ("ax", r"(?:^|[^a-z0-9])ax(?=$|[^a-z0-9])"),
        ("wifi", r"wi[\s-]?fi(?:\s*\d+[a-z]*)?"),
        ("eagle", r"(?:^|[^a-z0-9])eagle(?=$|[^a-z0-9])"),
        ("aorus", r"(?:^|[^a-z0-9])aorus(?=$|[^a-z0-9])"),
        ("gamingx", r"gaming\s*x"),
        ("steellegend", r"steel\s*legend"),
        ("prors", r"pro\s*rs"),
        ("lightning", r"(?:^|[^a-z0-9])lightning(?=$|[^a-z0-9])"),
        ("livemixer", r"live\s*mixer"),
        ("ds3h", r"(?:^|[^a-z0-9])ds3h(?=$|[^a-z0-9])"),
        ("d3hp", r"(?:^|[^a-z0-9])d3hp(?=$|[^a-z0-9])"),
        ("hdv", r"(?:^|[^a-z0-9])hdv(?=$|[^a-z0-9])"),
        ("elite", r"(?:^|[^a-z0-9])elite(?=$|[^a-z0-9])"),
        ("ud", r"(?:^|[^a-z0-9])ud(?=$|[^a-z0-9])"),
        ("riptide", r"(?:^|[^a-z0-9])riptide(?=$|[^a-z0-9])"),
        ("tomahawk", r"(?:^|[^a-z0-9])tomahawk(?=$|[^a-z0-9])"),
        ("mortar", r"(?:^|[^a-z0-9])mortar(?=$|[^a-z0-9])"),
        ("strix", r"(?:^|[^a-z0-9])strix(?=$|[^a-z0-9])"),
        ("prime", r"(?:^|[^a-z0-9])prime(?=$|[^a-z0-9])"),
    ]
    for feature_key, pattern in feature_patterns:
        if re.search(pattern, model_feature_source, flags=re.IGNORECASE):
            features.add(feature_key)

    return {
        "brand": brand,
        "model": model,
        "model_text": model_text.upper(),
        "chipset": chipset,
        "socket": socket,
        "ddr": ddr,
        "wifi": wifi,
        "features": features,
    }


def empty_board_key():
    return {
        "brand": "",
        "model": "",
        "model_text": "",
        "chipset": "",
        "socket": "",
        "ddr": "",
        "wifi": None,
        "features": set(),
    }


def find_board_review_candidates(
    product_name,
    top_n=5,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    infer_category=None,
    normalize_catalog_category_name=None,
):
    name = str(product_name or "").strip()
    if not name:
        return []
    local = board_brand_model_key(name)
    local_brand = local.get("brand", "")
    local_model = local.get("model", "")
    if not local_brand or not local_model:
        return []

    pool = []
    exact = db_find_exact_id_for_name(name)
    if exact:
        pool.append(exact)
    try:
        model_text = str(local.get("model_text", "") or "").strip()
        brand_query = str(local_brand or "").strip()
        if model_text and brand_query:
            pool.extend(db_find_top_candidates(
                f"{brand_query} {model_text}",
                top_n=25,
                min_score=0.10,
                allow_b2b=False,
            ) or [])
        if model_text:
            pool.extend(db_find_top_candidates(
                model_text,
                top_n=20,
                min_score=0.10,
                allow_b2b=False,
            ) or [])
    except Exception:
        pass
    pool.extend(db_find_top_candidates(name, top_n=15, min_score=0.10, allow_b2b=False) or [])

    items = []
    seen = set()
    for candidate in pool:
        if not isinstance(candidate, dict):
            continue
        cid = normalize_onliner_id(candidate.get("id", ""))
        candidate_name = str(candidate.get("name", "") or "").strip()
        if not cid or not candidate_name or cid in seen:
            continue
        if normalize_catalog_category_name(infer_category(candidate_name)) != "Материнская плата":
            continue
        candidate_board = board_brand_model_key(candidate_name)
        if candidate_board.get("brand") != local_brand:
            continue
        candidate_model = candidate_board.get("model", "")
        model_exact = candidate_model == local_model
        model_close = bool(candidate_model and local_model and (candidate_model in local_model or local_model in candidate_model))
        if not model_exact and not model_close:
            continue

        score = _score_board_candidate(candidate, local, candidate_board, model_exact, model_close)
        candidate_features = set(candidate_board.get("features") or set())
        seen.add(cid)
        items.append({
            "id": cid,
            "name": candidate_name,
            "url": str(candidate.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(candidate.get("source", "mb_db")).strip() or "mb_db",
            "chipset": candidate_board.get("chipset", ""),
            "socket": candidate_board.get("socket", ""),
            "ddr": candidate_board.get("ddr", ""),
            "wifi": candidate_board.get("wifi"),
            "features": sorted(candidate_features),
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    local_sku = str(local.get("sku", "") or "").strip()
    if local_sku:
        exact_items = [item for item in items if str(item.get("sku", "") or "").strip() == local_sku]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _score_board_candidate(candidate, local, candidate_board, model_exact, model_close):
    score = max(float(candidate.get("score", 0.0) or 0.0), 0.90)
    if model_exact:
        score += 0.06
    elif model_close:
        score += 0.03
    if local.get("chipset") and candidate_board.get("chipset") == local.get("chipset"):
        score += 0.03
    elif local.get("chipset") and candidate_board.get("chipset") and candidate_board.get("chipset") != local.get("chipset"):
        score -= 0.08
    if local.get("socket") and candidate_board.get("socket") == local.get("socket"):
        score += 0.02
    elif local.get("socket") and candidate_board.get("socket") and candidate_board.get("socket") != local.get("socket"):
        score -= 0.08
    if local.get("ddr") and candidate_board.get("ddr") == local.get("ddr"):
        score += 0.03
    elif local.get("ddr") and candidate_board.get("ddr") and candidate_board.get("ddr") != local.get("ddr"):
        score -= 0.12
    local_wifi = bool(local.get("wifi"))
    candidate_wifi = bool(candidate_board.get("wifi"))
    if local_wifi != candidate_wifi:
        return -1.0
    if local_wifi and candidate_wifi:
        score += 0.03

    local_features = set(local.get("features") or set())
    candidate_features = set(candidate_board.get("features") or set())
    if local_features or candidate_features:
        shared_features = local_features & candidate_features
        missing_features = local_features - candidate_features
        extra_features = candidate_features - local_features
        score += min(0.04, 0.012 * len(shared_features))
        score -= min(0.14, 0.035 * len(missing_features))
        score -= min(0.06, 0.015 * len(extra_features - {"wifi"}))

    if model_close and not model_exact and local_features:
        strong_family = {
            "d4", "ax", "aorus", "eagle", "steellegend", "prors", "lightning", "livemixer",
            "ds3h", "d3hp", "hdv", "elite", "ud", "riptide", "tomahawk", "mortar", "strix",
            "prime", "gamingx",
        }
        if (local_features & strong_family) - candidate_features:
            score -= 0.10
    return score


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
    after_brand = re.sub(r'^\s*(игровой\s+)?монитор\s+', '', after_brand, flags=re.IGNORECASE).strip()
    if size:
        after_brand = re.sub(r'^\s*\d{2}(?:\.\d)?\s*"\s*', '', after_brand, flags=re.IGNORECASE).strip()
    if brand:
        after_brand = re.sub(rf'^\s*{re.escape(brand)}\s+', '', after_brand, flags=re.IGNORECASE).strip()

    resolution = ""
    resolution_match = re.search(r'(\d{3,4}\s*x\s*\d{3,4})', cleaned, flags=re.IGNORECASE)
    if resolution_match and resolution_match.group(1):
        resolution = re.sub(r"\s+", "", resolution_match.group(1).lower())

    hz = ""
    hz_match = re.search(r'(\d{2,3})\s*(?:гц|hz)\b', low, flags=re.IGNORECASE)
    if hz_match and hz_match.group(1):
        hz = hz_match.group(1)

    white = bool(re.search(r'(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|бел', low, flags=re.IGNORECASE))

    model_text = re.split(r'\s*\(', after_brand, maxsplit=1)[0].strip()
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
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 120",
                    (f"%{local_code}%",),
                ).fetchall())
            if brand_sql and model_text:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                    "LIMIT 120",
                    (f"%{brand_sql.lower()}%", f"%{model_text.lower()}%"),
                ).fetchall())
            compact_model = str(local.get("model", "") or "").strip()
            if compact_model and len(rows) < 20:
                tail = re.sub(r"[^a-z0-9]+", "", model_text.lower())
                model_token = model_text.lower()
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 120",
                    (f"%{model_token}%",),
                ).fetchall())
                if tail and tail != model_token:
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '\"', '') LIKE ? "
                        "LIMIT 120",
                        (f"%{tail}%",),
                    ).fetchall())
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
        model_close = bool(candidate_model and local_model and (candidate_model in local_model or local_model in candidate_model))
        if not code_exact and not model_exact and not model_close:
            continue

        score = _score_monitor_candidate(candidate, local, candidate_monitor, code_exact, model_exact, model_close)
        seen.add(cid)
        items.append({
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
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]


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
    elif local.get("resolution") and candidate_monitor.get("resolution") and candidate_monitor.get("resolution") != local.get("resolution"):
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


def gpu_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_gpu_key()
    low = raw.lower()
    gpu_brand = "nvidia" if "geforce" in low or "rtx" in low or "gtx" in low else (
        "amd" if "radeon" in low or re.search(r"(?:^|[^a-z0-9])rx\s*\d{3,4}", low) else ""
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
                    rows.extend(conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '+', ''), '(', '') LIKE ? "
                        "LIMIT 80",
                        (f"%{sku_query.replace('+','')}%",),
                    ).fetchall())
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                    "LIMIT 160",
                    (f"%{vendor_query.lower()}%", f"%{spaced_model.lower()}%"),
                ).fetchall())
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '+', '') LIKE ? "
                    "LIMIT 160",
                    (f"%{model_query.replace('+','')}%",),
                ).fetchall())
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
        items.append({
            "id": cid,
            "name": candidate_name,
            "url": str(candidate.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(candidate.get("source", "gpu_db")).strip() or "gpu_db",
            "series": candidate_gpu.get("series", ""),
            "sku": candidate_gpu.get("sku", ""),
            "memory_gb": candidate_gpu.get("memory_gb", ""),
            "white": candidate_gpu.get("white"),
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]


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
    elif local.get("memory_gb") and candidate_gpu.get("memory_gb") and candidate_gpu.get("memory_gb") != local.get("memory_gb"):
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
    kit_match = re.search(r"kitof\s*(\d+)|kit\s*[xх]\s*(\d+)|(\d+)\s*[xх]\s*\d+\s*(?:g|г)\s*(?:b|б)", low, flags=re.IGNORECASE)
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
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '+', '') LIKE ? "
                    "LIMIT 120",
                    (f"%{sku_query}%",),
                ).fetchall())
            if brand_query and len(rows) < 20:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 120",
                    (f"%{brand_query.lower()}%",),
                ).fetchall())
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
        items.append({
            "id": cid,
            "name": candidate_name,
            "url": str(candidate.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(candidate.get("source", "ram_db")).strip() or "ram_db",
            "sku": candidate_ram.get("sku", ""),
            "mhz": candidate_ram.get("mhz", ""),
            "capacity_gb": candidate_ram.get("capacity_gb", ""),
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    local_sku = str(local.get("sku", "") or "").strip()
    if local_sku:
        exact_items = [item for item in items if str(item.get("sku", "") or "").strip() == local_sku]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _ram_norm_sku(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_strong_ram_sku(value):
    norm = _ram_norm_sku(value)
    if len(norm) < 8:
        return False
    if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
        return False
    blocked = {
        "ddr3", "ddr4", "ddr5", "rgb", "argb", "mhz", "cl",
        "kitof2", "kitof4", "intel", "amd", "oem", "box",
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
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 150",
                    (f"%{local_code}%",),
                ).fetchall())
            if local_brand and len(rows) < 80:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{local_brand.lower()}%",),
                ).fetchall())
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

    exact_items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    soft_items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    items = exact_items if exact_items else soft_items
    return items[:max(1, int(top_n))]


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
        "source": str(candidate.get("source", "ssd_db")).strip() or (
            "ssd_db_code_exact" if exact_code else "ssd_db_fallback"
        ),
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
        "ssd", "nvme", "m2", "pcie", "sata", "usb", "typec",
        "mbps", "tb", "gb", "rtl", "oem", "bulk", "series",
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


def psu_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_psu_key()
    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("1stplayer", r"(?:^|[^a-z0-9])1st\s*player(?=$|[^a-z0-9])|(?:^|[^a-z0-9])1stplayer(?=$|[^a-z0-9])"),
        ("adataxpg", r"(?:^|[^a-z0-9])(?:adata|xpg)(?=$|[^a-z0-9])"),
        ("chieftec", r"(?:^|[^a-z0-9])chieftec(?=$|[^a-z0-9])"),
        ("cougar", r"(?:^|[^a-z0-9])cougar(?=$|[^a-z0-9])"),
        ("deepcool", r"(?:^|[^a-z0-9])deepcool(?=$|[^a-z0-9])"),
        ("lianli", r"(?:^|[^a-z0-9])lian\s*li(?=$|[^a-z0-9])|(?:^|[^a-z0-9])lianli(?=$|[^a-z0-9])"),
        ("gamemax", r"(?:^|[^a-z0-9])gamemax(?=$|[^a-z0-9])"),
        ("montech", r"(?:^|[^a-z0-9])montech(?=$|[^a-z0-9])"),
        ("ntech", r"(?:^|[^a-z0-9])n-?tech(?=$|[^a-z0-9])"),
        ("powercase", r"(?:^|[^a-z0-9])powercase(?=$|[^a-z0-9])"),
        ("projectx", r"(?:^|[^a-z0-9])project\s*x(?=$|[^a-z0-9])"),
        ("vicsone", r"(?:^|[^a-z0-9])vicsone(?=$|[^a-z0-9])"),
        ("zalman", r"(?:^|[^a-z0-9])zalman(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    watt = ""
    watt_match = re.search(r"\b(\d{3,4})\s*(?:w|вт)\b", low, flags=re.IGNORECASE)
    if watt_match and watt_match.group(1):
        watt = watt_match.group(1)

    eff = ""
    if re.search(r"80\s*plus\s*titanium|\btitanium\b", low, flags=re.IGNORECASE):
        eff = "titanium"
    elif re.search(r"80\s*plus\s*platinum|\bplatinum\b", low, flags=re.IGNORECASE):
        eff = "platinum"
    elif re.search(r"80\s*plus\s*gold|\bgold\b", low, flags=re.IGNORECASE):
        eff = "gold"
    elif re.search(r"80\s*plus\s*silver|\bsilver\b", low, flags=re.IGNORECASE):
        eff = "silver"
    elif re.search(r"80\s*plus\s*bronze|\bbronze\b", low, flags=re.IGNORECASE):
        eff = "bronze"
    elif re.search(r"80\s*plus\s*standard|\bstandard\b|80\s*plus\b", low, flags=re.IGNORECASE):
        eff = "standard"

    modular = ""
    if re.search(r"non[-\s]?modular|немодуль|не\s*модуль", low, flags=re.IGNORECASE):
        modular = "non"
    elif re.search(r"semi[-\s]?modular|полу[-\s]?модуль", low, flags=re.IGNORECASE):
        modular = "semi"
    elif re.search(r"full[-\s]?modular|полностью\s*модуль", low, flags=re.IGNORECASE):
        modular = "full"

    code = _extract_psu_code(raw)

    series_patterns = [
        ("ngdpgold", r"ngdp\s*gold"),
        ("ackbronze", r"ack\s*bronze"),
        ("ackgold", r"ack\s*gold"),
        ("dkpremium", r"dk\s*premium"),
        ("core_reactor_ii_ve", r"core\s*reactor\s*ii\s*ve"),
        ("core_reactor_ii", r"core\s*reactor\s*ii"),
        ("cyber_core_ii", r"cyber\s*core\s*ii"),
        ("pylonii", r"pylon\s*ii"),
        ("pylon", r"(?:^|[^a-z0-9])pylon(?=$|[^a-z0-9])"),
        ("kyber", r"(?:^|[^a-z0-9])kyber(?=$|[^a-z0-9])"),
        ("fusion", r"(?:^|[^a-z0-9])fusion(?=$|[^a-z0-9])"),
        ("probe", r"(?:^|[^a-z0-9])probe(?=$|[^a-z0-9])"),
        ("pymcore", r"(?:^|[^a-z0-9])pymcore(?=$|[^a-z0-9])"),
        ("polarispro", r"polaris\s*pro"),
        ("polaris", r"(?:^|[^a-z0-9])polaris(?=$|[^a-z0-9])"),
        ("core", r"(?:^|[^a-z0-9])core(?=$|[^a-z0-9])"),
        ("proton", r"(?:^|[^a-z0-9])proton(?=$|[^a-z0-9])"),
        ("gamerstorm", r"(?:^|[^a-z0-9])gamerstorm(?=$|[^a-z0-9])"),
        ("centuryii", r"century\s*ii"),
        ("centuryg5", r"century\s*g5"),
        ("titangold", r"titan\s*gold"),
        ("titanpla", r"titan\s*pla"),
        ("fk", r"(?:^|[^a-z0-9])fk(?=$|[^a-z0-9])"),
    ]
    series = ""
    for key, pattern in series_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    form_factor = "sfx" if re.search(r"(?:^|[^a-z0-9])sfx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE) else "atx"
    atx = ""
    atx_match = re.search(r"\batx\s*([0-9](?:\.[0-9]{1,2})?)\b", low, flags=re.IGNORECASE)
    if atx_match and atx_match.group(1):
        atx = atx_match.group(1)
    white = bool(re.search(r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])|\bбел(?:ый|ая|ое|ые)?\b", low, flags=re.IGNORECASE))
    return {
        "brand": brand,
        "watt": watt,
        "eff": eff,
        "modular": modular,
        "code": code,
        "series": series,
        "form_factor": form_factor,
        "atx": atx,
        "white": white,
    }


def empty_psu_key():
    return {
        "brand": "",
        "watt": "",
        "eff": "",
        "modular": "",
        "code": "",
        "series": "",
        "form_factor": "",
        "atx": "",
        "white": False,
    }


def find_psu_review_candidates(
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
    local = psu_brand_model_key(name)
    if not local.get("brand") or not local.get("watt"):
        return []
    local_code = str(local.get("code", "") or "").strip()

    pool = []
    try:
        with db_connection() as conn:
            rows = []
            brand_query = str(local.get("brand", "") or "").strip()
            watt_query = str(local.get("watt", "") or "").strip()
            code_query = str(local.get("code", "") or "").strip()
            if code_query:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                    "LIMIT 180",
                    (f"%{code_query}%",),
                ).fetchall())
            if brand_query and watt_query:
                rows.extend(conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{brand_query.lower()}%", f"%{watt_query}%"),
                ).fetchall())
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "psu_db_exact"})
    except Exception:
        pass

    if db_find_top_candidates:
        for candidate in db_find_top_candidates(name, top_n=22, min_score=0.10, allow_b2b=False):
            pool.append(candidate)
    if db_find_exact_id_for_name:
        exact = db_find_exact_id_for_name(name)
        if exact:
            pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for candidate in pool:
        classified = _classify_psu_candidate(
            candidate,
            seen,
            local,
            local_code,
            infer_category,
            normalize_catalog_category_name,
        )
        if not classified:
            continue
        seen.add(classified["id"])
        items.append(classified)

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_code:
        exact_items = [
            item for item in items
            if psu_code_match(local_code, str(item.get("code", "") or "").strip())
        ]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def psu_code_match(a, b):
    a = _psu_norm(a)
    b = _psu_norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    strip_suffixes = ("bulk", "oem", "ret", "wgeu", "eu", "fa0b", "fc0b", "fc0w", "bk", "wh")
    for suffix in strip_suffixes:
        if a.endswith(suffix):
            a = a[: -len(suffix)]
        if b.endswith(suffix):
            b = b[: -len(suffix)]
    if a == b:
        return True
    if len(a) >= 6 and len(b) >= 6 and (a.startswith(b) or b.startswith(a)):
        return True
    if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
        return True
    return False


def _classify_psu_candidate(
    candidate,
    seen,
    local,
    local_code,
    infer_category,
    normalize_catalog_category_name,
):
    if not isinstance(candidate, dict):
        return None
    cid = normalize_onliner_id(candidate.get("id", ""))
    candidate_name = str(candidate.get("name", "") or "").strip()
    if not cid or not candidate_name or cid in seen:
        return None
    if normalize_catalog_category_name(infer_category(candidate_name)) != "Блок питания":
        return None

    candidate_psu = psu_brand_model_key(candidate_name)
    if candidate_psu.get("brand") != local.get("brand"):
        return None
    for field in ["watt", "eff", "modular", "form_factor"]:
        if local.get(field) and candidate_psu.get(field) and candidate_psu.get(field) != local.get(field):
            return None
    candidate_code = str(candidate_psu.get("code", "") or "").strip()
    if local_code and candidate_code and not psu_code_match(local_code, candidate_code):
        return None

    score = max(float(candidate.get("score", 0.0) or 0.0), 0.90)
    if local_code and candidate_code and psu_code_match(local_code, candidate_code):
        score = 0.999
    if local.get("series") and candidate_psu.get("series") == local.get("series"):
        score += 0.05
    elif local.get("series") and candidate_psu.get("series") and candidate_psu.get("series") != local.get("series"):
        score -= 0.08
    if local.get("atx") and candidate_psu.get("atx"):
        try:
            score += 0.015 if abs(float(local.get("atx")) - float(candidate_psu.get("atx"))) <= 0.11 else -0.05
        except Exception:
            pass
    if bool(local.get("white")) != bool(candidate_psu.get("white")):
        score -= 0.05

    return {
        "id": cid,
        "name": candidate_name,
        "url": str(candidate.get("url", "") or "").strip(),
        "score": round(min(0.999, max(0.0, score)), 3),
        "source": str(candidate.get("source", "psu_db")).strip() or "psu_db",
        "watt": candidate_psu.get("watt", ""),
        "eff": candidate_psu.get("eff", ""),
        "modular": candidate_psu.get("modular", ""),
        "code": candidate_code,
        "series": candidate_psu.get("series", ""),
    }


def _psu_norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_strong_psu_code(value):
    norm = _psu_norm(value)
    if len(norm) < 6:
        return False
    if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
        return False
    blocked = {
        "atx", "atx20", "atx23", "atx24", "atx30", "atx31",
        "nonmodular", "semimodular", "fullmodular", "modular",
        "activepfc", "apfc", "llcdc", "dcdc", "ret", "oem", "bulk",
    }
    if norm in blocked:
        return False
    return not norm.startswith("atx")


def _extract_psu_code(raw):
    block_words = {"black", "white", "bronze", "gold", "silver", "platinum", "modular", "nonmodular"}
    preferred_prefixes = ("ps", "ha", "pps", "ppx", "r", "zm", "pn", "pb", "vte", "sr")

    def token_rank(token):
        token = str(token or "").strip()
        norm = _psu_norm(token)
        if not _is_strong_psu_code(token):
            return -999
        if any(word in norm for word in block_words):
            return -999
        parts = [part for part in re.split(r"-+", token) if part]
        hyphens = max(0, len(parts) - 1)
        score = 0
        if 1 <= hyphens <= 3:
            score += 20
        if len(norm) <= 18:
            score += 12
        if norm.startswith(preferred_prefixes):
            score += 18
        if any(ch.isdigit() for ch in (parts[0] if parts else "")):
            score += 6
        if len(parts) >= 4:
            score -= 6
        return score

    token_candidates = []
    for match in re.finditer(r"\b([A-Za-z0-9]{1,10}(?:[.-][A-Za-z0-9]{1,16}){1,6})\b", raw):
        token = str(match.group(1) or "").strip()
        rank = token_rank(token)
        if rank > -999:
            token_candidates.append((rank, token))
    if token_candidates:
        token_candidates.sort(key=lambda item: (-item[0], len(_psu_norm(item[1]))))
        return _psu_norm(token_candidates[0][1])

    for match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9\-]{3,64})\)", raw):
        token = str(match.group(1) or "").strip()
        if _is_strong_psu_code(token):
            return _psu_norm(token)
    return ""


def case_brand_model_key(text):
    raw = str(text or "").strip()
    if not raw:
        return empty_case_key()
    low = raw.lower()
    brand = ""
    brand_patterns = [
        ("aerocool", r"(?:^|[^a-z0-9])aerocool(?=$|[^a-z0-9])"),
        ("adataxpg", r"(?:^|[^a-z0-9])(?:adata|xpg)(?=$|[^a-z0-9])"),
        ("cougar", r"(?:^|[^a-z0-9])cougar(?=$|[^a-z0-9])"),
        ("deepcool", r"(?:^|[^a-z0-9])deepcool(?=$|[^a-z0-9])"),
        ("gamemax", r"(?:^|[^a-z0-9])gamemax(?=$|[^a-z0-9])"),
        ("geometricfuture", r"(?:^|[^a-z0-9])geometric\s*future(?=$|[^a-z0-9])"),
        ("montech", r"(?:^|[^a-z0-9])montech(?=$|[^a-z0-9])"),
        ("powercase", r"(?:^|[^a-z0-9])powercase(?=$|[^a-z0-9])"),
        ("projectx", r"(?:^|[^a-z0-9])project\s*x(?=$|[^a-z0-9])"),
        ("segotep", r"(?:^|[^a-z0-9])segotep(?=$|[^a-z0-9])"),
        ("vicsone", r"(?:^|[^a-z0-9])vicsone(?=$|[^a-z0-9])"),
        ("zalman", r"(?:^|[^a-z0-9])zalman(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    form_factor = ""
    if re.search(r"(?:^|[^a-z0-9])e-?atx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "eatx"
    elif re.search(r"(?:^|[^a-z0-9])(?:micro[-\s]?atx|m[-\s]?atx)(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "matx"
    elif re.search(r"(?:^|[^a-z0-9])mini-?itx|miniitx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "itx"
    elif re.search(r"(?:^|[^a-z0-9])atx(?=$|[^a-z0-9])", low, flags=re.IGNORECASE):
        form_factor = "atx"

    without_psu = bool(re.search(r"без\s*б/?п|без\s*блока\s*пит", low, flags=re.IGNORECASE))
    with_psu = False
    if not without_psu:
        if (
            re.search(r"\b\d{3,4}\s*w\b", low, flags=re.IGNORECASE)
            or re.search(r"(?:^|[^a-zа-я0-9])с\s*б/?п(?=$|[^a-zа-я0-9])", low, flags=re.IGNORECASE)
            or re.search(r"(?:^|[^a-zа-я0-9])б/?п\s+[a-zа-я0-9]", low, flags=re.IGNORECASE)
        ):
            with_psu = True
    watt = ""
    watt_match = re.search(r"\b(\d{3,4})\s*w\b", low, flags=re.IGNORECASE)
    if watt_match and watt_match.group(1):
        watt = watt_match.group(1)

    code = _extract_case_code(raw)

    series = ""
    series_patterns = [
        ("invaderx", r"invader\s*x"),
        ("defender", r"(?:^|[^a-z0-9])defender(?=$|[^a-z0-9])"),
        ("lander", r"(?:^|[^a-z0-9])lander(?=$|[^a-z0-9])"),
        ("valorairplus", r"valor\s*air\s*plus"),
        ("valorair", r"valor\s*air"),
        ("airface", r"(?:^|[^a-z0-9])airface(?=$|[^a-z0-9])"),
        ("cc560", r"(?:^|[^a-z0-9])cc560(?=$|[^a-z0-9])"),
        ("cg580", r"(?:^|[^a-z0-9])cg580(?=$|[^a-z0-9])"),
        ("ch780", r"(?:^|[^a-z0-9])ch780(?=$|[^a-z0-9])"),
        ("ch170", r"(?:^|[^a-z0-9])ch170(?=$|[^a-z0-9])"),
        ("ch360", r"(?:^|[^a-z0-9])ch360(?=$|[^a-z0-9])"),
        ("ch160", r"(?:^|[^a-z0-9])ch160(?=$|[^a-z0-9])"),
        ("matrexx30", r"matrexx\s*30"),
        ("matrexx55", r"matrexx\s*55"),
        ("dragonknight", r"dragon\s*knight"),
        ("meshbox", r"(?:^|[^a-z0-9])meshbox(?=$|[^a-z0-9])"),
        ("precision", r"(?:^|[^a-z0-9])precision(?=$|[^a-z0-9])"),
        ("air1000", r"air\s*1000"),
        ("hs01pro", r"hs01\s*pro"),
        ("hs02pro", r"hs02\s*pro"),
        ("king95pro", r"king\s*95\s*pro"),
        ("skyone", r"sky\s*one"),
        ("skytwo", r"sky\s*two"),
        ("x3mesh", r"x3\s*mesh"),
        ("xrwood", r"xr\s*wood"),
    ]
    for key, pattern in series_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            series = key
            break

    colors = _case_colors(low)
    return {
        "brand": brand,
        "code": code,
        "series": series,
        "form_factor": form_factor,
        "with_psu": with_psu,
        "watt": watt,
        "white": "white" in colors,
        "colors": colors,
    }


def empty_case_key():
    return {
        "brand": "",
        "code": "",
        "series": "",
        "form_factor": "",
        "with_psu": False,
        "watt": "",
        "white": False,
        "colors": set(),
    }


def looks_like_case_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.match(r"^\s*корпус\b", low, flags=re.IGNORECASE):
        return True
    case_markers = [
        r"tempered\s*glass",
        r"vga\s*max",
        r"cpu\s*max",
        r"(?:^|[^a-z0-9])mesh(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])без\s*б/?п(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])mini-?itx(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])micro[-\s]?atx(?=$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])e-?atx(?=$|[^a-z0-9])",
    ]
    if any(re.search(pattern, low, flags=re.IGNORECASE) for pattern in case_markers):
        return True

    brand_prefix = (
        r"^\s*(deepcool|montech|gamemax|zalman|adata|xpg|aerocool|"
        r"powercase|cougar|vicsone|segotep|project\s*x)\b"
    )
    model_tokens = (
        r"(cc560|ch780|ch160|matrexx|invader|defender|lander|"
        r"valor\s*air|air\s*1000|king\s*95|x3\s*mesh|xr\s*wood|"
        r"hs0[12]\s*pro|sky\s*one|sky\s*two|meshbox|dragon\s*knight|precision)"
    )
    return bool(
        re.search(brand_prefix, low, flags=re.IGNORECASE)
        and re.search(model_tokens, low, flags=re.IGNORECASE)
    )


def case_code_match(a, b):
    a = re.sub(r"[^a-z0-9]+", "", str(a or "").lower())
    b = re.sub(r"[^a-z0-9]+", "", str(b or "").lower())
    if not a or not b:
        return False
    if a == b:
        return True

    def strip_leading_r_sku(value):
        if value.startswith("r") and len(value) > 6 and value[1:2].isalpha():
            return value[1:]
        return value

    variants_a = {strip_leading_r_sku(a), a}
    variants_b = {strip_leading_r_sku(b), b}
    if variants_a & variants_b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 5 and len(longer) >= 10 and shorter in longer:
        return True
    if len(a) >= 6 and len(b) >= 6 and (a.startswith(b) or b.startswith(a)):
        return True
    if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
        return True
    return False


def find_case_review_candidates(
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
    local = case_brand_model_key(name)
    if not local.get("brand"):
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = _fetch_case_seed_rows(conn, local)
            seen_seed = set()
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid or oid in seen_seed:
                    continue
                seen_seed.add(oid)
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.90, "source": "case_db_exact"})
    except Exception:
        pass

    if db_find_top_candidates:
        for candidate in db_find_top_candidates(name, top_n=24, min_score=0.10, allow_b2b=False):
            pool.append(candidate)
    if db_find_exact_id_for_name:
        exact = db_find_exact_id_for_name(name)
        if exact:
            pool = [exact] + list(pool or [])

    items = []
    seen = set()
    for candidate in pool:
        classified = _classify_case_candidate(
            candidate,
            seen,
            local,
            infer_category,
            normalize_catalog_category_name,
        )
        if not classified:
            continue
        seen.add(classified["id"])
        items.append(classified)

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    local_code = str(local.get("code", "") or "").strip()
    if local_code:
        exact_items = [
            item for item in items
            if case_code_match(local_code, str(item.get("code", "") or "").strip())
        ]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def case_form_factor_compatible(local_ff, candidate_ff):
    if not local_ff or not candidate_ff or local_ff == candidate_ff:
        return True
    return {local_ff, candidate_ff} <= {"atx", "eatx"}


def _fetch_case_seed_rows(conn, local):
    rows = []
    brand_query = str(local.get("brand", "") or "").strip()
    code_query = str(local.get("code", "") or "").strip()
    series_query = str(local.get("series", "") or "").strip()
    if code_query:
        rows.extend(conn.execute(
            "SELECT ni.onliner_id, ni.raw_name, oc.url "
            "FROM name_index ni "
            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
            "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
            "LIMIT 200",
            (f"%{code_query}%",),
        ).fetchall())
    if brand_query:
        for brand_token in _case_brand_tokens(brand_query):
            rows.extend(conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE lower(ni.raw_name) LIKE ? "
                "LIMIT 220",
                (f"%{brand_token}%",),
            ).fetchall())
    if series_query:
        for series_token in _case_series_tokens(series_query):
            rows.extend(conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE lower(ni.raw_name) LIKE ? "
                "LIMIT 180",
                (f"%{series_token.lower()}%",),
            ).fetchall())
    return rows


def _classify_case_candidate(candidate, seen, local, infer_category, normalize_catalog_category_name):
    if not isinstance(candidate, dict):
        return None
    cid = normalize_onliner_id(candidate.get("id", ""))
    candidate_name = str(candidate.get("name", "") or "").strip()
    if not cid or not candidate_name or cid in seen:
        return None
    if normalize_catalog_category_name(infer_category(candidate_name)) != "Корпус":
        return None

    candidate_case = case_brand_model_key(candidate_name)
    if candidate_case.get("brand") != local.get("brand"):
        return None
    if local.get("form_factor") and candidate_case.get("form_factor"):
        if not case_form_factor_compatible(local.get("form_factor"), candidate_case.get("form_factor")):
            return None
    if local.get("code") and candidate_case.get("code") and not case_code_match(local.get("code"), candidate_case.get("code")):
        return None
    if local.get("with_psu") != candidate_case.get("with_psu"):
        return None
    if (
        local.get("with_psu")
        and local.get("watt")
        and candidate_case.get("watt")
        and local.get("watt") != candidate_case.get("watt")
    ):
        return None

    local_colors = set(local.get("colors") or set())
    candidate_colors = set(candidate_case.get("colors") or set())
    if local_colors and candidate_colors and not (local_colors & candidate_colors):
        return None

    score = _score_case_candidate(candidate, local, candidate_case, local_colors, candidate_colors)
    return {
        "id": cid,
        "name": candidate_name,
        "url": str(candidate.get("url", "") or "").strip(),
        "score": round(min(0.999, max(0.0, score)), 3),
        "source": str(candidate.get("source", "case_db")).strip() or "case_db",
        "code": candidate_case.get("code", ""),
        "series": candidate_case.get("series", ""),
        "form_factor": candidate_case.get("form_factor", ""),
        "colors": sorted(candidate_colors),
    }


def _score_case_candidate(candidate, local, candidate_case, local_colors, candidate_colors):
    score = max(float(candidate.get("score", 0.0) or 0.0), 0.88)
    if local.get("code") and candidate_case.get("code") and case_code_match(local.get("code"), candidate_case.get("code")):
        score = 0.999
    if local.get("series") and candidate_case.get("series") == local.get("series"):
        score += 0.05
    elif local.get("series") and candidate_case.get("series") and candidate_case.get("series") != local.get("series"):
        score -= 0.08
    if local_colors and candidate_colors:
        shared_colors = local_colors & candidate_colors
        extra_colors = candidate_colors - local_colors
        score += min(0.05, 0.02 * len(shared_colors))
        score -= min(0.08, 0.02 * len(extra_colors))
    elif bool(local.get("white")) != bool(candidate_case.get("white")):
        score -= 0.06
    return score


def _extract_case_code(raw):
    paren_match = re.search(r"\(([A-Za-z0-9][A-Za-z0-9\-]{3,40})\)", raw)
    if paren_match and paren_match.group(1):
        candidate = str(paren_match.group(1) or "").strip()
        if not re.match(r"^\d+\s*[xх]", candidate.lower()):
            return re.sub(r"[^a-z0-9]+", "", candidate.lower())
    for pattern in [
        r"\b([A-Za-z]{2,6}-[A-Za-z0-9]{2,16}(?:-[A-Za-z0-9]{1,10})?)\b",
        r"\b([A-Za-z]{2,6}[0-9]{2,5}[A-Za-z0-9\-]{0,8})\b",
    ]:
        code_match = re.search(pattern, raw)
        if code_match and code_match.group(1):
            return re.sub(r"[^a-z0-9]+", "", code_match.group(1).lower())
    return ""


def _case_colors(low):
    color_map = {
        "black": [r"(?:^|[^a-z0-9])black(?=$|[^a-z0-9])", r"черн", r"ч[её]рн"],
        "white": [r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])", r"бел"],
        "gray": [r"(?:^|[^a-z0-9])gray(?=$|[^a-z0-9])", r"(?:^|[^a-z0-9])grey(?=$|[^a-z0-9])", r"сер"],
        "red": [r"(?:^|[^a-z0-9])red(?=$|[^a-z0-9])", r"красн"],
        "blue": [r"(?:^|[^a-z0-9])blue(?=$|[^a-z0-9])", r"син"],
        "green": [r"(?:^|[^a-z0-9])green(?=$|[^a-z0-9])", r"зел"],
        "yellow": [r"(?:^|[^a-z0-9])yellow(?=$|[^a-z0-9])", r"желт"],
        "pink": [r"(?:^|[^a-z0-9])pink(?=$|[^a-z0-9])", r"роз"],
        "orange": [r"(?:^|[^a-z0-9])orange(?=$|[^a-z0-9])", r"оранж"],
        "silver": [r"(?:^|[^a-z0-9])silver(?=$|[^a-z0-9])", r"серебр"],
    }
    colors = set()
    for color_key, patterns in color_map.items():
        for pattern in patterns:
            if re.search(pattern, low, flags=re.IGNORECASE):
                colors.add(color_key)
                break
    return colors


def _case_brand_tokens(brand_query):
    if brand_query == "adataxpg":
        return ["adata xpg", "xpg", "adata"]
    if brand_query == "projectx":
        return ["project x", "projectx"]
    if brand_query == "geometricfuture":
        return ["geometric future", "geometricfuture"]
    return [brand_query.lower()]


def _case_series_tokens(series_query):
    return {
        "invaderx": ["invader x", "invaderx"],
        "defender": ["defender"],
        "lander": ["lander"],
        "valorairplus": ["valor air plus", "valorairplus"],
        "valorair": ["valor air", "valorair"],
        "air1000": ["air 1000", "air1000"],
        "king95pro": ["king 95 pro", "king95 pro", "king95pro"],
        "x3mesh": ["x3 mesh", "x3mesh"],
        "xrwood": ["xr wood", "xrwood"],
        "cg580": ["cg 580", "cg580"],
        "ch170": ["ch 170", "ch170"],
        "ch360": ["ch 360", "ch360"],
        "ch160": ["ch 160", "ch160"],
        "matrexx30": ["matrexx 30", "matrexx30"],
    }.get(series_query, [series_query])


def hdd_norm_article(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def is_strong_hdd_paren_code(token):
    norm = hdd_norm_article(token)
    if len(norm) < 6:
        return False
    if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
        return False
    blocked = {
        "sataiii", "usb300", "usb301", "usb302", "usb310", "usb311", "usb312", "usb320",
        "6gbps", "12gbps", "7200rpm", "5400rpm", "5640rpm", "1000rpm",
        "256mb", "512mb", "128mb", "64mb",
        "rtl", "oem", "bulk",
    }
    return norm not in blocked


def hdd_brand_model_key(text, raw_paren_article_tokens=None, is_spec_code=None):
    raw = str(text or "").strip()
    if not raw:
        return empty_hdd_key()
    raw_paren_article_tokens = raw_paren_article_tokens or (lambda value: [])
    is_spec_code = is_spec_code or (lambda value: False)
    low = raw.lower()
    if re.search(r"\bnvme\b|\bm\.2\b|твердотельн", low, flags=re.IGNORECASE):
        return empty_hdd_key()

    brand = ""
    brand_patterns = [
        ("wd", r"(?:^|[^a-z0-9])wd(?:$|[^a-z0-9])|western\s*digital"),
        ("seagate", r"(?:^|[^a-z0-9])seagate(?=$|[^a-z0-9])"),
        ("toshiba", r"(?:^|[^a-z0-9])toshiba(?=$|[^a-z0-9])"),
        ("adata", r"(?:^|[^a-z0-9])a-?data(?=$|[^a-z0-9])|(?:^|[^a-z0-9])adata(?=$|[^a-z0-9])"),
        ("netac", r"(?:^|[^a-z0-9])netac(?=$|[^a-z0-9])"),
        ("hgst", r"(?:^|[^a-z0-9])hgst(?=$|[^a-z0-9])"),
        ("hitachi", r"(?:^|[^a-z0-9])hitachi(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            brand = value
            break

    code = _extract_hdd_code(raw, raw_paren_article_tokens, is_spec_code)
    if not brand and code:
        brand = _infer_hdd_brand_from_code(code)

    capacity = _extract_hdd_capacity(low)
    form = ""
    if re.search(r"2\s*[.,]\s*5\s*\"|2\s*,\s*5\s*\"", low, flags=re.IGNORECASE):
        form = "25"
    elif re.search(r"3\s*[.,]\s*5\s*\"|3\s*,\s*5\s*\"", low, flags=re.IGNORECASE):
        form = "35"

    external = bool(re.search(r"внешн|portable", low, flags=re.IGNORECASE))
    return {
        "brand": brand,
        "code": code,
        "capacity": capacity,
        "external": external,
        "form": form,
    }


def empty_hdd_key():
    return {"brand": "", "code": "", "capacity": "", "external": False, "form": ""}


def looks_like_hdd_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.search(r"\bnvme\b|\bm\.2\b|твердотельн", low, flags=re.IGNORECASE):
        return False
    if re.search(r"(?:^|[^a-z0-9])ssd(?:$|[^a-z0-9])", low, flags=re.IGNORECASE) and not re.search(
        r"\bhdd\b|жестк|винчест|hard\s*drive", low, flags=re.IGNORECASE
    ):
        return False
    if re.search(r"\bhdd\b|жестк|винчест|hard\s*drive", low, flags=re.IGNORECASE):
        return True
    if re.search(r"внешний\s+накопитель", low, flags=re.IGNORECASE) and re.search(
        r"\bhdd\b", low, flags=re.IGNORECASE
    ):
        return True
    return False


def find_hdd_review_candidates(
    product_name,
    top_n=5,
    db_connection=None,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    infer_category=None,
    normalize_catalog_category_name=None,
    raw_paren_article_tokens=None,
    is_spec_code=None,
):
    name = str(product_name or "").strip()
    if not name:
        return []
    key_kwargs = {
        "raw_paren_article_tokens": raw_paren_article_tokens,
        "is_spec_code": is_spec_code,
    }
    local = hdd_brand_model_key(name, **key_kwargs)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    if not local_code and not local_brand:
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = _fetch_hdd_seed_rows(conn, local_code, local_brand)
            seed_best = {}
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid:
                    continue
                category_ok = normalize_catalog_category_name(infer_category(raw_name)) == "Жесткий диск"
                prev = seed_best.get(oid)
                if prev is None:
                    seed_best[oid] = (raw_name, url, category_ok)
                    continue
                prev_name, _prev_url, prev_ok = prev
                if (
                    category_ok and not prev_ok
                    or category_ok == prev_ok and len(str(raw_name or "")) > len(str(prev_name or ""))
                ):
                    seed_best[oid] = (raw_name, url, category_ok)
            for oid, (raw_name, url, category_ok) in seed_best.items():
                if category_ok:
                    pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "hdd_db_seed"})
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
        classified = _classify_hdd_candidate(
            candidate,
            seen,
            local,
            key_kwargs,
            infer_category,
            normalize_catalog_category_name,
        )
        if not classified:
            continue
        seen.add(classified["id"])
        items.append(classified)

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_code:
        exact_items = [
            item for item in items
            if case_code_match(local_code, str(item.get("code", "") or "").strip())
        ]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _fetch_hdd_seed_rows(conn, local_code, local_brand):
    rows = []
    if local_code:
        rows.extend(conn.execute(
            "SELECT ni.onliner_id, ni.raw_name, oc.url "
            "FROM name_index ni "
            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
            "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
            "LIMIT 180",
            (f"%{local_code}%",),
        ).fetchall())
    if local_brand and len(rows) < 90:
        rows.extend(conn.execute(
            "SELECT ni.onliner_id, ni.raw_name, oc.url "
            "FROM name_index ni "
            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
            "WHERE lower(ni.raw_name) LIKE ? "
            "LIMIT 220",
            (f"%{local_brand.lower()}%",),
        ).fetchall())
    return rows


def _classify_hdd_candidate(candidate, seen, local, key_kwargs, infer_category, normalize_catalog_category_name):
    if not isinstance(candidate, dict):
        return None
    cid = normalize_onliner_id(candidate.get("id", ""))
    candidate_name = str(candidate.get("name", "") or "").strip()
    if not cid or not candidate_name or cid in seen:
        return None
    if normalize_catalog_category_name(infer_category(candidate_name)) != "Жесткий диск":
        return None
    candidate_low = candidate_name.lower()
    if re.search(r"\bnvme\b|\bm\.2\b|твердотельн", candidate_low, flags=re.IGNORECASE):
        return None

    candidate_hdd = hdd_brand_model_key(candidate_name, **key_kwargs)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_capacity = str(local.get("capacity", "") or "").strip()
    local_external = bool(local.get("external"))
    local_form = str(local.get("form", "") or "").strip()
    candidate_code = str(candidate_hdd.get("code", "") or "").strip()
    candidate_brand = str(candidate_hdd.get("brand", "") or "").strip()
    candidate_capacity = str(candidate_hdd.get("capacity", "") or "").strip()
    candidate_external = bool(candidate_hdd.get("external"))
    candidate_form = str(candidate_hdd.get("form", "") or "").strip()

    if local_brand and candidate_brand and candidate_brand != local_brand:
        return None
    if local_code and candidate_code and not case_code_match(local_code, candidate_code):
        return None
    if local_capacity and candidate_capacity and local_capacity.lower() != candidate_capacity.lower():
        return None
    if local_external != candidate_external:
        return None
    if local_form and candidate_form and local_form != candidate_form:
        return None

    score = max(float(candidate.get("score", 0.0) or 0.0), 0.88)
    if local_code and candidate_code and case_code_match(local_code, candidate_code):
        score = 0.999

    return {
        "id": cid,
        "name": candidate_name,
        "url": str(candidate.get("url", "") or "").strip(),
        "score": round(min(0.999, max(0.0, score)), 3),
        "source": str(candidate.get("source", "hdd_db")).strip() or "hdd_db",
        "code": candidate_code,
        "capacity": candidate_capacity,
    }


def _extract_hdd_code(raw, raw_paren_article_tokens, is_spec_code):
    for code_match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{4,80})\)", raw):
        token = str(code_match.group(1) or "").strip()
        if is_strong_hdd_paren_code(token):
            return hdd_norm_article(token)
    for token in raw_paren_article_tokens(raw):
        if is_strong_hdd_paren_code(token):
            return hdd_norm_article(token)
    for token in re.findall(r"\b([A-Za-z0-9][A-Za-z0-9.\-/]{6,40})\b", raw):
        if is_spec_code(hdd_norm_article(token).upper()):
            continue
        if is_strong_hdd_paren_code(token):
            return hdd_norm_article(token)
    return ""


def _infer_hdd_brand_from_code(code):
    if code.startswith("st") and len(code) >= 8:
        return "seagate"
    if code.startswith(("wd", "wu")):
        return "wd"
    if code.startswith(("mg", "mq", "hdwd", "hdtb", "dt")):
        return "toshiba"
    if code.startswith(("ahd", "ahv")):
        return "adata"
    if code.startswith("nt0"):
        return "netac"
    return ""


def _extract_hdd_capacity(low):
    capacity = ""
    for capacity_match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*(tb|gb|тб|гб)\b", low, flags=re.IGNORECASE):
        if not capacity_match.group(1) or not capacity_match.group(2):
            continue
        tail = low[capacity_match.end():capacity_match.end() + 3]
        if tail.startswith("/"):
            continue
        unit = capacity_match.group(2).lower()
        if unit == "тб":
            unit = "tb"
        elif unit == "гб":
            unit = "gb"
        capacity = f"{capacity_match.group(1)}{unit}"
    return capacity


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

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_article:
        exact_items = [
            item for item in items
            if case_code_match(local_article, str(item.get("code", "") or "").strip())
        ]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _fetch_printer_seed_rows(conn, local_article, local_brand, local_model):
    rows = []
    if local_article:
        rows.extend(conn.execute(
            "SELECT ni.onliner_id, ni.raw_name, oc.url "
            "FROM name_index ni "
            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
            "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
            "LIMIT 180",
            (f"%{local_article}%",),
        ).fetchall())
    if local_brand and len(rows) < 90:
        rows.extend(conn.execute(
            "SELECT ni.onliner_id, ni.raw_name, oc.url "
            "FROM name_index ni "
            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
            "WHERE lower(ni.raw_name) LIKE ? "
            "LIMIT 220",
            (f"%{local_brand.lower()}%",),
        ).fetchall())
    if local_model and len(local_model) >= 6 and len(rows) < 140:
        rows.extend(conn.execute(
            "SELECT ni.onliner_id, ni.raw_name, oc.url "
            "FROM name_index ni "
            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
            "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
            "LIMIT 180",
            (f"%{local_model}%",),
        ).fetchall())
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


def cooler_norm_article(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def cooler_paren_looks_socket_bundle(token):
    text = str(token or "").strip().lower()
    if not text:
        return True
    if re.match(r"^\d", text):
        return True
    if text.count("/") >= 2 and re.search(r"\b(lga|am\d|fm\d)\b", text):
        return True
    if re.search(r"\d{2,4}\s*шт\s*/", text):
        return True
    return False


def is_strong_cooler_paren_code(token):
    raw_token = str(token or "").strip()
    if not raw_token or re.match(r"^\d+$", raw_token):
        return False
    norm = cooler_norm_article(raw_token)
    if len(norm) < 4 or not any(ch.isalpha() for ch in norm):
        return False
    blocked = {"sataiii", "usb320", "usb310", "rtl", "oem", "bulk", "ret", "box"}
    return norm not in blocked


def cooler_brand_model_key(text, raw_paren_article_tokens=None):
    raw = str(text or "").strip()
    if not raw:
        return empty_cooler_key()
    raw_paren_article_tokens = raw_paren_article_tokens or (lambda value: [])
    low = raw.lower()
    is_case_fan = bool(re.search(r"вентилятор|fan|комплект\s+вентиляторов|набор\s+\d+\s*в\s*\d+", low, flags=re.IGNORECASE))
    if re.search(r"\bкорпус\b|\bбез\s+бп\b", low, flags=re.IGNORECASE) and not is_case_fan:
        return empty_cooler_key()

    brand = _extract_cooler_brand(low)
    code = _extract_cooler_code(raw, raw_paren_article_tokens)
    if not brand and code:
        brand = _infer_cooler_brand_from_code(low, code)

    tdp = ""
    tdp_match = re.search(r"\btdp\s*(\d{2,4})\s*w\b", low, flags=re.IGNORECASE)
    if tdp_match and tdp_match.group(1):
        tdp = str(int(tdp_match.group(1)))
    if not tdp:
        tdp_match = re.search(r"\b(\d{2,4})\s*w\s*tdp\b", low, flags=re.IGNORECASE)
        if tdp_match and tdp_match.group(1):
            tdp = str(int(tdp_match.group(1)))

    colors = _cooler_colors(low)
    return {"brand": brand, "code": code, "tdp": tdp, "colors": colors, "white": "white" in colors}


def empty_cooler_key():
    return {"brand": "", "code": "", "tdp": "", "colors": set(), "white": False}


def cooler_catalog_category_ok(raw_name, infer_category=None, normalize_catalog_category_name=None):
    raw_name = str(raw_name or "")
    low = raw_name.lower()
    category = ""
    if infer_category and normalize_catalog_category_name:
        try:
            category = normalize_catalog_category_name(infer_category(raw_name))
        except Exception:
            category = ""
    if category == "Кулер":
        return True
    if category == "Охлаждение":
        if re.search(r"вентилятор|fan|комплект\s+вентиляторов|набор\s+\d+\s*в\s*\d+", low, flags=re.IGNORECASE):
            return True
        if re.search(r"кулер|для\s*процессора|cpu\s*cooler", low, flags=re.IGNORECASE):
            return True
        if re.search(
            r"жидкостн|\bсжо\b|водян|water\s*cool|all[\s\-]in[\s\-]one|"
            r"freezer|levante|dashflow|eskimo|frozen\s+|aqua\s+elite|"
            r"насос|\bpump\b|240mm|280mm|360mm|420mm|2x120mm|3x120mm|3x140mm",
            low,
            flags=re.IGNORECASE,
        ):
            return True
    return False


def cooler_seed_rank(raw_name, infer_category=None, normalize_catalog_category_name=None):
    raw_name = str(raw_name or "")
    category = ""
    if infer_category and normalize_catalog_category_name:
        try:
            category = normalize_catalog_category_name(infer_category(raw_name))
        except Exception:
            category = ""
    if category == "Кулер":
        base = 100
    elif category == "Охлаждение":
        base = 50
    else:
        base = 0
    return base + min(80, len(raw_name))


def looks_like_cooler_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    is_case_fan = bool(re.search(r"вентилятор|fan|комплект\s+вентиляторов|набор\s+\d+\s*в\s*\d+", low, flags=re.IGNORECASE))
    if re.search(r"\bжестк|\bhdd\b", low, flags=re.IGNORECASE):
        return False
    if re.search(r"\bкорпус\b", low, flags=re.IGNORECASE) and not is_case_fan:
        return False
    if is_case_fan:
        return True
    if re.match(r"^\s*кулер\b", low, flags=re.IGNORECASE):
        return True
    return bool(re.search(r"\bcpu\s*cooler\b|\bдля\s*процессора\b.*\bкулер\b", low, flags=re.IGNORECASE))


def looks_like_liquid_cpu_cooling_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if re.search(r"\bкорпус\b|\bжестк|\bhdd\b|\bssd\b", low, flags=re.IGNORECASE):
        return False
    if re.search(
        r"система\s+водяного\s+охлаждения|водяного\s+охлаждения\b|"
        r"\bсжо\b|жидкостн(?:ое|ая|ые)?\s+охлажден|водян(?:ое|ая|ые)?\s+охлажден",
        low,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(r"\ball[\s\-]in[\s\-]one\b|\baio\b|liquid\s+(freezer|cool)|water\s*cool", low, flags=re.IGNORECASE):
        return True
    return bool(re.search(
        r"\b(dashflow|levante|eskimo|lightflow|liquid\s+freezer|freezer\s+iii)\b|"
        r"\bfrozen\s+(edge|horizon|infinity|magic|notte|prism|warframe)\b|"
        r"\baqua\s+elite\b|\bcore\s+matrix\b|\bturbo\s+right\b|\bnitro\+|"
        r"\bid[\s\-]*cooling\s+(sl|dashflow|dx|fx)\w",
        low,
        flags=re.IGNORECASE,
    ))


def find_cooler_review_candidates(
    product_name,
    top_n=5,
    db_connection=None,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    infer_category=None,
    normalize_catalog_category_name=None,
    raw_paren_article_tokens=None,
):
    name = str(product_name or "").strip()
    if not name:
        return []
    key_kwargs = {"raw_paren_article_tokens": raw_paren_article_tokens}
    local = cooler_brand_model_key(name, **key_kwargs)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    if not local_code and not local_brand:
        return []

    pool = []
    try:
        with db_connection() as conn:
            rows = _fetch_cooler_seed_rows(conn, local_code, local_brand)
            seed_map = {}
            for oid, raw_name, url in rows:
                oid = normalize_onliner_id(oid)
                if not oid:
                    continue
                if not cooler_catalog_category_ok(raw_name, infer_category, normalize_catalog_category_name):
                    continue
                rank = cooler_seed_rank(raw_name, infer_category, normalize_catalog_category_name)
                prev = seed_map.get(oid)
                if prev is None or rank > prev[2]:
                    seed_map[oid] = (raw_name, url, rank)
            for oid, (raw_name, url, _rank) in seed_map.items():
                pool.append({"id": oid, "name": raw_name, "url": url, "score": 0.91, "source": "cooler_db_seed"})
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
    local_is_liquid = looks_like_liquid_cpu_cooling_name(name)
    for candidate in pool:
        classified = _classify_cooler_candidate(
            candidate,
            seen,
            local,
            local_is_liquid,
            key_kwargs,
            infer_category,
            normalize_catalog_category_name,
        )
        if not classified:
            continue
        seen.add(classified["id"])
        items.append(classified)

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    if local_code:
        exact_items = [
            item for item in items
            if case_code_match(local_code, str(item.get("code", "") or "").strip())
        ]
        if exact_items:
            items = exact_items
    return items[:max(1, int(top_n))]


def _fetch_cooler_seed_rows(conn, local_code, local_brand):
    rows = []
    if local_code:
        rows.extend(conn.execute(
            "SELECT ni.onliner_id, ni.raw_name, oc.url "
            "FROM name_index ni "
            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
            "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
            "LIMIT 200",
            (f"%{local_code}%",),
        ).fetchall())
    if local_brand and len(rows) < 90:
        for brand_query in _cooler_brand_queries(local_brand):
            rows.extend(conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE lower(ni.raw_name) LIKE ? "
                "LIMIT 220",
                (f"%{brand_query.lower()}%",),
            ).fetchall())
    return rows


def _classify_cooler_candidate(
    candidate,
    seen,
    local,
    local_is_liquid,
    key_kwargs,
    infer_category,
    normalize_catalog_category_name,
):
    if not isinstance(candidate, dict):
        return None
    cid = normalize_onliner_id(candidate.get("id", ""))
    candidate_name = str(candidate.get("name", "") or "").strip()
    if not cid or not candidate_name or cid in seen:
        return None
    if not cooler_catalog_category_ok(candidate_name, infer_category, normalize_catalog_category_name):
        return None
    candidate_low = candidate_name.lower()
    if not local_is_liquid:
        if re.search(r"жидкостн|\bсжо\b|водян", candidate_low, flags=re.IGNORECASE) and "кулер" not in candidate_low:
            return None

    candidate_cooler = cooler_brand_model_key(candidate_name, **key_kwargs)
    local_code = str(local.get("code", "") or "").strip()
    local_brand = str(local.get("brand", "") or "").strip()
    local_tdp = str(local.get("tdp", "") or "").strip()
    candidate_code = str(candidate_cooler.get("code", "") or "").strip()
    candidate_brand = str(candidate_cooler.get("brand", "") or "").strip()
    candidate_tdp = str(candidate_cooler.get("tdp", "") or "").strip()

    if local_brand and candidate_brand and candidate_brand != local_brand:
        return None
    normalized_name = cooler_norm_article(candidate_name)
    if local_code:
        if candidate_code:
            if not case_code_match(local_code, candidate_code):
                return None
        elif len(local_code) >= 5:
            if local_code not in normalized_name:
                if local_brand == "cryorig":
                    match = re.match(r"^crh(\d+)", local_code)
                    if not (match and f"h{match.group(1)}" in normalized_name):
                        return None
                else:
                    return None

    local_colors = set(local.get("colors") or set())
    candidate_colors = set(candidate_cooler.get("colors") or set())
    if local_colors and candidate_colors and not (local_colors & candidate_colors):
        return None
    if local_tdp and candidate_tdp:
        try:
            if abs(int(local_tdp) - int(candidate_tdp)) > 25:
                return None
        except Exception:
            pass

    score = max(float(candidate.get("score", 0.0) or 0.0), 0.88)
    if local_code and candidate_code and case_code_match(local_code, candidate_code):
        score = 0.999

    return {
        "id": cid,
        "name": candidate_name,
        "url": str(candidate.get("url", "") or "").strip(),
        "score": round(min(0.999, max(0.0, score)), 3),
        "source": str(candidate.get("source", "cooler_db")).strip() or "cooler_db",
        "code": candidate_code,
        "tdp": candidate_tdp,
    }


def _extract_cooler_brand(low):
    brand_patterns = [
        ("deepcool", r"deep\s*cool|deepcool"),
        ("cryorig", r"(?:^|[^a-z0-9])cryorig(?=$|[^a-z0-9])"),
        ("idcooling", r"id[\s\-]*cooling|(?:^|[^a-z0-9])id\s+cooling"),
        ("montech", r"(?:^|[^a-z0-9])montech(?=$|[^a-z0-9])"),
        ("xpg", r"\bxpg\b"),
        ("adata", r"\badata\b"),
        ("geometricfuture", r"geometric\s*future|geometricfuture"),
        ("sapphire", r"\bsapphire\b"),
        ("thermalright", r"thermal\s*right|thermalright"),
        ("arctic", r"arctic\s*cooling|(?:^|[^a-z0-9])arctic(?=$|[^a-z0-9])"),
        ("alseye", r"(?:^|[^a-z0-9])alseye(?=$|[^a-z0-9])"),
        ("noctua", r"(?:^|[^a-z0-9])noctua(?=$|[^a-z0-9])"),
        ("bequiet", r"be\s*quiet|bequiet"),
        ("zalman", r"(?:^|[^a-z0-9])zalman(?=$|[^a-z0-9])"),
    ]
    for value, pattern in brand_patterns:
        if re.search(pattern, low, flags=re.IGNORECASE):
            return value
    return ""


def _extract_cooler_code(raw, raw_paren_article_tokens):
    for code_match in re.finditer(r"\(([A-Za-z0-9][A-Za-z0-9.\-/]{3,80})\)", raw):
        token = str(code_match.group(1) or "").strip()
        if cooler_paren_looks_socket_bundle(token):
            continue
        if is_strong_cooler_paren_code(token):
            return cooler_norm_article(token)
    for token in raw_paren_article_tokens(raw):
        if cooler_paren_looks_socket_bundle(token):
            continue
        if is_strong_cooler_paren_code(token):
            return cooler_norm_article(token)
    for pattern in _COOLER_INLINE_CODE_PATTERNS:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match and match.group(1):
            candidate = str(match.group(1) or "").strip()
            if is_strong_cooler_paren_code(candidate):
                return cooler_norm_article(candidate)
    return ""


_COOLER_INLINE_CODE_PATTERNS = [
    r"\b(R-[A-Za-z0-9\-]{6,40})\b",
    r"\b(CR-[A-Za-z0-9\-]{2,24})\b",
    r"\b(AF-\d{3}(?:-[A-Z0-9]+)+)\b",
    r"\b(TL-[A-Z0-9]{1,12}(?:-[A-Z0-9]+)*)\b",
    r"\b(AX\d{3}(?:\s+[A-Z]+)?)\b",
    r"\b(RX\d{3}(?:\s+[A-Z]+)?)\b",
    r"\b(ICEFAN\s+\d{3}(?:\s+[A-Z]+)*)\b",
    r"\b(CRYSTAL\s+\d{3}(?:\s+[A-Z]+)*)\b",
    r"\b(VENTO\s+R\s+\d{3}X?\d?\s+ARGB\s+PWM)\b",
    r"\b(MACHO-[A-Z0-9\-]{2,24})\b",
    r"\b(ACALP[a-z0-9]{4,20})\b",
    r"\b(AS-[A-Z0-9\-]{2,20})\b",
    r"\b(SE-\d{3}(?:-[A-Z0-9]{2,})+)\b",
    r"\b(IS-\d{2}[A-Z]*(?:-[A-Z]{2,})?)\b",
    r"\b(DK-\d{2}[A-Z]?)\b",
    r"\b(AG\d{3})\b",
    r"\b(AK\d{3})\b",
    r"\b(NX\d{3})\b",
    r"\b(FROZN\s+A\d{3}(?:\s+[A-Z]+)*)\b",
    r"\b(LEVANTE[A-Z0-9\-]{4,36})\b",
    r"\b(ACFRE\d{5}[A-Z]?)\b",
    r"\b(F-[A-Z0-9\-]{4,40})\b",
    r"\b(A-ELITE[A-Z0-9\-]{2,36})\b",
    r"\b(C-MATRIX[A-Z0-9\-]{2,24})\b",
    r"\b(TURBO-RIGHT-[A-Z0-9\-]{2,24})\b",
    r"\b(4N\d{3}-\d{2}-\d{2}[A-Z])\b",
    r"\b(1C[0-9A-Z]{8,14})\b",
]


def _infer_cooler_brand_from_code(low, code):
    if re.search(r"deep\s*cool|deepcool", low, flags=re.IGNORECASE):
        return "deepcool"
    if re.search(r"id[\s\-]*cooling|id\s+cooling", low, flags=re.IGNORECASE):
        return "idcooling"
    if re.search(r"cryorig", low, flags=re.IGNORECASE) or code.startswith("cr"):
        return "cryorig"
    if re.search(r"thermal\s*right|thermalright|macho", low, flags=re.IGNORECASE) or code.startswith("macho"):
        return "thermalright"
    if code.startswith("acalp") or re.search(r"alpine", low, flags=re.IGNORECASE):
        return "arctic"
    if re.search(r"montech", low, flags=re.IGNORECASE) or code.startswith("nx"):
        return "montech"
    if re.search(r"alseye", low, flags=re.IGNORECASE):
        return "alseye"
    if re.search(r"\blevante\b|levanteii", low, flags=re.IGNORECASE) or "levante" in code:
        return "xpg"
    if code.upper().startswith("ACFRE") or re.search(r"liquid\s+freezer|freezer\s+iii", low, flags=re.IGNORECASE):
        return "arctic"
    if re.search(r"geometric|eskimo", low, flags=re.IGNORECASE) or re.match(r"^1c", code, flags=re.IGNORECASE):
        return "geometricfuture"
    if re.search(r"\bsapphire\b|nitro\+", low, flags=re.IGNORECASE) or code.upper().startswith("4N"):
        return "sapphire"
    return ""


def _cooler_colors(low):
    color_map = {
        "black": [r"(?:^|[^a-z0-9])black(?=$|[^a-z0-9])", r"\bbk\b", r"черн"],
        "white": [r"(?:^|[^a-z0-9])white(?=$|[^a-z0-9])", r"\bwh\b", r"\bwh\s", r"бел"],
        "gray": [r"(?:^|[^a-z0-9])grey(?=$|[^a-z0-9])", r"(?:^|[^a-z0-9])gray(?=$|[^a-z0-9])", r"сер"],
    }
    colors = set()
    for color_key, patterns in color_map.items():
        for pattern in patterns:
            if re.search(pattern, low, flags=re.IGNORECASE):
                colors.add(color_key)
                break
    return colors


def _cooler_brand_queries(brand):
    return {
        "bequiet": ["be quiet", "bequiet"],
        "idcooling": ["id-cooling", "id cooling", "idcooling"],
        "xpg": ["xpg", "adata xpg"],
        "geometricfuture": ["geometric future", "geometricfuture"],
    }.get(brand, [brand])


def looks_like_peripheral_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    return bool(re.search(
        r"клавиатур|keyboard|мышь|мыши|mouse|гарнитур|наушник|headset|headphones|колонк|акустик|speaker|soundbar",
        low,
        flags=re.IGNORECASE,
    ))


def peripheral_catalog_category_ok(raw_name, infer_category=None, normalize_catalog_category_name=None):
    raw_name = str(raw_name or "").strip()
    if not raw_name:
        return False
    category = ""
    if infer_category and normalize_catalog_category_name:
        try:
            category = normalize_catalog_category_name(infer_category(raw_name))
        except Exception:
            category = ""
    if category in {"Клавиатура", "Мышь", "Наушники", "Акустика"}:
        return True
    return looks_like_peripheral_name(raw_name)


def find_peripheral_review_candidates(
    product_name,
    top_n=5,
    db_find_top_candidates=None,
    db_find_exact_id_for_name=None,
    infer_category=None,
    normalize_catalog_category_name=None,
):
    name = str(product_name or "").strip()
    if not name:
        return []

    pool = []
    if db_find_exact_id_for_name:
        exact = db_find_exact_id_for_name(name)
        if exact:
            pool.append(exact)
    if db_find_top_candidates:
        pool.extend(db_find_top_candidates(name, top_n=25, min_score=0.18, allow_b2b=False))

    items = []
    seen = set()
    for candidate in pool:
        if not isinstance(candidate, dict):
            continue
        cid = normalize_onliner_id(candidate.get("id", ""))
        candidate_name = str(candidate.get("name", "") or "").strip()
        if not cid or not candidate_name or cid in seen:
            continue
        if not peripheral_catalog_category_ok(candidate_name, infer_category, normalize_catalog_category_name):
            continue
        score = float(candidate.get("score", 0.0) or 0.0)
        if score < 0.25 and not str(candidate.get("source", "")).startswith("exact"):
            continue
        seen.add(cid)
        items.append({
            "id": cid,
            "name": candidate_name,
            "url": str(candidate.get("url", "") or "").strip(),
            "score": round(min(0.999, max(0.0, score)), 3),
            "source": str(candidate.get("source", "peripheral_db")).strip() or "peripheral_db",
        })

    items.sort(key=lambda item: (
        -(float(item.get("score", 0.0) or 0.0)),
        str(item.get("name", "") or "").lower(),
    ))
    return items[:max(1, int(top_n))]
