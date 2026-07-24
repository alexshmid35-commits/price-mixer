"""Category-specific review matching for hdd."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.services.review_matching.case import case_code_match


def hdd_norm_article(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def is_strong_hdd_paren_code(token):
    norm = hdd_norm_article(token)
    if len(norm) < 6:
        return False
    if not any(ch.isalpha() for ch in norm) or not any(ch.isdigit() for ch in norm):
        return False
    blocked = {
        "sataiii",
        "usb300",
        "usb301",
        "usb302",
        "usb310",
        "usb311",
        "usb312",
        "usb320",
        "6gbps",
        "12gbps",
        "7200rpm",
        "5400rpm",
        "5640rpm",
        "1000rpm",
        "256mb",
        "512mb",
        "128mb",
        "64mb",
        "rtl",
        "oem",
        "bulk",
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
    if re.search(r"внешний\s+накопитель", low, flags=re.IGNORECASE) and re.search(r"\bhdd\b", low, flags=re.IGNORECASE):
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
                    category_ok
                    and not prev_ok
                    or category_ok == prev_ok
                    and len(str(raw_name or "")) > len(str(prev_name or ""))
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


def _fetch_hdd_seed_rows(conn, local_code, local_brand):
    rows = []
    if local_code:
        rows.extend(
            conn.execute(
                "SELECT ni.onliner_id, ni.raw_name, oc.url "
                "FROM name_index ni "
                "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                "LIMIT 180",
                (f"%{local_code}%",),
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
        tail = low[capacity_match.end() : capacity_match.end() + 3]
        if tail.startswith("/"):
            continue
        unit = capacity_match.group(2).lower()
        if unit == "тб":
            unit = "tb"
        elif unit == "гб":
            unit = "gb"
        capacity = f"{capacity_match.group(1)}{unit}"
    return capacity
