"""Category column, visibility, and saved markup DataFrame helpers."""

import re

import pandas as pd

GLOBAL_VISIBILITY_KEY = "__global__"

_MARKUP_CATEGORY_ALWAYS_RECHECK = {
    "SSD",
    "Накопители USB",
    "Монитор",
    "Периферия",
    "Аксессуары",
    "Системный блок",
    "БУМАГА",
    "АКСЕССУАРЫ",
    "Видеокарта",
    "Процессор",
    "Оперативная память",
    "Компьютер",
    "WEB",
    "РАЗВЕТВИТЕЛЬ",
    "Кабели и переходники",
    "Клавиатура",
    "НАБОР",
    "Наушники",
    "USB2",
    "USB3",
    "USB2.0",
    "USB3.0",
    "USB3.1",
    "USB3.2",
}


def _markup_category_needs_recheck(name, current_category):
    current = str(current_category or "").strip()
    if not current or current in _MARKUP_CATEGORY_ALWAYS_RECHECK:
        return True
    text = str(name or "").strip().lower()
    if current != "Монитор" and any(
        token in text for token in ("монитор", "ips", "hdmi", "displayport", "гц", "hz")
    ):
        return True
    return False


def _should_prefer_inferred_category(name, current_category, inferred_category):
    current = str(current_category or "").strip()
    inferred = str(inferred_category or "").strip()
    if not current or not inferred or current == inferred:
        return False
    text = str(name or "").strip().lower()
    if not text:
        return False

    if inferred == "Охлаждение" and current in {"SSD", "Накопители USB", "Монитор"} and (
        "радиатор" in text or "охлажд" in text or "термопаст" in text
    ):
        return True
    if inferred == "Монитор" and current not in {"Монитор"} and (
        "монитор" in text or "ips" in text or "hdmi" in text or "displayport" in text or "гц" in text or "hz" in text
    ):
        return True
    if inferred == "Кронштейны" and current in {"Монитор", "Периферия", "Аксессуары"} and (
        "кронштейн" in text
    ):
        return True
    if inferred == "Оперативная память" and current == "Системный блок" and _is_standalone_memory_name(text):
        return True
    if inferred == "Бумага и материалы для печати" and current == "БУМАГА":
        return True
    if inferred == "Аксессуары для серверов" and current == "АКСЕССУАРЫ":
        return True
    if inferred == "Системный блок" and current in {"Видеокарта", "SSD", "Процессор", "Оперативная память", "Компьютер"} and (
        "компьютер" in text or "моноблок" in text or "системный блок" in text or "пэвм tgpc" in text
    ):
        return True
    if inferred == "Периферия" and current in {"Накопители USB", "WEB", "РАЗВЕТВИТЕЛЬ"} and (
        "web камера" in text or "webcam" in text or "dvdrw" in text
    ):
        return True
    if inferred == "USB-хабы" and current in {"Периферия", "Кабели и переходники", "РАЗВЕТВИТЕЛЬ"} and (
        "usb-хаб" in text or "usb hub" in text or "док-станц" in text or "разветвитель usb" in text
    ):
        return True
    if inferred == "Кабели и переходники" and current in {"Периферия", "Накопители USB", "РАЗВЕТВИТЕЛЬ"} and (
        "разветвитель usb" in text or "us158" in text or "30345" in text
    ):
        return True
    if inferred == "Клавиатура" and current in {"Накопители USB", "НАБОР"} and "набор" in text:
        return True
    if inferred in {"SSD", "Жесткий диск"} and current == "Накопители USB" and (
        "ssd" in text or "hdd" in text or "жестк" in text or "винчестер" in text
    ):
        return True
    if inferred in {
        "Охлаждение",
        "Периферия",
        "Клавиатура",
        "Мышь",
        "Наушники",
        "Сеть",
        "Сверла и буры",
        "Строительный, слесарный, монтажный инструмент",
        "Наборы инструментов",
        "Наборы электроинструмента",
    } and current == "Кабели и переходники":
        return True
    if inferred in {"Клавиатура", "Мышь", "Монитор"} and current == "Периферия":
        return True
    if inferred == "Акустика" and current == "Наушники":
        return True
    if inferred in {"Системный блок", "Аксессуары"} and current == "SSD":
        return True
    if inferred == "Накопители USB" and current.upper() in {"USB2", "USB3", "USB2.0", "USB3.0", "USB3.1", "USB3.2"}:
        return True
    if current == "Компьютер" and inferred in {"Системный блок", "Кабели и переходники"}:
        return True
    return False


