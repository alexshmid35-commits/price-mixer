"""Onliner B2B OAuth, catalog cache, and price-position helpers."""

import base64
import re
import threading
import time

import requests

from price_mixer.settings import _coerce_bool, _coerce_int, load_app_settings

B2B_TOKEN_LOCK = threading.RLock()
B2B_TOKEN_CACHE = {"access_token": "", "expires_at": 0}
B2B_CATALOG_LOCK = threading.RLock()
B2B_CATALOG_CACHE = {
    "sections": {"ts": 0, "items": []},
    "manufacturers": {},
    "products": {},
    "articles": {},
}


def normalize_onliner_id(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def get_onliner_b2b_settings():
    settings = load_app_settings()
    cfg = (settings.get("onliner_b2b") or {})
    return {
        "enabled": _coerce_bool(cfg.get("enabled", False), default=False),
        "base_url": str(cfg.get("base_url", "https://b2bapi.onliner.by") or "https://b2bapi.onliner.by").strip(),
        "price_api_base_url": str(cfg.get("price_api_base_url") or "https://price.api.onliner.by").strip(),
        "client_id": str(cfg.get("client_id", "") or "").strip(),
        "client_secret": str(cfg.get("client_secret", "") or "").strip(),
        "token_url": str(cfg.get("token_url", "https://b2bapi.onliner.by/oauth/token") or "https://b2bapi.onliner.by/oauth/token").strip(),
        "verify_ssl": _coerce_bool(cfg.get("verify_ssl", True), default=True),
        "timeout_sec": _coerce_int(cfg.get("timeout_sec", 20), 20, min_value=5, max_value=120),
    }


def invalidate_onliner_b2b_token():
    with B2B_TOKEN_LOCK:
        B2B_TOKEN_CACHE["access_token"] = ""
        B2B_TOKEN_CACHE["expires_at"] = 0


def onliner_b2b_get_token(force_refresh=False):
    cfg = get_onliner_b2b_settings()
    if not cfg.get("enabled"):
        raise RuntimeError("Onliner B2B API выключен в настройках.")
    client_id = str(cfg.get("client_id", "") or "").strip()
    client_secret = str(cfg.get("client_secret", "") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Не заполнены Client ID / Client Secret для Onliner B2B API.")

    now = int(time.time())
    with B2B_TOKEN_LOCK:
        cached_token = str(B2B_TOKEN_CACHE.get("access_token", "") or "").strip()
        cached_expires_at = int(B2B_TOKEN_CACHE.get("expires_at", 0) or 0)
        if (not force_refresh) and cached_token and cached_expires_at - now > 30:
            return {
                "access_token": cached_token,
                "expires_at": cached_expires_at,
                "expires_in": max(0, cached_expires_at - now),
                "token_type": "Bearer",
                "source": "cache",
            }

    pair = f"{client_id}:{client_secret}"
    basic = base64.b64encode(pair.encode("utf-8")).decode("ascii")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {basic}",
    }
    resp = requests.post(
        str(cfg.get("token_url") or "https://b2bapi.onliner.by/oauth/token"),
        headers=headers,
        data={"grant_type": "client_credentials"},
        verify=bool(cfg.get("verify_ssl", True)),
        timeout=int(cfg.get("timeout_sec", 20) or 20),
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    access_token = str(payload.get("access_token", "") or "").strip()
    expires_in = _coerce_int(payload.get("expires_in", 300), 300, min_value=60, max_value=86400)
    token_type = str(payload.get("token_type", "Bearer") or "Bearer").strip() or "Bearer"
    if not access_token:
        raise RuntimeError("Onliner B2B API не вернул access_token.")
    expires_at = int(time.time()) + int(expires_in)
    with B2B_TOKEN_LOCK:
        B2B_TOKEN_CACHE["access_token"] = access_token
        B2B_TOKEN_CACHE["expires_at"] = expires_at
    return {
        "access_token": access_token,
        "expires_at": expires_at,
        "expires_in": expires_in,
        "token_type": token_type,
        "source": "oauth",
    }


def onliner_b2b_request(method, path, params=None, json_body=None, force_token_refresh=False):
    cfg = get_onliner_b2b_settings()
    token_info = onliner_b2b_get_token(force_refresh=force_token_refresh)
    base_url = str(cfg.get("base_url", "https://b2bapi.onliner.by") or "https://b2bapi.onliner.by").rstrip("/")
    rel_path = "/" + str(path or "").lstrip("/")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token_info['access_token']}",
    }
    return requests.request(
        method=str(method or "GET").upper(),
        url=base_url + rel_path,
        headers=headers,
        params=params,
        json=json_body,
        verify=bool(cfg.get("verify_ssl", True)),
        timeout=int(cfg.get("timeout_sec", 20) or 20),
    )


