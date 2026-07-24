"""Category-specific review matching for case."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.services.review_matching.features import normalize_feature_code


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
    return bool(re.search(brand_prefix, low, flags=re.IGNORECASE) and re.search(model_tokens, low, flags=re.IGNORECASE))


def case_code_match(a, b):
    a = normalize_feature_code(a)
    b = normalize_feature_code(b)
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

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    local_code = str(local.get("code", "") or "").strip()
    if local_code:
        exact_items = [item for item in items if case_code_match(local_code, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[: max(1, int(top_n))]


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
        rows.extend(
            conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                "LIMIT 200",
                (f"%{code_query}%",),
            ).fetchall()
        )
    if brand_query:
        for brand_token in _case_brand_tokens(brand_query):
            rows.extend(
                conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 220",
                    (f"%{brand_token}%",),
                ).fetchall()
            )
    if series_query:
        for series_token in _case_series_tokens(series_query):
            rows.extend(
                conn.execute(
                    "SELECT ni.onliner_id, ni.raw_name, oc.url "
                    "FROM name_index ni "
                    "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                    "WHERE lower(ni.raw_name) LIKE ? "
                    "LIMIT 180",
                    (f"%{series_token.lower()}%",),
                ).fetchall()
            )
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
    if (
        local.get("code")
        and candidate_case.get("code")
        and not case_code_match(local.get("code"), candidate_case.get("code"))
    ):
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
    if (
        local.get("code")
        and candidate_case.get("code")
        and case_code_match(local.get("code"), candidate_case.get("code"))
    ):
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