def _is_standalone_memory_name(text):
    text = re.sub(r"^\[[^\]]+\]\s*", "", str(text or "")).strip()
    if not re.search(r"\bddr[345]\b|оперативн|\bram\b|so[\s\-]?dimm|\bdimm\b", text):
        return False
    return not re.search(r"\bкомпьютер\b|системный\s+блок|\bпэвм\b|\btgpc\b|iven\s+(?:by|gaming|office|home|pro|ultra)|\bcore\s+i[3579]\b|\bryzen\b", text)


def get_effective_category(row, overrides=None, build_item_category_keys=None, infer_category=None):
    overrides = overrides or {}
    build_item_category_keys = build_item_category_keys or (lambda item: [])
    infer_category = infer_category or (lambda name: "")
    inferred = None
    for key in build_item_category_keys(row):
        manual = str(overrides.get(key, "")).strip()
        if manual:
            inferred = inferred if inferred is not None else infer_category(row.get("Название", ""))
            if _should_prefer_inferred_category(row.get("Название", ""), manual, inferred):
                return inferred
            return manual
    return inferred if inferred is not None else infer_category(row.get("Название", ""))


def row_category(row, overrides=None, build_item_category_keys=None, infer_category=None):
    existing = str(row.get("Категория", "")).strip()
    if existing:
        inferred = (infer_category or (lambda name: ""))(row.get("Название", ""))
        if _should_prefer_inferred_category(row.get("Название", ""), existing, inferred):
            return inferred
        return existing
    return get_effective_category(
        row,
        overrides=overrides,
        build_item_category_keys=build_item_category_keys,
        infer_category=infer_category,
    )


def ensure_category_column(df, overrides=None, build_item_category_keys=None, infer_category=None):
    df = df.copy()
    df["Категория"] = df.apply(
        lambda row: row_category(
            row,
            overrides=overrides,
            build_item_category_keys=build_item_category_keys,
            infer_category=infer_category,
        ),
        axis=1,
    )
    return df


def load_visibility_map(_session_dir, load_visibility=None):
    return load_visibility() if callable(load_visibility) else {}


def save_visibility_map(_session_dir, visibility_map, save_visibility=None):
    if callable(save_visibility):
        save_visibility(visibility_map)