def onliner_b2b_price_request(method, path, params=None, json_body=None, force_token_refresh=False):
    """HTTP to price-list API, default host price.api.onliner.by."""
    cfg = get_onliner_b2b_settings()
    token_info = onliner_b2b_get_token(force_refresh=force_token_refresh)
    base_url = str(cfg.get("price_api_base_url", "https://price.api.onliner.by") or "https://price.api.onliner.by").rstrip("/")
    rel_path = "/" + str(path or "").lstrip("/")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token_info['access_token']}",
    }
    return requests.request(
        method=str(method or "GET").upper(),
        url=base_url + rel_path,
        headers=headers,
        params=params,
        json=json_body,
        verify=bool(cfg.get("verify_ssl", True)),
        timeout=int(cfg.get("timeout_sec", 20) or 20),
    )


def normalize_b2b_dict_items(payload):
    if isinstance(payload, list):
        out = []
        for idx, item in enumerate(payload):
            if isinstance(item, dict):
                entry = dict(item)
                if "id" not in entry and idx is not None:
                    entry["id"] = str(idx)
                out.append(entry)
        return out
    if not isinstance(payload, dict):
        return []
    out = []
    numeric_like_keys = []
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip()
        if re.fullmatch(r"\d+", key or ""):
            numeric_like_keys.append(key)
        if isinstance(raw_value, dict):
            entry = dict(raw_value)
            entry.setdefault("id", key)
            out.append(entry)
        else:
            out.append({"id": key, "name": str(raw_value or "").strip()})
    if numeric_like_keys and len(numeric_like_keys) == len(payload):
        return out
    for nested_key in ("items", "data", "results", "sections", "manufacturers", "products"):
        nested = payload.get(nested_key)
        if isinstance(nested, (list, dict)):
            items = normalize_b2b_dict_items(nested)
            if items:
                return items
    return out


def b2b_cache_get(bucket, key=None, ttl=3600):
    now = int(time.time())
    with B2B_CATALOG_LOCK:
        holder = B2B_CATALOG_CACHE.get(bucket)
        if key is None:
            if isinstance(holder, dict) and now - int(holder.get("ts", 0) or 0) <= ttl:
                return holder.get("items")
            return None
        if isinstance(holder, dict):
            item = holder.get(str(key))
            if isinstance(item, dict) and now - int(item.get("ts", 0) or 0) <= ttl:
                return item.get("items")
    return None


def b2b_cache_set(bucket, items, key=None):
    payload = {"ts": int(time.time()), "items": items if isinstance(items, list) else []}
    with B2B_CATALOG_LOCK:
        if key is None:
            B2B_CATALOG_CACHE[bucket] = payload
        else:
            if not isinstance(B2B_CATALOG_CACHE.get(bucket), dict):
                B2B_CATALOG_CACHE[bucket] = {}
            B2B_CATALOG_CACHE[bucket][str(key)] = payload


