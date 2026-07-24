"""Category-specific review matching for peripheral."""

import re

from price_mixer.services.product_normalization import normalize_onliner_id


def looks_like_peripheral_name(text):
    raw = str(text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    return bool(
        re.search(
            r"клавиатур|keyboard|мышь|мыши|mouse|гарнитур|наушник|headset|headphones|колонк|акустик|speaker|soundbar",
            low,
            flags=re.IGNORECASE,
        )
    )


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
        items.append(
            {
                "id": cid,
                "name": candidate_name,
                "url": str(candidate.get("url", "") or "").strip(),
                "score": round(min(0.999, max(0.0, score)), 3),
                "source": str(candidate.get("source", "peripheral_db")).strip() or "peripheral_db",
            }
        )

    items.sort(
        key=lambda item: (
            -(float(item.get("score", 0.0) or 0.0)),
            str(item.get("name", "") or "").lower(),
        )
    )
    return items[: max(1, int(top_n))]