def apply_saved_markups_to_df(
    df,
    load_category_markups=None,
    load_category_overrides=None,
    get_category_markup_config=None,
    calc_rrc_and_no_discount=None,
    normalize_onliner_id=None,
    get_onliner_market_stats_from_cache_only=None,
    build_item_category_keys=None,
    infer_category=None,
):
    if df.empty:
        return df
    markups = load_category_markups() if callable(load_category_markups) else {}
    if not markups:
        return df
    if "РРЦ" not in df.columns:
        df["РРЦ"] = ""
    if "Цена без скидки" not in df.columns:
        df["Цена без скидки"] = ""
    df["РРЦ"] = df["РРЦ"].astype("object")
    df["Цена без скидки"] = df["Цена без скидки"].astype("object")
    overrides = load_category_overrides() if callable(load_category_overrides) else {}
    if "Категория" in df.columns:
        categories = df["Категория"].fillna("").astype(str).str.strip().tolist()
    else:
        categories = [""] * len(df)
    prices = pd.to_numeric(df.get("Цена", pd.Series(index=df.index, dtype=float)), errors="coerce").tolist()
    names = df.get("Название", pd.Series("", index=df.index, dtype="object")).tolist()
    onliner_ids = df.get("OnlinerID", pd.Series("", index=df.index, dtype="object")).tolist()
    rrc_values = df["РРЦ"].tolist()
    no_discount_values = df["Цена без скидки"].tolist()
    config_cache = {}
    market_stats_cache = {}

    for position, index in enumerate(df.index):
        category = categories[position]
        if _markup_category_needs_recheck(names[position], category):
            category = row_category(df.iloc[position], overrides, build_item_category_keys, infer_category)
        if category not in markups:
            continue
        base_price = prices[position]
        if pd.isna(base_price):
            continue
        if category not in config_cache:
            config_cache[category] = get_category_markup_config(markups, category)
        cfg = config_cache[category]
        calc_base = float(base_price)
        if cfg.get("base_mode") in {"onliner_min", "onliner_avg", "onliner_max"}:
            oid = normalize_onliner_id(onliner_ids[position]) if callable(normalize_onliner_id) else ""
            if oid:
                if oid not in market_stats_cache:
                    market_stats_cache[oid] = (
                        get_onliner_market_stats_from_cache_only(oid)
                        if callable(get_onliner_market_stats_from_cache_only)
                        else {}
                    )
                stats = market_stats_cache[oid]
                market_key = cfg["base_mode"].removeprefix("onliner_")
                market_price = stats.get(market_key)
                if market_price is not None:
                    calc_base = float(market_price)
        rrc, no_discount_price = calc_rrc_and_no_discount(
            calc_base,
            cfg["percent"],
            threshold=cfg.get("threshold", 0.0),
            min_profit=cfg.get("min_profit", 0.0),
            no_discount_percent=cfg.get("no_discount_percent", 0.0),
        )
        rrc_values[position] = rrc
        no_discount_values[position] = no_discount_price
    df["РРЦ"] = rrc_values
    df["Цена без скидки"] = no_discount_values
    return df


def apply_visibility_filter(
    df,
    session_dir,
    load_visibility_map_func=None,
    load_category_overrides=None,
    build_item_category_keys=None,
    infer_category=None,
    normalize_supplier=None,
    normalize_category=None,
):
    if df.empty or "Название" not in df.columns:
        return df
    visibility_map = load_visibility_map_func(session_dir) if callable(load_visibility_map_func) else {}
    if not visibility_map:
        return df

    overrides = load_category_overrides() if callable(load_category_overrides) else {}
    hidden_categories = {
        category
        for categories in (visibility_map or {}).values()
        for category in categories
        if str(category or "").strip()
    }
    if callable(normalize_category):
        hidden_categories = {
            normalize_category(category)
            for category in hidden_categories
            if str(category or "").strip()
        }
    hidden_categories = {category for category in hidden_categories if str(category or "").strip()}
    if not hidden_categories:
        return df

    mask = []
    for _, row in df.iterrows():
        categories = []
        existing = str(row.get("Категория", "")).strip()
        if existing:
            categories.append(existing)
        effective = row_category(row, overrides, build_item_category_keys, infer_category)
        if effective:
            categories.append(effective)
        if callable(normalize_category):
            categories = [normalize_category(category) for category in categories]
        categories = [category for category in categories if str(category or "").strip()]
        mask.append(not any(category in hidden_categories for category in categories))
    return df[pd.Series(mask, index=df.index)].copy()


def update_category_visibility(payload, visibility_map, *, category_sort_key):
    payload = payload or {}
    categories = payload.get("categories", [])
    hidden = bool(payload.get("hidden", True))

    if not isinstance(categories, list):
        return {"status": "error", "message": "Некорректный список категорий"}, visibility_map, 400

    categories = [str(item).strip() for item in categories if str(item).strip()]
    if not categories:
        return {"status": "error", "message": "Категории не выбраны"}, visibility_map, 400

    hidden_set = {
        str(category).strip()
        for saved_categories in (visibility_map or {}).values()
        for category in saved_categories
        if str(category).strip()
    }
    if hidden:
        hidden_set.update(categories)
    else:
        hidden_set.difference_update(categories)

    visibility_map = {}
    if hidden_set:
        visibility_map[GLOBAL_VISIBILITY_KEY] = sorted(hidden_set, key=category_sort_key)

    categories_out = [{"name": name, "hidden": True} for name in hidden_set]
    categories_out.sort(key=lambda item: (
        1 if item.get("hidden") else 0,
        category_sort_key(str(item.get("name", "")).strip()),
    ))
    return {
        "status": "ok",
        "supplier": GLOBAL_VISIBILITY_KEY,
        "hidden": hidden,
        "categories": categories_out,
    }, visibility_map, 200