def onliner_b2b_get_sections(force_refresh=False):
    cached = None if force_refresh else b2b_cache_get("sections", ttl=12 * 3600)
    if isinstance(cached, list):
        return cached
    resp = onliner_b2b_request("GET", "/sections", force_token_refresh=force_refresh)
    resp.raise_for_status()
    items = normalize_b2b_dict_items(resp.json() if resp.content else {})
    b2b_cache_set("sections", items)
    return items


def onliner_b2b_get_manufacturers(section_id, force_refresh=False):
    sid = str(section_id or "").strip()
    if not sid:
        return []
    cached = None if force_refresh else b2b_cache_get("manufacturers", key=sid, ttl=12 * 3600)
    if isinstance(cached, list):
        return cached
    resp = onliner_b2b_request("GET", f"/sections/{sid}/manufacturers", force_token_refresh=force_refresh)
    resp.raise_for_status()
    items = normalize_b2b_dict_items(resp.json() if resp.content else {})
    b2b_cache_set("manufacturers", items, key=sid)
    return items


def onliner_b2b_get_products(section_id, manufacturer_id, title="", force_refresh=False):
    sid = str(section_id or "").strip()
    mid = str(manufacturer_id or "").strip()
    title = str(title or "").strip()
    if not sid or not mid:
        return []
    cache_key = f"{sid}|{mid}|{title.lower()}"
    cached = None if force_refresh else b2b_cache_get("products", key=cache_key, ttl=6 * 3600)
    if isinstance(cached, list):
        return cached
    params = {"title": title} if title else None
    resp = onliner_b2b_request("GET", f"/sections/{sid}/manufacturers/{mid}/products", params=params, force_token_refresh=force_refresh)
    resp.raise_for_status()
    items = normalize_b2b_dict_items(resp.json() if resp.content else {})
    b2b_cache_set("products", items, key=cache_key)
    return items


def onliner_b2b_get_articles(section_id, manufacturer_id, product_id, force_refresh=False):
    sid = str(section_id or "").strip()
    mid = str(manufacturer_id or "").strip()
    pid = normalize_onliner_id(product_id)
    if not sid or not mid or not pid:
        return []
    cache_key = f"{sid}|{mid}|{pid}"
    cached = None if force_refresh else b2b_cache_get("articles", key=cache_key, ttl=24 * 3600)
    if isinstance(cached, list):
        return cached
    resp = onliner_b2b_request("GET", f"/sections/{sid}/manufacturers/{mid}/products/{pid}/articles", force_token_refresh=force_refresh)
    resp.raise_for_status()
    raw_items = resp.json() if resp.content else []
    items = []
    for item in (raw_items if isinstance(raw_items, list) else []):
        if isinstance(item, dict):
            art = str(item.get("article", "") or "").strip()
        else:
            art = str(item or "").strip()
        if art:
            items.append(art)
    b2b_cache_set("articles", items, key=cache_key)
    return items


def onliner_b2b_fetch_product_positions_export(section_id, manufacturer_id, product_id, force_token_refresh=False):
    """GET .../products/{productId}/positions from price-list export API."""
    sid = str(section_id or "").strip()
    mid = str(manufacturer_id or "").strip()
    pid = normalize_onliner_id(product_id)
    if not sid or not mid or not pid:
        return []
    rel = f"/sections/{sid}/manufacturers/{mid}/products/{pid}/positions"
    resp = onliner_b2b_price_request("GET", rel, force_token_refresh=force_token_refresh)
    resp.raise_for_status()
    payload = resp.json() if resp.content else []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        pos = payload.get("positions")
        if isinstance(pos, list):
            return [x for x in pos if isinstance(x, dict)]
    return normalize_b2b_dict_items(payload)


