import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

from price_mixer.runtime_paths import get_runtime_paths
from price_mixer.services.product_normalization import normalize_onliner_id
from price_mixer.state_store import load_dict, save_dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATHS = get_runtime_paths()

ONLINER_MARKET_CACHE_FILE = RUNTIME_PATHS.cache_file("onliner_market_cache.json")
ONLINER_PRODUCT_CACHE_FILE = RUNTIME_PATHS.cache_file("onliner_product_cache.json")
ONLINER_MARKET_CACHE_TTL = 24 * 3600
ONLINER_PRODUCT_CACHE_TTL = 7 * 24 * 3600
ONLINER_PRODUCT_CACHE_LOCK = threading.RLock()


def empty_market_stats():
    return {
        "min": None,
        "avg": None,
        "max": None,
        "offers": 0,
        "min_competitors": 0,
        "avg_competitors": 0,
    }


def safe_float(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def safe_int(value, default=0):
    try:
        return int(value or default)
    except Exception:
        return default


def load_onliner_market_cache():
    return load_dict(ONLINER_MARKET_CACHE_FILE)


def save_onliner_market_cache(cache):
    save_dict(ONLINER_MARKET_CACHE_FILE, cache)


def load_onliner_product_cache():
    return load_dict(ONLINER_PRODUCT_CACHE_FILE)


def save_onliner_product_cache(cache):
    save_dict(ONLINER_PRODUCT_CACHE_FILE, cache)


def extract_position_prices(payload):
    prices = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "position_price" and isinstance(value, dict):
                amount = safe_float(value.get("amount"))
                if amount is not None and amount > 0:
                    prices.append(amount)
            else:
                prices.extend(extract_position_prices(value))
    elif isinstance(payload, list):
        for item in payload:
            prices.extend(extract_position_prices(item))
    return prices


def extract_offer_rows(payload):
    payload = payload or {}
    rows = []

    shops_map = payload.get("shops") or {}
    if not isinstance(shops_map, dict):
        shops_map = {}

    def _shop_from_map(shop_id):
        sid = str(shop_id or "").strip()
        if not sid:
            return {}
        if sid in shops_map and isinstance(shops_map[sid], dict):
            return shops_map[sid]
        if sid.isdigit() and int(sid) in shops_map and isinstance(shops_map[int(sid)], dict):
            return shops_map[int(sid)]
        return {}

    def _extract_price(node):
        if isinstance(node.get("position_price"), dict):
            price = safe_float((((node.get("position_price") or {}).get("converted") or {}).get("BYN") or {}).get("amount"))
            if price is None:
                price = safe_float((node.get("position_price") or {}).get("amount"))
            if price is not None:
                return price
        if isinstance(node.get("price"), dict):
            price = safe_float((((node.get("price") or {}).get("converted") or {}).get("BYN") or {}).get("amount"))
            if price is None:
                price = safe_float((node.get("price") or {}).get("amount"))
            if price is not None:
                return price
        if "price" in node:
            return safe_float(node.get("price"))
        return None

    def _seller_info(node):
        seller_name = ""
        seller_id = str(node.get("seller_id") or node.get("shop_id") or node.get("vendor_id") or "").strip()
        seller_url = str(node.get("shop_url") or node.get("seller_url") or "").strip()

        for key in ("shop", "seller", "vendor", "merchant", "store"):
            val = node.get(key)
            if isinstance(val, dict):
                seller_name = str(val.get("title") or val.get("name") or val.get("full_name") or seller_name).strip()
                seller_id = str(val.get("id") or val.get("key") or seller_id).strip()
                seller_url = str(val.get("html_url") or val.get("url") or seller_url).strip()
                if seller_name or seller_id or seller_url:
                    break

        mapped = _shop_from_map(seller_id)
        if mapped:
            if not seller_name:
                seller_name = str(mapped.get("title") or mapped.get("name") or "").strip()
            if not seller_url:
                seller_url = str(mapped.get("html_url") or mapped.get("url") or "").strip()
            if not seller_id:
                seller_id = str(mapped.get("id") or "").strip()

        if not seller_name:
            seller_name = str(node.get("seller_name") or node.get("shop_name") or node.get("vendor_name") or "").strip()

        return seller_name, seller_id, seller_url

    def _append_row(node, price):
        seller_name, seller_id, seller_url = _seller_info(node)
        rows.append({
            "seller_name": seller_name or "—",
            "seller_id": seller_id,
            "seller_url": seller_url,
            "price": round(float(price), 2),
            "url": str(node.get("product_url") or node.get("html_url") or node.get("url") or seller_url or "").strip(),
            "warranty": str(node.get("warranty") or "").strip(),
            "stock": str((node.get("stock_status") or {}).get("text") or "").strip(),
            "updated_at": str(node.get("date_update") or "").strip(),
        })

    positions = payload.get("positions") or {}
    if isinstance(positions, dict):
        iter_lists = [value for value in positions.values() if isinstance(value, list)]
    elif isinstance(positions, list):
        iter_lists = [positions]
    else:
        iter_lists = []

    for items in iter_lists:
        for node in items:
            if not isinstance(node, dict):
                continue
            price = _extract_price(node)
            if price is None:
                continue
            _append_row(node, price)

    if not rows:
        def _walk(node):
            if isinstance(node, dict):
                price = _extract_price(node)
                if price is not None:
                    _append_row(node, price)
                for value in node.values():
                    _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(payload)

    dedup = []
    seen = set()
    for row in rows:
        key = (row.get("seller_id", ""), row.get("seller_name", ""), row.get("price", ""), row.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(row)
    return dedup


def market_stats_from_cache_record(cached):
    if not isinstance(cached, dict):
        return empty_market_stats()
    return {
        "min": safe_float(cached.get("min")),
        "avg": safe_float(cached.get("avg")),
        "max": safe_float(cached.get("max")),
        "offers": safe_int(cached.get("offers"), 0),
        "min_competitors": safe_int(cached.get("min_competitors"), 0),
        "avg_competitors": safe_int(cached.get("avg_competitors"), 0),
    }


def get_onliner_market_stats_from_cache_only(
    onliner_id,
    cache=None,
    allow_stale=True,
    now_fn=time.time,
    load_cache=load_onliner_market_cache,
):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return empty_market_stats()
    if cache is None:
        cache = load_cache()
    cached = cache.get(oid)
    if not isinstance(cached, dict):
        return empty_market_stats()
    if not allow_stale:
        now = int(now_fn())
        if now - safe_int(cached.get("updated_at"), 0) > ONLINER_MARKET_CACHE_TTL:
            return empty_market_stats()
    return market_stats_from_cache_record(cached)


def market_stats_has_values(stats):
    if not isinstance(stats, dict):
        return False
    if safe_float(stats.get("min")) is not None:
        return True
    if safe_float(stats.get("avg")) is not None:
        return True
    if safe_float(stats.get("max")) is not None:
        return True
    return safe_int(stats.get("offers"), 0) > 0


def market_stats_error(reason):
    payload = empty_market_stats()
    payload.update({"_error": True, "_error_reason": str(reason or "")})
    return payload


def fetch_onliner_product_payload(onliner_id, api_get):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return None, "пустой onliner id"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    product = None
    direct_error = ""
    search_error = ""
    try:
        response = api_get(
            f"https://catalog.api.onliner.by/products/{oid}",
            timeout=12,
            headers=headers,
        )
        if response.ok:
            payload = response.json() or {}
            payload_id = normalize_onliner_id(payload.get("id", ""))
            if payload_id == oid:
                product = payload
            else:
                direct_error = f"products/{oid}: mismatched id {payload_id or 'empty'}"
        else:
            direct_error = f"products/{oid}: http {response.status_code}"
    except Exception:
        direct_error = f"products/{oid}: timeout/connection"

    if not product:
        search_url = f"https://catalog.api.onliner.by/search/products?query={oid}"
        try:
            response = api_get(search_url, timeout=12, headers=headers)
            if response.ok:
                products = (response.json() or {}).get("products", [])
                for item in products:
                    if str(item.get("id", "")).strip() == oid:
                        product = item
                        break
                if product is None:
                    search_error = "search: товар не найден"
            else:
                search_error = f"search: http {response.status_code}"
        except Exception:
            search_error = "search: timeout/connection"

    if product:
        return product, ""
    reason = "; ".join([item for item in [direct_error, search_error] if item]) or "товар не найден"
    return None, reason


def fetch_onliner_market_stats_catalog_api(onliner_id, api_get):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return market_stats_error("пустой onliner id")
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    product, product_error = fetch_onliner_product_payload(oid, api_get=api_get)
    if not product:
        return market_stats_error(product_error or "товар не найден")

    prices_obj = product.get("prices") or {}
    min_price = safe_float((((prices_obj.get("price_min") or {}).get("converted") or {}).get("BYN") or {}).get("amount"))
    if min_price is None:
        min_price = safe_float((prices_obj.get("price_min") or {}).get("amount"))
    offers_count = safe_int((prices_obj.get("offers") or {}).get("count"), 0)
    avg_price = None
    max_price = None
    min_competitors = 0
    avg_competitors = 0

    positions_error = ""
    positions_url = str(prices_obj.get("url", "")).strip()
    if positions_url:
        try:
            response = api_get(positions_url, timeout=12, headers=headers)
            if response.ok:
                position_prices = extract_position_prices(response.json())
                if position_prices:
                    avg_price = round(float(sum(position_prices)) / len(position_prices), 2)
                    max_price = round(float(max(position_prices)), 2)
                    min_price = round(float(min(position_prices)), 2)
                    min_competitors = sum(1 for price in position_prices if price <= min_price * 1.02)
                    avg_competitors = sum(1 for price in position_prices if abs(price - avg_price) <= max(1.0, avg_price * 0.05))
                    if not offers_count:
                        offers_count = len(position_prices)
                else:
                    positions_error = "positions: пустой список цен"
            else:
                positions_error = f"positions: http {response.status_code}"
        except Exception:
            positions_error = "positions: timeout/connection"

    if offers_count <= 0 and min_price is not None:
        offers_count = 1

    if offers_count < 1:
        min_price = None
        avg_price = None
        max_price = None
        min_competitors = 0
        avg_competitors = 0
    elif min_price is not None:
        if avg_price is None:
            avg_price = min_price
        if max_price is None:
            max_price = min_price

    return {
        "min": None if min_price is None else round(float(min_price), 2),
        "avg": None if avg_price is None else round(float(avg_price), 2),
        "max": None if max_price is None else round(float(max_price), 2),
        "offers": offers_count,
        "min_competitors": int(min_competitors),
        "avg_competitors": int(avg_competitors),
        "_error": False,
        "_error_reason": "" if offers_count >= 1 else positions_error,
    }


def fetch_onliner_market_stats(
    onliner_id,
    product_name="",
    category_name="",
    api_get=None,
    get_b2b_settings=None,
    fetch_b2b_stats=None,
):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return market_stats_error("пустой onliner id")
    cat_stats = fetch_onliner_market_stats_catalog_api(oid, api_get=api_get)
    if market_stats_has_values(cat_stats):
        return cat_stats
    cfg = get_b2b_settings() if callable(get_b2b_settings) else {}
    if (
        cfg.get("enabled")
        and str(cfg.get("client_id", "") or "").strip()
        and str(cfg.get("client_secret", "") or "").strip()
        and callable(fetch_b2b_stats)
    ):
        b2b_stats = fetch_b2b_stats(oid, product_name=product_name, category_name=category_name)
        if market_stats_has_values(b2b_stats):
            return b2b_stats
    return cat_stats


def get_onliner_market_stats_cached(
    onliner_id,
    cache=None,
    get_product_by_id=None,
    infer_category_fn=None,
    fetch_market_stats=None,
    load_cache=load_onliner_market_cache,
    now_fn=time.time,
):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"min": None, "avg": None, "offers": 0}
    if cache is None:
        cache = load_cache()
    now = int(now_fn())
    with ONLINER_PRODUCT_CACHE_LOCK:
        cached = cache.get(oid)
    if isinstance(cached, dict) and (now - safe_int(cached.get("updated_at"), 0) <= ONLINER_MARKET_CACHE_TTL):
        return market_stats_from_cache_record(cached)
    hint_name = ""
    hint_cat = ""
    db_product = get_product_by_id(oid) if callable(get_product_by_id) else None
    if isinstance(db_product, dict):
        hint_name = str(db_product.get("name", "") or "").strip()
    if hint_name and callable(infer_category_fn):
        hint_cat = infer_category_fn(hint_name)
    stats = fetch_market_stats(oid, product_name=hint_name, category_name=hint_cat)
    cache[oid] = {"updated_at": now, **stats}
    return stats


def get_onliner_market_stats_bulk(
    onliner_ids,
    max_workers=22,
    id_hints=None,
    fetch_market_stats=None,
    load_cache=load_onliner_market_cache,
    save_cache=save_onliner_market_cache,
    now_fn=time.time,
):
    ids = [normalize_onliner_id(item) for item in onliner_ids]
    ids = [item for item in ids if item]
    if not ids:
        return {}
    cache = load_cache()
    result = {}
    pending = []
    now = int(now_fn())
    for oid in ids:
        cached = cache.get(oid)
        if isinstance(cached, dict) and (now - safe_int(cached.get("updated_at"), 0) <= ONLINER_MARKET_CACHE_TTL):
            result[oid] = market_stats_from_cache_record(cached)
        else:
            pending.append(oid)

    def _fetch_one_market(oid):
        hint = (id_hints or {}).get(oid) if id_hints else None
        if isinstance(hint, dict):
            return fetch_market_stats(
                oid,
                product_name=str(hint.get("name", "") or ""),
                category_name=str(hint.get("category", "") or ""),
            )
        return fetch_market_stats(oid)

    if pending:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_oid = {executor.submit(_fetch_one_market, oid): oid for oid in pending}
            for future in as_completed(future_to_oid):
                oid = future_to_oid[future]
                try:
                    stats = future.result()
                except Exception:
                    stats = {**empty_market_stats(), "_error": True}
                result[oid] = stats
                cache[oid] = {"updated_at": now, **stats}
        save_cache(cache)
    return result


def fetch_onliner_product_info(
    onliner_id,
    cache=None,
    force_refresh=False,
    use_cache_on_error=True,
    product_name_hint=None,
    api_get=None,
    get_product_by_id=None,
    load_cache=load_onliner_product_cache,
    now_fn=time.time,
):
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return {"name": "", "url": "", "source": "empty"}
    if cache is None:
        cache = load_cache()
    now = int(now_fn())
    cached = cache.get(oid)
    if (not force_refresh) and isinstance(cached, dict) and now - safe_int(cached.get("updated_at"), 0) <= ONLINER_PRODUCT_CACHE_TTL:
        return {
            "name": str(cached.get("name", "")).strip(),
            "url": str(cached.get("url", "")).strip(),
            "source": "cache",
        }

    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    def _cache_and_return(name, url, source):
        with ONLINER_PRODUCT_CACHE_LOCK:
            cache[oid] = {"updated_at": now, "name": name, "url": url}
        return {"name": name, "url": url, "source": source}

    db_product = get_product_by_id(oid) if callable(get_product_by_id) else None
    if isinstance(db_product, dict) and str(db_product.get("name", "")).strip():
        return _cache_and_return(
            str(db_product.get("name", "")).strip(),
            str(db_product.get("url", "")).strip(),
            "db",
        )

    def _search_by_id_fallback():
        try:
            response = api_get(
                f"https://catalog.api.onliner.by/search/products?query={oid}",
                timeout=12,
                headers=headers,
            )
            if not response.ok:
                return None
            products = (response.json() or {}).get("products") or []
            for item in products:
                if str(item.get("id", "")).strip() == oid:
                    return {
                        "name": str(item.get("full_name") or item.get("name") or "").strip(),
                        "url": str(item.get("html_url") or "").strip(),
                    }
            return None
        except Exception:
            return None

    def _search_by_name_fallback(name_hint):
        if not name_hint:
            return None
        try:
            response = api_get(
                f"https://catalog.api.onliner.by/search/products?query={quote(name_hint[:80])}",
                timeout=12,
                headers=headers,
            )
            if not response.ok:
                return None
            products = (response.json() or {}).get("products") or []
            for item in products:
                if str(item.get("id", "")).strip() == oid:
                    return {
                        "name": str(item.get("full_name") or item.get("name") or "").strip(),
                        "url": str(item.get("html_url") or "").strip(),
                    }
            return None
        except Exception:
            return None

    try:
        response = api_get(
            f"https://catalog.api.onliner.by/products/{oid}",
            timeout=8,
            headers=headers,
        )
        if response.ok:
            payload = response.json() or {}
            payload_numeric_id = normalize_onliner_id(payload.get("id", ""))
            payload_key = str(payload.get("key", "")).strip()
            id_match = (payload_numeric_id == oid) or (payload_key == oid)
            name = str(payload.get("full_name") or payload.get("name") or "").strip()
            url = str(payload.get("html_url") or "").strip()
            if id_match and name:
                return _cache_and_return(name, url, "api")

        fallback = _search_by_id_fallback()
        if fallback and fallback.get("name"):
            return _cache_and_return(fallback["name"], fallback.get("url", ""), "search_by_id")

        fallback_by_name = _search_by_name_fallback(product_name_hint)
        if fallback_by_name and fallback_by_name.get("name"):
            return _cache_and_return(fallback_by_name["name"], fallback_by_name.get("url", ""), "search_by_name")

        if use_cache_on_error and isinstance(cached, dict):
            return {
                "name": str(cached.get("name", "")).strip(),
                "url": str(cached.get("url", "")).strip(),
                "source": "cache_fallback_http_error",
            }
        return {"name": "", "url": "", "source": "http_error"}

    except Exception:
        fallback = _search_by_id_fallback()
        if fallback and fallback.get("name"):
            return _cache_and_return(fallback["name"], fallback.get("url", ""), "search_by_id_after_error")
        fallback_by_name = _search_by_name_fallback(product_name_hint)
        if fallback_by_name and fallback_by_name.get("name"):
            return _cache_and_return(fallback_by_name["name"], fallback_by_name.get("url", ""), "search_by_name_after_error")
        if use_cache_on_error and isinstance(cached, dict):
            return {
                "name": str(cached.get("name", "")).strip(),
                "url": str(cached.get("url", "")).strip(),
                "source": "cache_fallback_error",
            }
        return {"name": "", "url": "", "source": "error"}