def build_category_override_items_payload(
    df,
    *,
    query,
    limit,
    overrides,
    build_item_category_key,
    infer_category,
    row_category,
):
    if df is None or df.empty or "Название" not in df.columns:
        return {"items": []}

    query = str(query or "").strip().lower()
    try:
        limit = int(limit)
    except Exception:
        limit = 40
    limit = max(1, min(limit, 200))

    result = []
    for _, row in df.iterrows():
        name = str(row.get("Название", ""))
        if not name:
            continue
        if query and query not in name.lower():
            continue
        auto_category = infer_category(name)
        effective_category = row_category(row, overrides)
        result.append({
            "key": build_item_category_key(row),
            "name": name,
            "supplier": str(row.get("Поставщик", "")),
            "auto_category": auto_category,
            "category": effective_category,
            "manual": effective_category != auto_category,
        })
        if len(result) >= limit:
            break
    return {"items": result}


def apply_category_override_to_df(
    df,
    payload,
    *,
    overrides,
    build_item_category_keys,
    explicit_overrides=None,
):
    payload = payload or {}
    item_key = str(payload.get("item_key", "")).strip()
    item_keys = payload.get("item_keys", [])
    target_category = str(payload.get("target_category", "")).strip()

    if not isinstance(item_keys, list):
        item_keys = []
    selected_keys = {str(key).strip() for key in item_keys if str(key).strip()}
    if item_key:
        selected_keys.add(item_key)
    if not selected_keys:
        return {"status": "error", "message": "Товар не выбран"}, df, overrides, 0
    if not target_category:
        return {"status": "error", "message": "Категория не выбрана"}, df, overrides, 0

    overrides = dict(overrides or {})
    explicit = dict(explicit_overrides or {})
    expanded_keys = set(selected_keys)

    matching_rows = []
    if df is not None:
        row_keys = [(index, set(build_item_category_keys(row))) for index, row in df.iterrows()]
        while True:
            before = len(expanded_keys)
            for _, keys in row_keys:
                if expanded_keys.intersection(keys):
                    expanded_keys.update(keys)
            if len(expanded_keys) == before:
                break
        matching_rows = [(index, keys) for index, keys in row_keys if expanded_keys.intersection(keys)]

    for key in expanded_keys:
        overrides[key] = target_category
        explicit[key] = target_category

    for index, _ in matching_rows:
        df.at[index, "Категория"] = target_category
    if explicit_overrides is not None:
        explicit_overrides.clear()
        explicit_overrides.update(explicit)
    return {"status": "ok"}, df, overrides, len(matching_rows)