def _safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def parse_b2b_price_string(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        value = float(raw)
        return value if value > 0 else None
    if isinstance(raw, dict):
        for key in ("amount", "value", "BYN", "byn", "converted"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                price = parse_b2b_price_string(nested.get("amount") or nested.get("value"))
                if price is not None and price > 0:
                    return price
            else:
                price = parse_b2b_price_string(nested)
                if price is not None and price > 0:
                    return price
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace(" ", "").replace(",", ".")
    return _safe_float(text)


def b2b_row_price_value(row):
    """Extract price from a B2B position row with several possible JSON/XML fields."""
    if not isinstance(row, dict):
        return None
    for key in ("pricePromo", "price_promo", "promoPrice"):
        price = parse_b2b_price_string(row.get(key))
        if price is not None and price > 0:
            return float(price)
    for key in ("price", "Price", "cost", "amount"):
        price = parse_b2b_price_string(row.get(key))
        if price is not None and price > 0:
            return float(price)
    return None


def market_stats_from_b2b_position_rows(rows):
    if not isinstance(rows, list):
        rows = []
    if not rows:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": "b2b: нет позиций в ответе",
        }
    prices = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = b2b_row_price_value(row)
        if price is not None and price > 0:
            prices.append(float(price))
    if not prices:
        return {
            "min": None, "avg": None, "max": None, "offers": 0,
            "min_competitors": 0, "avg_competitors": 0,
            "_error": True,
            "_error_reason": "b2b: позиции есть, но не удалось прочитать цену (поля price / pricePromo)",
        }
    offers_count = len(prices)
    min_price = float(min(prices))
    max_price = float(max(prices))
    avg_price = round(float(sum(prices)) / len(prices), 2)
    min_competitors = sum(1 for price in prices if price <= min_price * 1.02)
    avg_competitors = sum(1 for price in prices if abs(price - avg_price) <= max(1.0, avg_price * 0.05))
    return {
        "min": round(min_price, 2),
        "avg": avg_price,
        "max": round(max_price, 2),
        "offers": offers_count,
        "min_competitors": int(min_competitors),
        "avg_competitors": int(avg_competitors),
        "_error": False,
        "_error_reason": "",
    }


def b2b_market_stats_error(reason):
    return {
        "min": None,
        "avg": None,
        "max": None,
        "offers": 0,
        "min_competitors": 0,
        "avg_competitors": 0,
        "_error": True,
        "_error_reason": str(reason or ""),
    }


def fetch_market_stats_b2b(
    onliner_id,
    *,
    product_name="",
    category_name="",
    get_settings=get_onliner_b2b_settings,
    resolve_catalog_path=None,
    fetch_positions=onliner_b2b_fetch_product_positions_export,
    stats_from_rows=market_stats_from_b2b_position_rows,
):
    """Fetch market stats from B2B price positions with consistent error payloads."""
    oid = normalize_onliner_id(onliner_id)
    if not oid:
        return b2b_market_stats_error("пустой onliner id")

    cfg = get_settings() if callable(get_settings) else {}
    if not cfg.get("enabled"):
        return b2b_market_stats_error("b2b выключен в настройках")
    if not str(cfg.get("client_id", "") or "").strip() or not str(cfg.get("client_secret", "") or "").strip():
        return b2b_market_stats_error("b2b: не заданы client_id / client_secret")

    resolver = resolve_catalog_path or resolve_catalog_path_for_product
    try:
        section_id, manufacturer_id = resolver(
            oid,
            product_name=product_name,
            category_name=category_name,
        )
    except Exception as exc:
        return b2b_market_stats_error(f"b2b resolve: {str(exc)[:120]}")

    if not section_id or not manufacturer_id:
        return b2b_market_stats_error(
            "b2b: не найден раздел/производитель для товара (нужно название в прайсе или в локальной базе)"
        )

    try:
        rows = fetch_positions(section_id, manufacturer_id, oid)
    except Exception as exc:
        return b2b_market_stats_error(f"b2b positions: {str(exc)[:160]}")
    return stats_from_rows(rows)


def b2b_section_tokens(category_name, product_name=""):
    alias_map = {
        "Процессор": ["процессор", "cpu"],
        "Кулер": ["кулер", "cooler"],
        "Охлаждение": ["охлаждение", "водяное охлаждение"],
        "Материнская плата": ["материнская плата"],
        "Оперативная память": ["оперативная память", "память ddr", "dram"],
        "SSD": ["ssd"],
        "Жесткий диск": ["жесткий диск", "hdd"],
        "Видеокарта": ["видеокарта"],
        "Блок питания": ["блок питания", "psu"],
        "Корпус": ["корпус"],
        "Монитор": ["монитор"],
        "Кронштейны": ["кронштейн", "vesa", "mount"],
        "Ноутбук": ["ноутбук"],
        "Системный блок": ["системный блок", "компьютер"],
        "Клавиатура": ["клавиатура"],
        "Мышь": ["мышь"],
        "Наушники": ["наушники", "гарнитура"],
        "Акустика": ["акустика", "колонки"],
        "Сеть": ["роутер", "сеть", "wifi"],
        "Накопители USB": ["usb накопитель", "флешка"],
        "Кабели и переходники": ["кабель", "переходник", "адаптер"],
        "Аксессуары": ["аксессуары"],
    }
    tokens = []
    try:
        from price_mixer.services.product_normalization import infer_category, normalize_catalog_category_name

        inferred = normalize_catalog_category_name(category_name or infer_category(product_name or ""))
    except Exception:
        inferred = str(category_name or "").strip()
        if not inferred:
            text = str(product_name or "").lower()
            for category, aliases in alias_map.items():
                if any(alias in text for alias in aliases):
                    inferred = category
                    break
    if inferred:
        tokens.extend(alias_map.get(inferred, [inferred.lower()]))
    raw_cat = str(category_name or "").strip().lower()
    if raw_cat and raw_cat not in tokens:
        tokens.append(raw_cat)
    out = []
    seen = set()
    for token in tokens:
        key = str(token or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def resolve_catalog_path_for_product(
    target_oid,
    product_name="",
    category_name="",
    force_refresh=False,
    *,
    get_product_by_id=None,
    preferred_brand_token=None,
    extract_article=None,
    priority_model_queries=None,
    name_tokens=None,
    get_settings=get_onliner_b2b_settings,
    get_sections=onliner_b2b_get_sections,
    get_manufacturers=onliner_b2b_get_manufacturers,
    get_products=onliner_b2b_get_products,
    cache_get=b2b_cache_get,
    cache_set=b2b_cache_set,
    section_tokens=b2b_section_tokens,
):
    """Resolve an Onliner product ID to B2B section/manufacturer IDs."""
    cfg = get_settings()
    if not cfg.get("enabled"):
        return None, None
    oid = normalize_onliner_id(target_oid)
    if not oid:
        return None, None
    cache_key = str(oid)
    if not force_refresh:
        cached = cache_get("product_path", key=cache_key, ttl=7 * 24 * 3600)
        if isinstance(cached, list) and len(cached) >= 2 and cached[0] and cached[1]:
            return str(cached[0]), str(cached[1])

    name = str(product_name or "").strip()
    if not name and callable(get_product_by_id):
        product = get_product_by_id(oid)
        if isinstance(product, dict):
            name = str(product.get("name", "") or "").strip()
    if not name:
        return None, None

    try:
        sections = get_sections()
    except Exception:
        return None, None

    tokens = section_tokens(str(category_name or "").strip(), name)
    candidate_sections = []
    for section in sections:
        sec_id = str((section or {}).get("id", "") or "").strip()
        sec_name = str((section or {}).get("name", "") or "").strip()
        if not sec_id or not sec_name:
            continue
        low_name = sec_name.lower()
        score = 0
        for token in tokens:
            if token and token in low_name:
                score = max(score, len(token))
        if score > 0:
            candidate_sections.append((score, sec_id, sec_name))
    candidate_sections.sort(key=lambda item: item[0], reverse=True)
    candidate_sections = candidate_sections[:6] if candidate_sections else []
    if not candidate_sections and sections:
        candidate_sections = [
            (
                0,
                str((sections[i] or {}).get("id", "") or "").strip(),
                str((sections[i] or {}).get("name", "") or ""),
            )
            for i in range(min(8, len(sections)))
            if str((sections[i] or {}).get("id", "") or "").strip()
        ]

    brand = str(preferred_brand_token(name) if callable(preferred_brand_token) else "").strip()
    queries = []
    seen_queries = set()

    def _add_query(value):
        query = str(value or "").strip()
        if not query:
            return
        key = query.lower()
        if key in seen_queries:
            return
        seen_queries.add(key)
        queries.append(query)

    article = str(extract_article(name) if callable(extract_article) else "").strip()
    if article:
        _add_query(article)
    if callable(priority_model_queries):
        for query in priority_model_queries(name)[:2]:
            _add_query(query)
    if callable(name_tokens):
        _add_query(" ".join(name_tokens(name)[:6]))
    _add_query(name[:90])
    queries = queries[:4]

    for _score, sec_id, _sec_name in candidate_sections:
        try:
            manufacturers = get_manufacturers(sec_id)
        except Exception:
            continue
        if brand:
            matching_manufacturers = [
                manufacturer for manufacturer in manufacturers
                if brand.lower() in str((manufacturer or {}).get("name", "") or "").lower()
            ]
        else:
            matching_manufacturers = list(manufacturers[:6])
        if not matching_manufacturers:
            matching_manufacturers = list(manufacturers[:8])
        for manufacturer in matching_manufacturers[:10]:
            mid = str((manufacturer or {}).get("id", "") or "").strip()
            if not mid:
                continue
            try:
                products_full = get_products(sec_id, mid, title="")
            except Exception:
                products_full = []
            for index, product in enumerate(products_full):
                if index >= 12000:
                    break
                if not isinstance(product, dict):
                    continue
                pid = normalize_onliner_id(product.get("id", ""))
                if pid == oid:
                    cache_set("product_path", [sec_id, mid], key=cache_key)
                    return str(sec_id), str(mid)
            for query in queries:
                try:
                    products = get_products(sec_id, mid, title=query)
                except Exception:
                    continue
                for product in products[:160]:
                    if not isinstance(product, dict):
                        continue
                    pid = normalize_onliner_id(product.get("id", ""))
                    if pid == oid:
                        cache_set("product_path", [sec_id, mid], key=cache_key)
                        return str(sec_id), str(mid)
    return None, None


def search_candidates(
    local_name,
    category_name="",
    limit=30,
    *,
    get_settings=get_onliner_b2b_settings,
    get_sections=onliner_b2b_get_sections,
    get_manufacturers=onliner_b2b_get_manufacturers,
    get_products=onliner_b2b_get_products,
    get_articles=onliner_b2b_get_articles,
    section_tokens=b2b_section_tokens,
    preferred_brand_token=None,
    extract_article=None,
    priority_model_queries=None,
    name_tokens=None,
    article_like_tokens=None,
    strict_candidate_allowed=None,
    calc_name_match=None,
    get_product_by_id=None,
    normalize_compact_name=None,
    upsert_product=None,
):
    """Search B2B catalog candidates for a local product name."""
    cfg = get_settings()
    if not cfg.get("enabled"):
        return []
    name = str(local_name or "").strip()
    if not name:
        return []
    try:
        sections = get_sections()
    except Exception:
        return []

    tokens = section_tokens(category_name, name)
    candidate_sections = []
    for section in sections:
        sec_id = str((section or {}).get("id", "") or "").strip()
        sec_name = str((section or {}).get("name", "") or "").strip()
        if not sec_id or not sec_name:
            continue
        low_name = sec_name.lower()
        score = 0
        for token in tokens:
            if token and token in low_name:
                score = max(score, len(token))
        if score > 0:
            candidate_sections.append((score, sec_id, sec_name))
    candidate_sections.sort(key=lambda item: item[0], reverse=True)
    candidate_sections = candidate_sections[:3] if candidate_sections else []
    if not candidate_sections and sections:
        first = sections[0] or {}
        candidate_sections = [(0, str(first.get("id", "")).strip(), str(first.get("name", "")).strip())]

    brand = str(preferred_brand_token(name) if callable(preferred_brand_token) else "").strip()
    queries = []
    seen_queries = set()

    def _add_query(value):
        query = str(value or "").strip()
        if not query:
            return
        key = query.lower()
        if key in seen_queries:
            return
        seen_queries.add(key)
        queries.append(query)

    article = str(extract_article(name) if callable(extract_article) else "").strip()
    if article:
        _add_query(article)
    if callable(priority_model_queries):
        for query in priority_model_queries(name)[:2]:
            _add_query(query)
    if callable(name_tokens):
        _add_query(" ".join(name_tokens(name)[:6]))
    _add_query(name[:90])
    queries = queries[:3]

    local_articles = article_like_tokens(name) if callable(article_like_tokens) else set()
    candidates = {}

    for _, sec_id, _sec_name in candidate_sections:
        try:
            manufacturers = get_manufacturers(sec_id)
        except Exception:
            continue
        if brand:
            matching_manufacturers = [
                manufacturer for manufacturer in manufacturers
                if brand.lower() in str((manufacturer or {}).get("name", "") or "").lower()
            ]
        else:
            matching_manufacturers = list(manufacturers[:4])
        if not matching_manufacturers:
            matching_manufacturers = list(manufacturers[:4])

        for manufacturer in matching_manufacturers[:4]:
            mid = str((manufacturer or {}).get("id", "") or "").strip()
            if not mid:
                continue
            for query in queries:
                try:
                    products = get_products(sec_id, mid, title=query)
                except Exception:
                    continue
                for product in products[:20]:
                    pid = normalize_onliner_id((product or {}).get("id", ""))
                    pname = str((product or {}).get("name", "") or "").strip()
                    if not pid or not pname:
                        continue
                    if pid in candidates:
                        continue
                    if callable(strict_candidate_allowed):
                        allowed, _reason = strict_candidate_allowed(name, pname)
                        if not allowed:
                            continue
                    cmp = calc_name_match(name, pname) if callable(calc_name_match) else {"score": 0.0, "match": False, "reason": ""}
                    score = float(cmp.get("score", 0.0) or 0.0)
                    if cmp.get("match"):
                        score = max(score, 0.76)
                    purl = ""
                    if callable(get_product_by_id):
                        cached_product = get_product_by_id(pid)
                        if isinstance(cached_product, dict):
                            purl = str(cached_product.get("url", "") or "").strip()
                    article_hits = []
                    if local_articles and score >= 0.45:
                        try:
                            article_hits = get_articles(sec_id, mid, pid)
                        except Exception:
                            article_hits = []
                    if callable(normalize_compact_name):
                        remote_articles = {
                            normalize_compact_name(article)
                            for article in article_hits
                            if str(article or "").strip()
                        }
                    else:
                        remote_articles = {str(article or "").strip().lower() for article in article_hits if str(article or "").strip()}
                    if local_articles and remote_articles:
                        if local_articles.intersection(remote_articles):
                            score = max(score, 0.98)
                        else:
                            score *= 0.55
                    if score < 0.34:
                        continue
                    candidates[pid] = {
                        "id": pid,
                        "name": pname,
                        "url": purl,
                        "score": round(float(score), 3),
                        "source": "b2b",
                        "reason": str(cmp.get("reason", "") or ""),
                    }
                    if callable(upsert_product):
                        upsert_product(pid, pname, purl, source="b2b")
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    items = list(candidates.values())
    items.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
    return items[:limit]
