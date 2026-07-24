"""Category-specific review matching for board."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id


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
        re.search(
            r"(?:^|[^a-z0-9])wi[\s-]?fi(?:\s*\d+[a-z]*)?(?=$|[^a-z0-9])", model_feature_source, flags=re.IGNORECASE
        )
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
            pool.extend(
                db_find_top_candidates(
                    f"{brand_query} {model_text}",
                    top_n=25,
                    min_score=0.10,
                    allow_b2b=False,
                )
                or []
            )
        if model_text:
            pool.extend(
                db_find_top_candidates(
                    model_text,
                    top_n=20,
                    min_score=0.10,
                    allow_b2b=False,
                )
                or []
            )
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
        model_close = bool(
            candidate_model and local_model and (candidate_model in local_model or local_model in candidate_model)
        )
        if not model_exact and not model_close:
            continue

        score = _score_board_candidate(candidate, local, candidate_board, model_exact, model_close)
        candidate_features = set(candidate_board.get("features") or set())
        seen.add(cid)
        items.append(
            {
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


def _score_board_candidate(candidate, local, candidate_board, model_exact, model_close):
    score = max(float(candidate.get("score", 0.0) or 0.0), 0.90)
    if model_exact:
        score += 0.06
    elif model_close:
        score += 0.03
    if local.get("chipset") and candidate_board.get("chipset") == local.get("chipset"):
        score += 0.03
    elif (
        local.get("chipset")
        and candidate_board.get("chipset")
        and candidate_board.get("chipset") != local.get("chipset")
    ):
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
            "d4",
            "ax",
            "aorus",
            "eagle",
            "steellegend",
            "prors",
            "lightning",
            "livemixer",
            "ds3h",
            "d3hp",
            "hdv",
            "elite",
            "ud",
            "riptide",
            "tomahawk",
            "mortar",
            "strix",
            "prime",
            "gamingx",
        }
        if (local_features & strong_family) - candidate_features:
            score -= 0.10
    return score
