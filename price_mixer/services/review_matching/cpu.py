"""Category-specific review matching for cpu."""

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
        model = "pentium" + model[len("pentiumgold") :]
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
                rows.extend(
                    conn.execute(
                        "SELECT ni.onliner_id, ni.raw_name, oc.url "
                        "FROM name_index ni "
                        "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                        "WHERE ni.raw_name LIKE ? "
                        "LIMIT 80",
                        (f"%{local_code}%",),
                    ).fetchall()
                )
            if len(rows) < 80:
                numbers = re.findall(r"\d{4,5}[a-z]?", name, flags=re.IGNORECASE)
                for number in numbers[:2]:
                    if not local_brand:
                        continue
                    rows.extend(
                        conn.execute(
                            "SELECT ni.onliner_id, ni.raw_name, oc.url "
                            "FROM name_index ni "
                            "JOIN onliner_catalog oc ON oc.onliner_id = ni.onliner_id "
                            "WHERE ni.raw_name LIKE ? AND ni.raw_name LIKE ? "
                            "LIMIT 80",
                            (f"%{local_brand}%", f"%{number}%"),
                        ).fetchall()
                    )
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
        items.append(
            {
                "id": cid,
                "name": candidate_name,
                "url": str(candidate.get("url", "") or "").strip(),
                "score": final_score,
                "source": str(candidate.get("source", "cpu_db")).strip() or "cpu_db",
                "package": candidate_package,
            }
        )
    items.sort(
        key=lambda item: (
            0 if local_package and item.get("package") == local_package else 1,
            0 if local_package == "oem" and item.get("package") == "" else 1,
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    return items[: max(1, int(top_n))]


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
