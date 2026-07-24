"""Category-specific review matching for cooler."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.services.review_matching.case import case_code_match


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
    is_case_fan = bool(
        re.search(r"вентилятор|fan|комплект\s+вентиляторов|набор\s+\d+\s*в\s*\d+", low, flags=re.IGNORECASE)
    )
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
    is_case_fan = bool(
        re.search(r"вентилятор|fan|комплект\s+вентиляторов|набор\s+\d+\s*в\s*\d+", low, flags=re.IGNORECASE)
    )
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
    return bool(
        re.search(
            r"\b(dashflow|levante|eskimo|lightflow|liquid\s+freezer|freezer\s+iii)\b|"
            r"\bfrozen\s+(edge|horizon|infinity|magic|notte|prism|warframe)\b|"
            r"\baqua\s+elite\b|\bcore\s+matrix\b|\bturbo\s+right\b|\bnitro\+|"
            r"\bid[\s\-]*cooling\s+(sl|dashflow|dx|fx)\w",
            low,
            flags=re.IGNORECASE,
        )
    )


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

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    if local_code:
        exact_items = [item for item in items if case_code_match(local_code, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[: max(1, int(top_n))]


def _fetch_cooler_seed_rows(conn, local_code, local_brand):
    rows = []
    if local_code:
        rows.extend(
            conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                "LIMIT 200",
                (f"%{local_code}%",),
            ).fetchall()
        )
    if local_brand and len(rows) < 90:
        for brand_query in _cooler_brand_queries(local_brand):
            rows.extend(
                conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{brand_query.lower()}%",),
                ).fetchall()
            )
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