def build_category_preview_items_payload(
    df,
    payload,
    *,
    overrides,
    row_category,
    build_item_category_key,
    normalize_onliner_id,
    load_market_cache,
    get_market_stats_from_cache_only,
):
    payload = payload or {}
    categories = payload.get("categories", [])
    selected = {str(category).strip() for category in categories if str(category).strip()}
    category_filters = payload.get("category_filters", [])
    selected_filters = {
        (
            str(item.get("category", "")).strip(),
            str(item.get("id_mode", "all")).strip().lower() or "all",
        )
        for item in category_filters
        if isinstance(item, dict) and str(item.get("category", "")).strip()
    }
    if not selected or df is None or df.empty:
        return {"items": []}

    with_market = bool(payload.get("with_market", False))
    allow_stale_market = bool(payload.get("allow_stale_market", True))
    try:
        limit = int(payload.get("limit", 4000))
    except Exception:
        limit = 4000
    limit = max(1, min(limit, 10000))
    try:
        max_market_checks = int(payload.get("max_market_checks", 300))
    except Exception:
        max_market_checks = 300
    max_market_checks = max(1, min(max_market_checks, 800))

    items = []
    total_matches = 0
    onliner_ids = []
    for index, row in df.iterrows():
        category = row_category(row, overrides)
        if category not in selected:
            continue
        price = pd.to_numeric(row.get("Цена", float("nan")), errors="coerce")
        rrc = pd.to_numeric(row.get("РРЦ", float("nan")), errors="coerce")
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if selected_filters:
            matching_modes = {mode for selected_category, mode in selected_filters if selected_category == category}
            if not matching_modes:
                continue
            if "all" not in matching_modes:
                if oid and "with_id" not in matching_modes:
                    continue
                if not oid and "without_id" not in matching_modes:
                    continue
        total_matches += 1
        if len(items) >= limit:
            continue
        if with_market and oid:
            onliner_ids.append(oid)
        items.append({
            "key": build_item_category_key(row),
            "row_idx": int(index),
            "onliner_id": oid,
            "name": str(row.get("Название", "")),
            "supplier": str(row.get("Поставщик", "")),
            "category": category,
            "price": "" if pd.isna(price) else round(float(price), 2),
            "rrc": "" if pd.isna(rrc) else round(float(rrc), 2),
        })

    market_map = {}
    preview_row_count = len(items)
    rows_with_onliner_id = sum(1 for item in items if str(item.get("onliner_id") or "").strip())
    market_unique_onliner_ids = 0
    market_checked = 0
    if with_market and onliner_ids:
        unique_ids = list(dict.fromkeys(onliner_ids))
        if not allow_stale_market:
            unique_ids = unique_ids[:max_market_checks]
        market_unique_onliner_ids = len(unique_ids)
        market_checked = market_unique_onliner_ids
        cache = load_market_cache()
        for oid in unique_ids:
            market_map[oid] = get_market_stats_from_cache_only(
                oid,
                cache=cache,
                allow_stale=allow_stale_market,
            )

    missing_market = 0
    missing_market_ids = set()
    no_onliner_id = 0
    for item in items:
        oid = item.get("onliner_id", "")
        stats = market_map.get(oid, {}) if oid else {}
        market_min = stats.get("min")
        market_avg = stats.get("avg")
        market_max = stats.get("max")
        if with_market and not oid:
            no_onliner_id += 1
        if with_market and oid and (market_min is None and market_avg is None):
            missing_market += 1
            missing_market_ids.add(oid)
        item["market_min"] = "" if market_min is None else round(float(market_min), 2)
        item["market_avg"] = "" if market_avg is None else round(float(market_avg), 2)
        item["market_max"] = "" if market_max is None else round(float(market_max), 2)
        item["market_offers"] = int(stats.get("offers", 0) or 0) if stats else 0
        item["min_competitors"] = int(stats.get("min_competitors", 0) or 0) if stats else 0
        item["avg_competitors"] = int(stats.get("avg_competitors", 0) or 0) if stats else 0

    items.sort(key=lambda item: (item["category"], item["name"].lower()))
    return {
        "items": items,
        "total_matches": total_matches,
        "truncated": total_matches > len(items),
        "preview_row_count": preview_row_count,
        "market_rows_with_onliner_id": rows_with_onliner_id,
        "market_unique_onliner_ids": market_unique_onliner_ids,
        "market_checked": market_checked,
        "missing_market": missing_market,
        "missing_market_ids": len(missing_market_ids),
        "no_onliner_id": no_onliner_id,
    }


def _markup_calc_base(row, base_price, cfg, normalize_onliner_id, get_onliner_market_stats_from_cache_only):
    calc_base = float(base_price)
    if cfg.get("base_mode") not in {"onliner_min", "onliner_avg", "onliner_max"}:
        return calc_base
    oid = normalize_onliner_id(row.get("OnlinerID", "")) if callable(normalize_onliner_id) else ""
    stats = get_onliner_market_stats_from_cache_only(oid) if oid and callable(get_onliner_market_stats_from_cache_only) else {}
    market_price = None
    if cfg.get("base_mode") == "onliner_min":
        market_price = stats.get("min")
    elif cfg.get("base_mode") == "onliner_avg":
        market_price = stats.get("avg")
    elif cfg.get("base_mode") == "onliner_max":
        market_price = stats.get("max")
    if market_price is not None:
        calc_base = float(market_price)
    return calc_base
