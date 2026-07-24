"""Category-specific review matching for psu."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id


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
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE replace(replace(replace(replace(lower(ni.raw_name), '-', ''), ' ', ''), '/', ''), '.', '') LIKE ? "
                        "LIMIT 180",
                        (f"%{code_query}%",),
                    ).fetchall()
                )
            if brand_query and watt_query:
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE lower(ni.raw_name) LIKE ? AND lower(ni.raw_name) LIKE ? "
                        "LIMIT 220",
                        (f"%{brand_query.lower()}%", f"%{watt_query}%"),
                    ).fetchall()
                )
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

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    if local_code:
        exact_items = [item for item in items if psu_code_match(local_code, str(item.get("code", "") or "").strip())]
        if exact_items:
            items = exact_items
    return items[: max(1, int(top_n))]


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
        "atx",
        "atx20",
        "atx23",
        "atx24",
        "atx30",
        "atx31",
        "nonmodular",
        "semimodular",
        "fullmodular",
        "modular",
        "activepfc",
        "apfc",
        "llcdc",
        "dcdc",
        "ret",
        "oem",
        "bulk",
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
