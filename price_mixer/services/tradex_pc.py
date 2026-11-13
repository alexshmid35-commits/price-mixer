"""Exact WOUK desktop identities; different SKU prefixes and colors never alias."""

import re


def is_tradex_pc_name(name):
    text = re.sub(r"^\[[^\]]+\]\s*", "", str(name or "").strip())
    return bool(re.match(r"^(?:(?:компьютер|системный\s+блок|пэвм|desktop|pc)\s+)?wouk\b", text, re.I))


def extract_tradex_pc_code(name):
    if not is_tradex_pc_name(name):
        return ""
    match = re.search(r"\b([A-Z]\d{5,8}(?:BK|WH))(?![\w-])", str(name), re.I)
    return match.group(1).upper() if match else ""


def tradex_pc_match(local_name, candidate_name):
    if not is_tradex_pc_name(local_name):
        return None
    local_code = extract_tradex_pc_code(local_name)
    candidate_code = extract_tradex_pc_code(candidate_name)
    if local_code and local_code == candidate_code:
        return {"score": 1.0, "match": True, "reason": "wouk_code_exact"}
    return {"score": 0.04, "match": False, "reason": "wouk_code_mismatch"}


def find_tradex_pc_candidates(name, *, search, get_product_by_id=None, limit=12):
    code = extract_tradex_pc_code(name)
    if not code:
        return []
    candidates = {}
    for item in (search(code) or {}).get("items", []):
        if callable(get_product_by_id):
            canonical = get_product_by_id(item.get("id", "")) or {}
            if not canonical.get("name"):
                continue
            item = {**item, "name": canonical["name"], "url": canonical.get("url") or item.get("url", "")}
        match = tradex_pc_match(name, item.get("name", ""))
        oid = str(item.get("id", "") or "").strip()
        if not oid or not match or not match["match"]:
            continue
        candidates[oid] = {
            **item, **match, "source": "tradex_pc_db", "badge": "точное",
        }
    result = list(candidates.values())
    if len(result) > 1:
        for item in result:
            item.update(score=0.90, reason="wouk_ambiguous_catalog", badge="проверить")
    return result[:max(1, int(limit))]
