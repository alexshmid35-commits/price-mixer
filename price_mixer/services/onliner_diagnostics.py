"""Payload builders for Onliner diagnostics endpoints."""

from __future__ import annotations

import re


def _json_payload(response):
    try:
        return response.json() if response.content else {}
    except Exception:
        return {}


def _pick_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "sections", "manufacturers", "products", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = _pick_items(value)
                if nested:
                    return nested
        if payload and all(isinstance(value, dict) for value in payload.values()):
            return list(payload.values())
        numeric_like_keys = [str(key).strip() for key in payload.keys()]
        if payload and all(re.fullmatch(r"\d+", key or "") for key in numeric_like_keys):
            normalized = []
            for raw_key, raw_value in payload.items():
                item_id = str(raw_key).strip()
                if isinstance(raw_value, dict):
                    entry = dict(raw_value)
                    entry.setdefault("id", item_id)
                else:
                    entry = {"id": item_id, "name": str(raw_value or "").strip()}
                normalized.append(entry)
            return normalized
    return []


def _item_id(item):
    if not isinstance(item, dict):
        return ""
    for key in ("id", "section_id", "manufacturer_id", "product_id", "sectionId", "manufacturerId", "productId"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    urls = item.get("url") or item.get("href") or item.get("link")
    if isinstance(urls, str):
        match = re.search(r"/(\d+)(?:/)?$", urls.strip())
        if match:
            return str(match.group(1)).strip()
    return ""


def _item_name(item):
    if not isinstance(item, dict):
        return ""
    for key in ("name", "full_name", "title", "key", "slug"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def b2b_test_payload(*, get_token, b2b_request):
    try:
        token_info = get_token(force_refresh=True)
        response = b2b_request("GET", "/shop")
        preview = _json_payload(response)
        return {
            "status": "ok",
            "token_type": str(token_info.get("token_type", "Bearer") or "Bearer"),
            "expires_in": int(token_info.get("expires_in", 0) or 0),
            "http_status": int(response.status_code or 0),
            "response_preview": preview if isinstance(preview, (dict, list)) else {},
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:300]}, 400


def b2b_probe_payload(*, get_token, b2b_request):
    try:
        token_info = get_token(force_refresh=True)
        section_resp = b2b_request("GET", "/sections")
        section_payload = _json_payload(section_resp)
        sections = _pick_items(section_payload)

        result = {
            "status": "ok",
            "token_type": str(token_info.get("token_type", "Bearer") or "Bearer"),
            "expires_in": int(token_info.get("expires_in", 0) or 0),
            "sections_http_status": int(section_resp.status_code or 0),
            "sections_count": len(sections),
            "sections_sample": sections[:3] if isinstance(sections, list) else [],
            "sections_payload_type": type(section_payload).__name__,
            "sections_payload_keys": list(section_payload.keys())[:10] if isinstance(section_payload, dict) else [],
            "sections_preview": section_payload if isinstance(section_payload, (dict, list)) else {},
            "manufacturers_http_status": 0,
            "manufacturers_count": 0,
            "manufacturers_sample": [],
            "products_http_status": 0,
            "products_count": 0,
            "products_sample": [],
            "message": "",
        }

        first_section = sections[0] if sections else {}
        first_section_id = _item_id(first_section)
        if not first_section_id:
            result["message"] = "B2B вернул разделы, но не удалось выделить section id для дальнейшей проверки. Проверь sections_preview."
            return result

        manufacturers_resp = b2b_request("GET", f"/sections/{first_section_id}/manufacturers")
        manufacturers = _pick_items(_json_payload(manufacturers_resp))
        result["manufacturers_http_status"] = int(manufacturers_resp.status_code or 0)
        result["manufacturers_count"] = len(manufacturers)
        result["manufacturers_sample"] = manufacturers[:3] if isinstance(manufacturers, list) else []

        first_manufacturer = manufacturers[0] if manufacturers else {}
        first_manufacturer_id = _item_id(first_manufacturer)
        if not first_manufacturer_id:
            result["message"] = "B2B вернул производителей, но не удалось выделить manufacturer id для проверки товаров."
            return result

        products_resp = b2b_request("GET", f"/sections/{first_section_id}/manufacturers/{first_manufacturer_id}/products")
        products = _pick_items(_json_payload(products_resp))
        result["products_http_status"] = int(products_resp.status_code or 0)
        result["products_count"] = len(products)
        result["products_sample"] = products[:3] if isinstance(products, list) else []
        result["message"] = (
            "B2B данные получены. "
            f"Раздел: {_item_name(first_section) or first_section_id}; "
            f"производитель: {_item_name(first_manufacturer) or first_manufacturer_id}."
        )
        return result
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:300]}, 400


def offers_payload(onliner_id, *, normalize_onliner_id, fetch_product_payload, api_get, extract_offer_rows):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"status": "error", "message": "Пустой OnlinerID"}
    product, product_error = fetch_product_payload(oid)
    if not product:
        return {"status": "error", "message": product_error or "Товар не найден"}

    prices_obj = product.get("prices") or {}
    offers_count = int((prices_obj.get("offers") or {}).get("count") or 0)
    positions_url = str(prices_obj.get("url", "")).strip()
    if not positions_url:
        return {
            "status": "ok",
            "offers_count": offers_count,
            "positions_count": 0,
            "unique_sellers_count": 0,
            "offers": [],
            "note": "API товара найден, но детализация офферов отсутствует.",
        }

    try:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = api_get(positions_url, timeout=12, headers=headers)
        if not response.ok:
            return {"status": "error", "message": f"positions: http {response.status_code}"}
        payload = response.json() or {}
    except Exception:
        return {"status": "error", "message": "positions: timeout/connection"}

    offers = extract_offer_rows(payload)
    unique_sellers = {
        (str(row.get("seller_id", "")).strip(), str(row.get("seller_name", "")).strip())
        for row in offers
    }
    return {
        "status": "ok",
        "offers_count": offers_count,
        "positions_count": len(offers),
        "unique_sellers_count": len(unique_sellers),
        "offers": offers[:120],
        "note": "Сравните offers.count, число позиций API и уникальные магазины. На сайте Onliner цифры могут отличаться.",
    }
