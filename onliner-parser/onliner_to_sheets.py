import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import time
import re
import json
import argparse
import os
from requests.exceptions import RequestException
from pathlib import Path
from datetime import datetime, timezone
from gspread.exceptions import APIError
from http.client import RemoteDisconnected

# 🧾 Настройки Google Sheets
SCRIPT_DIR = Path(__file__).resolve().parent
PARSER_STATE_DIR = Path(os.getenv("ONLINER_PARSER_STATE_DIR", str(SCRIPT_DIR))).resolve()
PARSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_JSON_KEY_FILE = SCRIPT_DIR.parent / "ai2025-462421-df1d36f12313.json"
JSON_KEY_FILE = Path(os.getenv("ONLINER_SHEETS_KEY_FILE", str(DEFAULT_JSON_KEY_FILE)))
SPREADSHEET_ID = '11zEGNWLqcOxhlm6SubOlW2xFvjQSrJAJJaUm-ga8iHM'
SHEET_TAB = 'All_Catalog'

BASE_CATEGORIES = {
    'cpu': 'Процессоры',
    'fan': 'Кулеры',
    'motherboard': 'Материнские платы',
    'dram': 'Оперативная память',
    'ssd': 'SSD',
    'hdd': 'Жесткие диски',
    'videocard': 'Видеокарты',
    'powersupply': 'Блоки питания',
    'chassis': 'Корпуса',
    'desktoppc': 'Компьютеры',
    'monoblock': 'Моноблоки',
    'notebook': 'Ноутбуки',
    'display': 'Мониторы',
    'smartwatch': 'Умные часы',
    'ebook': 'Электронные книги',
    'mobile': 'Смартфоны',
    'headphones': 'Наушники',
    'tabletpc': 'Планшеты',
    'keyboards': 'Клавиатуры',
    'mouse': 'Компьютерные мыши',
    'mousepad': 'Коврики для мыши',
    'tv': 'Телевизоры',
    'wallmount': 'Кронштейны',
    'console': 'Игровые приставки',
    'soundbar': 'Саундбары',
    'vacuumcleaner': 'Пылесосы',
    'robotcleaner': 'Роботы-пылесосы',
    'washingmachine': 'Стиральные машины',
    'refrigerator': 'Холодильники',
    'blender': 'Блендеры',
    'iron': 'Утюги',
    'hairdryer': 'Фены',
    'humidifier': 'Увлажнители',
    'aerogrill': 'Аэрогрили',
    'multicooker': 'Мультиварки',
    'heater': 'Обогреватели',
    'voltageregulator': 'Стабилизаторы, сетевые фильтры, удлинители'
}

CATEGORY_TITLE_OVERRIDES = {
    "3d_pen": "3D-ручки",
    "3dprinter": "3D-принтеры",
    "recievers": "AV-ресиверы и усилители",
    "hifisound": "AV-ресиверы и усилители",
    "memcards": "Карты памяти",
    "cardreaders": "Картридеры",
    "usbflash": "USB флеш-накопители",
    "externalhdd": "Внешние накопители",
    "hddbox": "Боксы для накопителей",
    "wrouter": "Wi-Fi роутеры",
    "dslmodem": "DSL-модемы",
    "networkadapter": "Сетевые адаптеры",
    "wirelessadapter": "Беспроводные адаптеры",
    "usbhub": "USB-хабы",
    "ipcamera": "IP-камеры",
    "videoregistrator": "Видеорегистраторы",
    "chargersmobile": "Зарядные устройства",
    "portablecharger": "Внешние аккумуляторы",
    "mouse": "Компьютерные мыши",
    "mousepad": "Коврики для мыши",
    "keyboards": "Клавиатуры",
    "desktoppc": "Компьютеры",
    "monoblock": "Моноблоки",
    "peripheralkits": "Комплекты периферии",
    "office_chair": "Офисные кресла",
    "wallmount": "Кронштейны",
    "notebookcase": "Сумки и чехлы для ноутбуков",
    "webcams": "Веб-камеры",
    "smart_home": "Умный дом",
    "vacuum_acs": "Аксессуары для пылесосов",
    "soundcard": "Звуковые карты",
    "wspeaker": "Портативные колонки",
}

ELECTRONICS_CATEGORY_SLUGS = {
    "antivirus",
    "barcode",
    "battery",
    "cable",
    "cardreaders",
    "carholder",
    "cartridges",
    "chargersmobile",
    "chassis",
    "computer_cleanin",
    "console",
    "cpu",
    "desktoppc",
    "digitalsignage",
    "display",
    "dram",
    "dslmodem",
    "dvr",
    "ebook",
    "externalhdd",
    "fan",
    "gps",
    "hdd",
    "hddbox",
    "headphones",
    "headphones_accs",
    "hifiaudio",
    "hifisound",
    "ipcamera",
    "keyboards",
    "memcards",
    "microphones",
    "mobile",
    "moddingpc",
    "monoblock",
    "motherboard",
    "mouse",
    "mousepad",
    "nas",
    "networkadapter",
    "notebook",
    "notebookcase",
    "optical",
    "peripheralkits",
    "photopaper",
    "portablecharger",
    "powerline",
    "powerstations",
    "powersupply",
    "printers",
    "projectors",
    "recievers",
    "remote",
    "scanner",
    "shredder",
    "smart_home",
    "smartwatch",
    "sound",
    "soundbar",
    "soundcard",
    "ssd",
    "switch",
    "tabletpc",
    "thermal",
    "tv",
    "ups",
    "ups_battery",
    "usbflash",
    "usbhub",
    "videocard",
    "videodoorphone",
    "videoregistrator",
    "wallmount",
    "wantenna",
    "webcams",
    "wirelessadapter",
    "wirelessap",
    "wrouter",
    "wspeaker",
}

COMPUTER_TECH_CATEGORY_SLUGS = {
    "antivirus",
    "cable",
    "cardreaders",
    "cartridges",
    "chassis",
    "computer_cleanin",
    "cpu",
    "desktoppc",
    "digitalsignage",
    "display",
    "dram",
    "dslmodem",
    "externalhdd",
    "fan",
    "hdd",
    "hddbox",
    "headphones",
    "headphones_accs",
    "keyboards",
    "memcards",
    "microphones",
    "moddingpc",
    "monoblock",
    "motherboard",
    "mouse",
    "mousepad",
    "nas",
    "networkadapter",
    "notebook",
    "notebookcase",
    "optical",
    "peripheralkits",
    "photopaper",
    "powerline",
    "powersupply",
    "printers",
    "projectors",
    "scanner",
    "shredder",
    "soundcard",
    "ssd",
    "switch",
    "tabletpc",
    "thermal",
    "ups",
    "ups_battery",
    "usbflash",
    "usbhub",
    "videocard",
    "webcams",
    "wirelessadapter",
    "wirelessap",
    "wrouter",
}

LIGHT_ELECTRONICS_CATEGORY_SLUGS = {
    "barcode",
    "battery",
    "carholder",
    "chargersmobile",
    "console",
    "dvr",
    "ebook",
    "gps",
    "hifiaudio",
    "hifisound",
    "ipcamera",
    "mobile",
    "portablecharger",
    "powerstations",
    "recievers",
    "remote",
    "smart_home",
    "smartwatch",
    "sound",
    "soundbar",
    "tv",
    "videodoorphone",
    "videoregistrator",
    "wallmount",
    "wantenna",
    "wspeaker",
}

DISCOVERED_CATEGORIES_JSON = PARSER_STATE_DIR / "discovered_categories.json"
DISCOVERED_CATEGORIES_MD = PARSER_STATE_DIR / "discovered_categories.md"
VALID_CATEGORIES_JSON = PARSER_STATE_DIR / "valid_categories.json"
VALID_CATEGORIES_MD = PARSER_STATE_DIR / "valid_categories.md"
PROGRESS_FILE = PARSER_STATE_DIR / "onliner_parse_progress.json"
BACKFILL_PROGRESS_FILE = PARSER_STATE_DIR / "onliner_backfill_progress.json"

def slug_to_title(slug):
    slug = str(slug or "").strip().lower()
    if not slug:
        return "Категория"
    if slug in CATEGORY_TITLE_OVERRIDES:
        return CATEGORY_TITLE_OVERRIDES[slug]

    human = slug.replace("_", " ").replace("-", " ").strip()
    human = re.sub(r"\s+", " ", human)
    tokens = []
    for part in human.split(" "):
        if part == "3d":
            tokens.append("3D")
        elif part == "usb":
            tokens.append("USB")
        elif part == "wifi":
            tokens.append("Wi-Fi")
        else:
            tokens.append(part.capitalize())
    return " ".join(tokens)

def _extract_categories_from_node(node, out):
    if isinstance(node, dict):
        slug = node.get("slug") or node.get("key") or node.get("id") or node.get("name")
        title = (
            node.get("title")
            or node.get("full_name")
            or node.get("label")
            or node.get("description")
            or node.get("name")
        )
        if isinstance(slug, str):
            slug = slug.strip().lower()
            if re.fullmatch(r"[a-z0-9_]+", slug):
                out[slug] = str(title).strip() if title else slug_to_title(slug)

        for v in node.values():
            _extract_categories_from_node(v, out)
    elif isinstance(node, list):
        for item in node:
            _extract_categories_from_node(item, out)

def _fetch_json(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OnlinerCatalogParser/1.0)"}
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
    resp.raise_for_status()
    return resp.json()

def discover_all_categories():
    endpoints = [
        "https://catalog.api.onliner.by/search/schemas",
        "https://catalog.api.onliner.by/search/schema",
        "https://catalog.api.onliner.by/schemas",
        "https://catalog.api.onliner.by/schema",
    ]

    discovered = {}
    errors = []

    for url in endpoints:
        try:
            payload = _fetch_json(url)
            _extract_categories_from_node(payload, discovered)
            print(f"✅ Endpoint ok: {url}, найдено slug: {len(discovered)}")
        except Exception as e:
            errors.append(f"{url} -> {e}")
            print(f"⚠️ Endpoint fail: {url} -> {e}")

    if not discovered:
        raise RuntimeError(
            "Не удалось получить категории из API. Ошибки: " + " | ".join(errors[:3])
        )

    for slug, title in BASE_CATEGORIES.items():
        discovered.setdefault(slug, title)

    sorted_items = sorted(discovered.items(), key=lambda x: x[0])
    DISCOVERED_CATEGORIES_JSON.write_text(
        json.dumps(dict(sorted_items), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    md_lines = [
        "# Discovered Onliner Categories",
        "",
        f"Total: {len(sorted_items)}",
        "",
        "| API Key | Title |",
        "|---|---|",
    ]
    for slug, title in sorted_items:
        md_lines.append(f"| `{slug}` | {title} |")
    DISCOVERED_CATEGORIES_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"💾 Сохранено: {DISCOVERED_CATEGORIES_JSON}")
    print(f"💾 Сохранено: {DISCOVERED_CATEGORIES_MD}")
    print(f"📚 Итого категорий: {len(sorted_items)}")

def collect_candidate_categories():
    categories = dict(BASE_CATEGORIES)
    if DISCOVERED_CATEGORIES_JSON.exists():
        try:
            discovered = json.loads(DISCOVERED_CATEGORIES_JSON.read_text(encoding="utf-8"))
            if isinstance(discovered, dict):
                for slug, title in discovered.items():
                    if slug and slug not in categories:
                        categories[str(slug)] = str(title)
        except Exception:
            pass

    script_dir = Path(__file__).resolve().parent
    parent_dir = script_dir.parent
    cache_candidates = set()

    # 1) Прямые пути к ожидаемой папке (с обычным и неразрывным пробелом).
    cache_candidates.add(parent_dir / "Price_List_localHost" / "onliner_id_cache.json")
    cache_candidates.add(parent_dir / "Price_List _localHost" / "onliner_id_cache.json")

    # 2) Шаблон по имени папки.
    for p in parent_dir.glob("Price_List*localHost/onliner_id_cache.json"):
        cache_candidates.add(p)
    for p in parent_dir.glob("Price_List*/onliner_id_cache.json"):
        cache_candidates.add(p)

    # 3) Рекурсивный fallback.
    for p in parent_dir.rglob("onliner_id_cache.json"):
        cache_candidates.add(p)

    cache_candidates = sorted(p for p in cache_candidates if p.exists())

    for cache_path in cache_candidates:
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        for val in raw.values():
            url = str((val or {}).get("url", ""))
            match = re.search(r"https?://catalog\.onliner\.by/([^/]+)/", url)
            if not match:
                continue
            slug = match.group(1).strip()
            if slug and slug not in categories:
                categories[slug] = slug_to_title(slug)

    return categories

def load_categories():
    if VALID_CATEGORIES_JSON.exists():
        try:
            valid = json.loads(VALID_CATEGORIES_JSON.read_text(encoding="utf-8"))
            if isinstance(valid, dict) and valid:
                merged = dict(BASE_CATEGORIES)
                for slug, title in valid.items():
                    if slug not in merged:
                        merged[str(slug)] = str(title)
                return merged
        except Exception:
            pass
    return collect_candidate_categories()

def validate_category_slug(slug):
    url = f'https://catalog.api.onliner.by/search/{slug}?page=1&group=1'
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OnlinerCatalogParser/1.0)"}
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
            if resp.status_code == 404:
                return False, "404"
            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < REQUEST_RETRIES:
                    time.sleep(REQUEST_RETRY_BASE_DELAY * attempt)
                    continue
                return False, f"http_{resp.status_code}"
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and "products" in payload:
                return True, "ok"
            return False, "bad_payload"
        except Exception:
            if attempt < REQUEST_RETRIES:
                time.sleep(REQUEST_RETRY_BASE_DELAY * attempt)
            else:
                return False, "error"
    return False, "error"

def clean_categories():
    candidates = collect_candidate_categories()
    print(f"🧪 Проверяем категории через API: {len(candidates)} шт.")
    valid = {}
    invalid = {}
    for i, (slug, title) in enumerate(candidates.items(), start=1):
        ok, reason = validate_category_slug(slug)
        if ok:
            valid[slug] = title
        else:
            invalid[slug] = reason
        if i % 10 == 0 or i == len(candidates):
            print(f"  {i}/{len(candidates)} | valid={len(valid)} invalid={len(invalid)}")

    valid_sorted = dict(sorted(valid.items(), key=lambda x: x[0]))
    VALID_CATEGORIES_JSON.write_text(
        json.dumps(valid_sorted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_lines = [
        "# Valid Onliner Categories",
        "",
        f"Valid: {len(valid_sorted)} of {len(candidates)}",
        "",
        "| API Key | Title |",
        "|---|---|",
    ]
    for slug, title in valid_sorted.items():
        md_lines.append(f"| `{slug}` | {title} |")
    if invalid:
        md_lines.extend(["", "## Invalid / Skipped", "", "| API Key | Reason |", "|---|---|"])
        for slug, reason in sorted(invalid.items(), key=lambda x: x[0]):
            md_lines.append(f"| `{slug}` | {reason} |")
    VALID_CATEGORIES_MD.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"💾 Сохранено: {VALID_CATEGORIES_JSON}")
    print(f"💾 Сохранено: {VALID_CATEGORIES_MD}")
    print(f"✅ Валидных категорий: {len(valid_sorted)}")
    print(f"⛔ Невалидных/пропущенных: {len(invalid)}")

CATEGORIES = load_categories()

EXCLUDE_BRANDS = [
    "ASUS", "Dendy", "Dinotronix", "Emote", "Lenovo", "Logitech", "Magistr",
    "Microsoft", "MSI", "Nintendo", "Nintendo Switch", "Nintendo Switch 2",
    "PGP AIO", "PlayStation 3", "Razer", "Retro Genesis", "Valve"
]

REQUEST_TIMEOUT = 20
REQUEST_RETRIES = 6
REQUEST_RETRY_BASE_DELAY = 2
MAX_WORKERS = 1
MAX_PRODUCTS_PER_CATEGORY = 20000
WRITE_REQUEST_RETRIES = 10
WRITE_RETRY_BASE_DELAY = 5
WRITE_MIN_INTERVAL_SECONDS = 1.5
LAST_WRITE_TS = 0.0
ROW_GROWTH_CHUNK = 2000
TARGET_COLUMNS = 8
ZERO_WRITE_PAGES_LIMIT = 12
CATEGORY_GROUP_MODE = 0
APPLY_STRICT_FILTERS = False
IDENTITY_READ_CHUNK_ROWS = 25000

STRICT_FILTER_CATEGORIES = {
    "cpu",
    "motherboard",
    "dram",
    "ssd",
    "hdd",
    "videocard",
    "powersupply",
    "chassis",
    "fan",
}


class WorkbookCellLimitError(Exception):
    pass

def is_retryable_sheet_api_error(exc):
    err = str(exc)
    if "10000000 cells" in err:
        return False
    retry_markers = [
        "429",
        "Quota exceeded",
        "[500]",
        "Internal error encountered",
        "[502]",
        "[503]",
        "[504]",
    ]
    return any(marker in err for marker in retry_markers)

def is_transient_sheet_error(exc):
    if isinstance(exc, (RemoteDisconnected, ConnectionError, TimeoutError)):
        return True
    msg = str(exc).lower()
    transient_markers = [
        "remote end closed connection",
        "connection aborted",
        "protocolerror",
        "temporarily unavailable",
        "connection reset",
        "read timed out",
        "timed out",
    ]
    return any(marker in msg for marker in transient_markers)

def extract_model(full_name):
    patterns = [
        r'\b(i[3579]-\d{4,5}[A-Z]{0,2})\b',
        r'\b(Ryzen\s+\d+\s+\d{4,5}[A-Z]{0,2})\b'
    ]
    for pattern in patterns:
        match = re.search(pattern, full_name, re.IGNORECASE)
        if match:
            return match.group(1)
    return full_name

def safe_get_price(item):
    try:
        prices = item.get("prices", {})
        price_min = prices.get("price_min", {})
        return price_min.get("amount", "N/A")
    except:
        return "N/A"

def safe_get_catalog_id(item):
    catalog_id = item.get("id")
    if catalog_id not in (None, ""):
        return str(catalog_id)
    return "N/A"

def safe_get_image_url(item):
    images = item.get("images") or {}
    if isinstance(images, dict):
        for key in ("header", "icon", "small", "original"):
            url = images.get(key)
            if url:
                return str(url)
    return ""

def safe_get_specs(item):
    return str(item.get("extended_name") or item.get("description") or "")

def parse_category_list(raw_value):
    if not raw_value:
        return []
    parts = re.split(r"[,\s]+", str(raw_value).strip())
    return [part.strip() for part in parts if part.strip()]

def normalize_match_text(raw_value):
    return str(raw_value or "").strip().lower()

def parse_match_tokens(raw_value):
    raw = normalize_match_text(raw_value)
    if not raw:
        return []
    return [token.strip() for token in re.split(r"[,\n;]+", raw) if token.strip()]

def item_matches_text_filter(item, match_text=""):
    needles = parse_match_tokens(match_text)
    if not needles:
        return True

    haystacks = [
        item.get("full_name", ""),
        item.get("extended_name", ""),
        item.get("description", ""),
        item.get("html_url", ""),
        item.get("manufacturer", {}).get("name", ""),
        item.get("micro_description", ""),
    ]
    for value in haystacks:
        value_lower = str(value or "").lower()
        for needle in needles:
            if needle in value_lower:
                return True
    return False

def resolve_categories_for_run(all_categories, include_raw=None, exclude_raw=None):
    include_list = parse_category_list(include_raw)
    exclude_set = set(parse_category_list(exclude_raw))

    if include_list:
        unknown = [c for c in include_list if c not in all_categories]
        if unknown:
            raise ValueError(f"Неизвестные категории: {', '.join(unknown)}")
        result = [c for c in include_list if c not in exclude_set]
    else:
        result = [c for c in all_categories if c not in exclude_set]

    if not result:
        raise ValueError("После фильтрации не осталось категорий для парсинга.")
    return result

def filter_electronics_categories(categories_order):
    result = [slug for slug in categories_order if slug in ELECTRONICS_CATEGORY_SLUGS]
    if not result:
        raise ValueError("После фильтра electronics-only не осталось категорий для парсинга.")
    return result

def apply_profile_filter(categories_order, profile):
    if not profile:
        return categories_order

    profile = str(profile).strip().lower()
    if profile == "computer_tech":
        allowed = COMPUTER_TECH_CATEGORY_SLUGS
    elif profile == "light_electronics":
        allowed = LIGHT_ELECTRONICS_CATEGORY_SLUGS
    elif profile == "all_other":
        used = COMPUTER_TECH_CATEGORY_SLUGS | LIGHT_ELECTRONICS_CATEGORY_SLUGS
        allowed = set(categories_order) - used
    else:
        raise ValueError(
            "Неизвестный профиль. Доступно: computer_tech, light_electronics, all_other"
        )

    result = [slug for slug in categories_order if slug in allowed]
    if not result:
        raise ValueError(f"После применения профиля {profile} не осталось категорий для парсинга.")
    return result

def extract_slug_from_catalog_url(url):
    raw = str(url or "").strip()
    if not raw:
        return ""
    match = re.search(r"https?://catalog\.onliner\.by/([^/?#]+)/", raw)
    if not match:
        return ""
    return match.group(1).strip().lower()

def fetch_products_page(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OnlinerCatalogParser/1.0)"}
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
            resp.raise_for_status()
            return resp.json().get("products", [])
        except RequestException as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code == 404:
                print(f'⚠️ Категория не поддерживается API (404): {url}')
                return []
            if attempt == REQUEST_RETRIES:
                print(f'❌ Ошибка запроса после {REQUEST_RETRIES} попыток: {e}')
                return None
            wait_seconds = REQUEST_RETRY_BASE_DELAY * attempt
            print(f'⚠️ Сбой сети (попытка {attempt}/{REQUEST_RETRIES}), повтор через {wait_seconds} сек...')
            time.sleep(wait_seconds)

def fetch_products(category):
    print(f'📦 Парсим категорию: {category}')
    all_results = []
    page = 1

    while len(all_results) < MAX_PRODUCTS_PER_CATEGORY:
        url = f'https://catalog.api.onliner.by/search/{category}?page={page}&group=1'
        try:
            products = fetch_products_page(url)
            if products is None:
                break
            if not products:
                break

            for item in products:
                full_name = item.get("full_name", "")
                brand = item.get("manufacturer", {}).get("name", "").strip()

                if any(b.lower() == brand.lower() for b in EXCLUDE_BRANDS):
                    continue
                if any(term in full_name.lower() for term in ['xeon', 'epyc', 'threadripper', 'amd fx']):
                    continue

                model = extract_model(full_name)
                price = safe_get_price(item)
                if price == "N/A":
                    continue

                catalog_id = safe_get_catalog_id(item)
                link = item.get("html_url", "")
                category_name = CATEGORIES.get(category, category)

                all_results.append([
                    category_name, brand, model, price, catalog_id, '', link
                ])

            page += 1
            time.sleep(1)
        except Exception as e:
            print(f'❌ Ошибка при парсинге: {e}')
            break

    print(f'✅ Найдено {len(all_results)} товаров в {category}')
    return all_results

def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def load_progress(progress_file=PROGRESS_FILE):
    if not progress_file.exists():
        return None
    try:
        return json.loads(progress_file.read_text(encoding="utf-8"))
    except Exception:
        return None

def save_progress(state, progress_file=PROGRESS_FILE):
    state["updated_at"] = utc_now_iso()
    progress_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def init_progress(categories_order, sheet_tab=SHEET_TAB, completed_categories=None, next_row=2, progress_file=PROGRESS_FILE):
    state = {
        "started_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "spreadsheet_id": SPREADSHEET_ID,
        "sheet_tab": sheet_tab,
        "categories_order": categories_order,
        "completed_categories": sorted(set(completed_categories or [])),
        "current": None,
        "rows_written": 0,
        "next_row": int(next_row),
    }
    save_progress(state, progress_file=progress_file)
    return state

def append_rows_strict(sheet, start_row, rows):
    global LAST_WRITE_TS
    if not rows:
        return start_row
    end_row = start_row + len(rows) - 1
    if end_row > sheet.row_count:
        rows_to_add = max(end_row - sheet.row_count, ROW_GROWTH_CHUNK)
        for attempt in range(1, WRITE_REQUEST_RETRIES + 1):
            wait_left = WRITE_MIN_INTERVAL_SECONDS - (time.time() - LAST_WRITE_TS)
            if wait_left > 0:
                time.sleep(wait_left)
            try:
                sheet.add_rows(rows_to_add)
                LAST_WRITE_TS = time.time()
                break
            except APIError as e:
                err = str(e)
                if "10000000 cells" in err:
                    raise WorkbookCellLimitError(
                        "Достигнут лимит Google Sheets: 10,000,000 ячеек в книге."
                    )
                if (not is_retryable_sheet_api_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                    raise
                sleep_seconds = WRITE_RETRY_BASE_DELAY * attempt
                print(
                    f"⚠️ Временная ошибка изменения листа Google Sheets. "
                    f"Повтор {attempt}/{WRITE_REQUEST_RETRIES} через {sleep_seconds} сек..."
                )
                time.sleep(sleep_seconds)
            except Exception as e:
                if (not is_transient_sheet_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                    raise
                sleep_seconds = WRITE_RETRY_BASE_DELAY * attempt
                print(
                    f"⚠️ Временный сетевой сбой при add_rows. "
                    f"Повтор {attempt}/{WRITE_REQUEST_RETRIES} через {sleep_seconds} сек..."
                )
                time.sleep(sleep_seconds)
    target_range = f"A{start_row}:H{end_row}"
    for attempt in range(1, WRITE_REQUEST_RETRIES + 1):
        # Throttle writes to avoid hitting per-minute write quota.
        wait_left = WRITE_MIN_INTERVAL_SECONDS - (time.time() - LAST_WRITE_TS)
        if wait_left > 0:
            time.sleep(wait_left)
        try:
            sheet.update(range_name=target_range, values=rows, value_input_option="RAW")
            LAST_WRITE_TS = time.time()
            break
        except APIError as e:
            err = str(e)
            if "10000000 cells" in err:
                raise WorkbookCellLimitError(
                    "Достигнут лимит Google Sheets: 10,000,000 ячеек в книге."
                )
            if (not is_retryable_sheet_api_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                raise
            sleep_seconds = WRITE_RETRY_BASE_DELAY * attempt
            print(
                f"⚠️ Временная ошибка записи в Google Sheets. "
                f"Повтор {attempt}/{WRITE_REQUEST_RETRIES} через {sleep_seconds} сек..."
            )
            time.sleep(sleep_seconds)
        except Exception as e:
            if (not is_transient_sheet_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                raise
            sleep_seconds = WRITE_RETRY_BASE_DELAY * attempt
            print(
                f"⚠️ Временный сетевой сбой при записи в лист. "
                f"Повтор {attempt}/{WRITE_REQUEST_RETRIES} через {sleep_seconds} сек..."
            )
            time.sleep(sleep_seconds)
    return end_row + 1

def clear_sheet_data_keep_header(sheet):
    if sheet.row_count <= 1:
        sheet.add_rows(1000)
    sheet.batch_clear([f"A2:H{sheet.row_count}"])

def ensure_header(sheet):
    header = ["Category", "Brand", "Model", "Price", "onliner_id", "URL", "image_url", "Specs"]
    for attempt in range(1, WRITE_REQUEST_RETRIES + 1):
        try:
            sheet.update(range_name="A1:H1", values=[header], value_input_option="RAW")
            return
        except APIError as e:
            if (not is_retryable_sheet_api_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                raise
            time.sleep(WRITE_RETRY_BASE_DELAY * attempt)
        except Exception as e:
            if (not is_transient_sheet_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                raise
            time.sleep(WRITE_RETRY_BASE_DELAY * attempt)

def ensure_sheet_columns(sheet):
    global LAST_WRITE_TS
    if sheet.col_count <= TARGET_COLUMNS:
        return
    for attempt in range(1, WRITE_REQUEST_RETRIES + 1):
        wait_left = WRITE_MIN_INTERVAL_SECONDS - (time.time() - LAST_WRITE_TS)
        if wait_left > 0:
            time.sleep(wait_left)
        try:
            sheet.resize(rows=sheet.row_count, cols=TARGET_COLUMNS)
            LAST_WRITE_TS = time.time()
            print(f"🧱 Сжали лист до {TARGET_COLUMNS} колонок (A:H) для экономии лимита ячеек.")
            return
        except APIError as e:
            err = str(e)
            if "10000000 cells" in err:
                raise WorkbookCellLimitError(
                    "Невозможно изменить размер листа: книга уже у лимита 10,000,000 ячеек."
                )
            if (not is_retryable_sheet_api_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                raise
            sleep_seconds = WRITE_RETRY_BASE_DELAY * attempt
            print(
                f"⚠️ Временная ошибка изменения колонок Google Sheets. "
                f"Повтор {attempt}/{WRITE_REQUEST_RETRIES} через {sleep_seconds} сек..."
            )
            time.sleep(sleep_seconds)
        except Exception as e:
            if (not is_transient_sheet_error(e)) or attempt == WRITE_REQUEST_RETRIES:
                raise
            sleep_seconds = WRITE_RETRY_BASE_DELAY * attempt
            print(
                f"⚠️ Временный сетевой сбой при resize листа. "
                f"Повтор {attempt}/{WRITE_REQUEST_RETRIES} через {sleep_seconds} сек..."
            )
            time.sleep(sleep_seconds)

def cleanup_sheet_keep_categories(sheet, allowed_slugs):
    allowed_slugs = set(allowed_slugs)
    allowed_titles = {
        str(CATEGORIES.get(slug, "")).strip().lower()
        for slug in allowed_slugs
        if str(CATEGORIES.get(slug, "")).strip()
    }
    rows = sheet.get_all_values()
    data_rows = rows[1:] if rows else []
    kept = []
    removed = 0

    for row in data_rows:
        padded = (row + [""] * TARGET_COLUMNS)[:TARGET_COLUMNS]
        category_title = str(padded[0]).strip().lower()
        item_url = str(padded[5]).strip()
        slug = extract_slug_from_catalog_url(item_url)
        keep = False

        if slug:
            keep = slug in allowed_slugs
        elif category_title:
            keep = category_title in allowed_titles

        if keep:
            kept.append(padded)
        else:
            removed += 1

    print(f"🧹 Очистка листа: строк всего={len(data_rows)}, оставляем={len(kept)}, удаляем={removed}")
    clear_sheet_data_keep_header(sheet)
    if kept:
        next_row = 2
        chunk_size = 300
        for i in range(0, len(kept), chunk_size):
            next_row = append_rows_strict(sheet, next_row, kept[i:i + chunk_size])
    print("✅ Очистка листа завершена.")

def process_category_with_resume(sheet, category, state, progress_file=PROGRESS_FILE, match_text=""):
    completed = set(state.get("completed_categories", []))
    if category in completed:
        print(f'⏭️ Пропускаем (уже готово): {category}')
        return True, 0

    current = state.get("current") or {}
    if current.get("category") == category:
        page = int(current.get("next_page", 1))
    else:
        page = 1
        state["current"] = {"category": category, "next_page": 1}
        save_progress(state, progress_file=progress_file)

    print(f'📦 Парсим категорию: {category} (старт со стр. {page})')
    total_in_category = 0

    while total_in_category < MAX_PRODUCTS_PER_CATEGORY:
        url = f'https://catalog.api.onliner.by/search/{category}?page={page}&group={CATEGORY_GROUP_MODE}'
        print(f"  ↳ {category}: страница {page}...")
        products = fetch_products_page(url)
        if products is None:
            print(f'⏸️ Остановка на {category}, стр. {page} (сеть/API). Продолжишь через --resume')
            state["current"] = {"category": category, "next_page": page}
            save_progress(state, progress_file=progress_file)
            return False, total_in_category
        if not products:
            break

        page_rows = []
        for item in products:
            if not item_matches_text_filter(item, match_text=match_text):
                continue

            full_name = item.get("full_name", "")
            brand = item.get("manufacturer", {}).get("name", "").strip()

            if APPLY_STRICT_FILTERS and category in STRICT_FILTER_CATEGORIES:
                if any(b.lower() == brand.lower() for b in EXCLUDE_BRANDS):
                    continue
            if APPLY_STRICT_FILTERS and any(term in full_name.lower() for term in ['xeon', 'epyc', 'threadripper', 'amd fx']):
                continue

            model = extract_model(full_name)
            price = safe_get_price(item)

            catalog_id = safe_get_catalog_id(item)
            link = item.get("html_url", "")
            image_url = safe_get_image_url(item)
            specs = safe_get_specs(item)
            category_name = CATEGORIES.get(category, category)

            page_rows.append([category_name, brand, model, price, catalog_id, link, image_url, specs])

        if page_rows:
            page_rows.sort(key=lambda x: x[1].lower())
            next_row = int(state.get("next_row", 2))
            next_row = append_rows_strict(sheet, next_row, page_rows)
            state["next_row"] = next_row
            written = len(page_rows)
            total_in_category += written
            state["rows_written"] = int(state.get("rows_written", 0)) + written
            print(f"    + записано: {written}, всего в категории: {total_in_category}")
        else:
            print("    + записано: 0")

        page += 1
        state["current"] = {"category": category, "next_page": page}
        save_progress(state, progress_file=progress_file)
        time.sleep(1)

    state["completed_categories"] = sorted(set(state.get("completed_categories", [])) | {category})
    state["current"] = None
    save_progress(state, progress_file=progress_file)
    print(f'✅ Найдено {total_in_category} товаров в {category}')
    return True, total_in_category

def build_row_from_item(category, item, match_text=""):
    if not item_matches_text_filter(item, match_text=match_text):
        return None

    full_name = item.get("full_name", "")
    brand = item.get("manufacturer", {}).get("name", "").strip()

    if APPLY_STRICT_FILTERS and category in STRICT_FILTER_CATEGORIES:
        if any(b.lower() == brand.lower() for b in EXCLUDE_BRANDS):
            return None
    if APPLY_STRICT_FILTERS and any(term in full_name.lower() for term in ['xeon', 'epyc', 'threadripper', 'amd fx']):
        return None

    model = extract_model(full_name)
    price = safe_get_price(item)
    catalog_id = safe_get_catalog_id(item)
    link = item.get("html_url", "")
    image_url = safe_get_image_url(item)
    specs = safe_get_specs(item)
    category_name = CATEGORIES.get(category, category)
    return [category_name, brand, model, price, catalog_id, link, image_url, specs]

def get_existing_identity_sets(sheet, chunk_rows=IDENTITY_READ_CHUNK_ROWS):
    existing_ids = set()
    existing_urls = set()
    last_data_row = 1
    total_rows = max(int(sheet.row_count or 1), 1)

    print(f'📥 Читаем существующие ID и URL порциями по {chunk_rows} строк...')
    for start_row in range(2, total_rows + 1, chunk_rows):
        end_row = min(start_row + chunk_rows - 1, total_rows)
        first_col, identity_cols = sheet.batch_get([
            f"A{start_row}:A{end_row}",
            f"E{start_row}:F{end_row}",
        ])

        for offset, row in enumerate(first_col):
            if any(str(value or "").strip() for value in row):
                last_data_row = max(last_data_row, start_row + offset)

        for offset, row in enumerate(identity_cols):
            oid = str(row[0]).strip() if row else ""
            url = str(row[1]).strip() if len(row) > 1 else ""
            if oid and oid != "N/A":
                existing_ids.add(oid)
            if url:
                existing_urls.add(url)
            if oid or url:
                last_data_row = max(last_data_row, start_row + offset)

        print(
            f'  ↳ прочитано до строки {end_row}/{total_rows}; '
            f'id={len(existing_ids)}, url={len(existing_urls)}'
        )

    return existing_ids, existing_urls, max(last_data_row + 1, 2)

def process_category_backfill(
    sheet,
    category,
    state,
    existing_ids,
    existing_urls,
    progress_file=BACKFILL_PROGRESS_FILE,
    match_text="",
):
    completed = set(state.get("completed_categories", []))
    if category in completed:
        print(f'⏭️ Пропускаем (уже проверено): {category}')
        return True, 0

    current = state.get("current") or {}
    if current.get("category") == category:
        page = int(current.get("next_page", 1))
    else:
        page = 1
        state["current"] = {"category": category, "next_page": 1}
        save_progress(state, progress_file=progress_file)

    print(f'🔁 Backfill категории: {category} (старт со стр. {page})')
    added_in_category = 0

    while True:
        url = f'https://catalog.api.onliner.by/search/{category}?page={page}&group={CATEGORY_GROUP_MODE}'
        print(f"  ↳ {category}: страница {page}...")
        products = fetch_products_page(url)
        if products is None:
            print(f'⏸️ Остановка backfill на {category}, стр. {page}. Продолжишь через --backfill-missing --resume')
            state["current"] = {"category": category, "next_page": page}
            save_progress(state, progress_file=progress_file)
            return False, added_in_category
        if not products:
            break

        page_rows = []
        page_total_products = len(products)
        page_matched_filter = 0
        page_already_exists = 0
        for item in products:
            row_data = build_row_from_item(category, item, match_text=match_text)
            if not row_data:
                continue
            page_matched_filter += 1
            oid = str(row_data[4]).strip()
            item_url = str(row_data[5]).strip()
            has_oid = oid and oid != "N/A"
            if has_oid and oid in existing_ids:
                page_already_exists += 1
                continue
            if item_url and item_url in existing_urls:
                page_already_exists += 1
                continue

            page_rows.append(row_data)
            if has_oid:
                existing_ids.add(oid)
            if item_url:
                existing_urls.add(item_url)

        if page_rows:
            page_rows.sort(key=lambda x: x[1].lower())
            next_row = int(state.get("next_row", 2))
            next_row = append_rows_strict(sheet, next_row, page_rows)
            state["next_row"] = next_row
            added_in_category += len(page_rows)
            state["rows_written"] = int(state.get("rows_written", 0)) + len(page_rows)
            print(
                f"    + backfill добавлено: {len(page_rows)}, "
                f"уже в таблице: {page_already_exists}, "
                f"совпало по фильтру: {page_matched_filter}, "
                f"всего в категории: {added_in_category}"
            )
        else:
            if match_text:
                page_filtered_out = max(page_total_products - page_matched_filter, 0)
                print(
                    f"    + backfill добавлено: 0, "
                    f"уже в таблице: {page_already_exists}, "
                    f"совпало по фильтру: {page_matched_filter}, "
                    f"не подошло по фильтру: {page_filtered_out}"
                )
            else:
                print(
                    f"    + backfill добавлено: 0, "
                    f"уже в таблице: {page_already_exists}, "
                    f"совпало по фильтру: {page_matched_filter}"
                )

        page += 1
        state["current"] = {"category": category, "next_page": page}
        save_progress(state, progress_file=progress_file)
        time.sleep(1)

    state["completed_categories"] = sorted(set(state.get("completed_categories", [])) | {category})
    state["current"] = None
    save_progress(state, progress_file=progress_file)
    print(f'✅ Backfill {category}: добавлено {added_in_category}')
    return True, added_in_category

def backfill_missing(
    resume=False,
    include_categories=None,
    exclude_categories=None,
    sheet_tab=SHEET_TAB,
    electronics_only=False,
    profile="",
    match_text="",
):
    print('🚀 Запуск режима backfill (только отсутствующие товары)...')
    print(f'📚 Категорий в проверке: {len(CATEGORIES)}')
    print(f'🔎 Режим полноты: group={CATEGORY_GROUP_MODE}, строгие фильтры={APPLY_STRICT_FILTERS}')
    print(f'📄 Лист: {sheet_tab}')
    sheet = authorize_google_sheets(sheet_tab=sheet_tab)
    ensure_sheet_columns(sheet)
    ensure_header(sheet)
    categories_order = resolve_categories_for_run(
        list(CATEGORIES.keys()),
        include_raw=include_categories,
        exclude_raw=exclude_categories,
    )
    if profile:
        before = len(categories_order)
        categories_order = apply_profile_filter(categories_order, profile)
        print(f"🧩 Профиль {profile}: {len(categories_order)}/{before} категорий.")
    if electronics_only:
        before = len(categories_order)
        categories_order = filter_electronics_categories(categories_order)
        print(f"🔌 Фильтр electronics-only: {len(categories_order)}/{before} категорий.")
    total_categories = len(categories_order)

    existing_ids, existing_urls, next_row = get_existing_identity_sets(sheet)
    print(f'📌 Уже в таблице: id={len(existing_ids)}, url={len(existing_urls)}')

    if resume:
        state = load_progress(progress_file=BACKFILL_PROGRESS_FILE)
        if state is None:
            print('ℹ️ Backfill прогресс не найден, запускаем новый backfill.')
            state = init_progress(categories_order, sheet_tab=sheet_tab, next_row=next_row, progress_file=BACKFILL_PROGRESS_FILE)
        elif "next_row" not in state:
            state["next_row"] = next_row
            save_progress(state, progress_file=BACKFILL_PROGRESS_FILE)
        if state.get("sheet_tab") and state["sheet_tab"] != sheet_tab:
            print(f"⚠️ Backfill progress был для листа {state['sheet_tab']}, переключаю на {sheet_tab}.")
            state["sheet_tab"] = sheet_tab
            save_progress(state, progress_file=BACKFILL_PROGRESS_FILE)
    else:
        state = init_progress(categories_order, sheet_tab=sheet_tab, next_row=next_row, progress_file=BACKFILL_PROGRESS_FILE)

    total_added = 0
    try:
        print_category_progress(state, total_categories)
        for category in categories_order:
            ok, added = process_category_backfill(
                sheet,
                category,
                state,
                existing_ids,
                existing_urls,
                progress_file=BACKFILL_PROGRESS_FILE,
                match_text=match_text,
            )
            total_added += added
            print_category_progress(state, total_categories)
            if not ok:
                print(f'💾 Backfill прогресс сохранён: {BACKFILL_PROGRESS_FILE}')
                return
    except KeyboardInterrupt:
        print('\n⏹️ Backfill остановлен пользователем. Прогресс сохранён.')
        print(f'💾 Файл прогресса: {BACKFILL_PROGRESS_FILE}')
        return

    print(f'📊 Backfill завершён. Добавлено новых товаров: {total_added}')
    if BACKFILL_PROGRESS_FILE.exists():
        BACKFILL_PROGRESS_FILE.unlink()
        print('🧹 Backfill прогресс удалён (проверка завершена полностью).')

def print_category_progress(state, total_categories):
    completed_count = len(state.get("completed_categories", []))
    remaining = max(total_categories - completed_count, 0)
    print(f"📊 Категорий: {completed_count}/{total_categories} спарсено, осталось: {remaining}")

def authorize_google_sheets(sheet_tab=SHEET_TAB):
    if not JSON_KEY_FILE.exists():
        raise FileNotFoundError(
            f"Файл ключа Google не найден: {JSON_KEY_FILE}. "
            "Положи JSON в папку скрипта или задай ONLINER_SHEETS_KEY_FILE."
        )
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(JSON_KEY_FILE), scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(sheet_tab)

def main(
    resume=False,
    append_remaining=False,
    include_categories=None,
    exclude_categories=None,
    sheet_tab=SHEET_TAB,
    electronics_only=False,
    cleanup_sheet=False,
    profile="",
    match_text="",
):
    print('🚀 Начинаем выгрузку...')
    print(f'📚 Категорий в парсинге: {len(CATEGORIES)}')
    print(f'🔎 Режим полноты: group={CATEGORY_GROUP_MODE}, строгие фильтры={APPLY_STRICT_FILTERS}')
    if len(CATEGORIES) <= len(BASE_CATEGORIES):
        print('⚠️ Загружены только базовые категории. Доп. кэши/файлы категорий не найдены.')
    print(f'📄 Лист: {sheet_tab}')
    sheet = authorize_google_sheets(sheet_tab=sheet_tab)
    ensure_sheet_columns(sheet)
    ensure_header(sheet)
    categories_order = resolve_categories_for_run(
        list(CATEGORIES.keys()),
        include_raw=include_categories,
        exclude_raw=exclude_categories,
    )
    if profile:
        before = len(categories_order)
        categories_order = apply_profile_filter(categories_order, profile)
        print(f"🧩 Профиль {profile}: {len(categories_order)}/{before} категорий.")
    if electronics_only:
        before = len(categories_order)
        categories_order = filter_electronics_categories(categories_order)
        print(f"🔌 Фильтр electronics-only: {len(categories_order)}/{before} категорий.")
    total_categories = len(categories_order)

    if cleanup_sheet:
        cleanup_sheet_keep_categories(sheet, categories_order)
        print("ℹ️ Режим cleanup-sheet: парсинг не запускался.")
        return

    if resume:
        state = load_progress(progress_file=PROGRESS_FILE)
        if state is None:
            print('ℹ️ Файл прогресса не найден, запускаем с начала.')
            clear_sheet_data_keep_header(sheet)
            state = init_progress(categories_order, sheet_tab=sheet_tab, progress_file=PROGRESS_FILE)
        else:
            if "next_row" not in state:
                state["next_row"] = max(len(sheet.get_all_values()) + 1, 2)
                save_progress(state, progress_file=PROGRESS_FILE)
            if state.get("sheet_tab") and state["sheet_tab"] != sheet_tab:
                print(f"⚠️ Прогресс был для листа {state['sheet_tab']}, переключаю на {sheet_tab}.")
                state["sheet_tab"] = sheet_tab
                save_progress(state, progress_file=PROGRESS_FILE)
    elif append_remaining:
        existing_rows = len(sheet.get_all_values())
        completed = set(BASE_CATEGORIES.keys()) if not include_categories else set()
        next_row = max(existing_rows + 1, 2)
        print(
            f"➕ Режим допарсинга: пропускаем базовые {len(completed)} категорий, "
            f"начинаем запись с строки {next_row}."
        )
        state = init_progress(categories_order, sheet_tab=sheet_tab, completed_categories=completed, next_row=next_row, progress_file=PROGRESS_FILE)
    else:
        clear_sheet_data_keep_header(sheet)
        state = init_progress(categories_order, sheet_tab=sheet_tab, progress_file=PROGRESS_FILE)

    try:
        print_category_progress(state, total_categories)
        for category in categories_order:
            ok, _ = process_category_with_resume(
                sheet,
                category,
                state,
                progress_file=PROGRESS_FILE,
                match_text=match_text,
            )
            print_category_progress(state, total_categories)
            if not ok:
                print(f'💾 Прогресс сохранён: {PROGRESS_FILE}')
                return
    except WorkbookCellLimitError as e:
        print(f"\n⛔ {e}")
        print("💾 Прогресс сохранён. Освободи место в книге (или используй новую таблицу) и продолжи через --resume.")
        print(f'💾 Файл прогресса: {PROGRESS_FILE}')
        return
    except KeyboardInterrupt:
        print('\n⏹️ Остановлено пользователем. Прогресс сохранён.')
        print(f'💾 Файл прогресса: {PROGRESS_FILE}')
        return

    print('📊 Завершено: данные обновлены в таблице.')
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        print('🧹 Файл прогресса удалён (парсинг завершён полностью).')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--discover-categories",
        action="store_true",
        help="Собрать полный список категорий из API и сохранить в файл",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Продолжить выгрузку с сохранённого места (по файлу прогресса)",
    )
    parser.add_argument(
        "--append-remaining",
        action="store_true",
        help="Не чистить лист и допарсить только небазовые категории поверх текущих данных",
    )
    parser.add_argument(
        "--clean-categories",
        action="store_true",
        help="Проверить все кандидатные категории и сохранить только валидные для API",
    )
    parser.add_argument(
        "--backfill-missing",
        action="store_true",
        help="Проверить категории и дозаписать только отсутствующие товары (без полной перепарсинга)",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default="",
        help="Список категорий для запуска: slug1,slug2,slug3",
    )
    parser.add_argument(
        "--exclude-categories",
        type=str,
        default="",
        help="Список категорий для исключения: slug1,slug2",
    )
    parser.add_argument(
        "--sheet-tab",
        type=str,
        default=SHEET_TAB,
        help="Имя вкладки Google Sheets для записи (например: All_Catalog, Mobile_Only)",
    )
    parser.add_argument(
        "--electronics-only",
        action="store_true",
        help="Оставить/парсить только категории электроники",
    )
    parser.add_argument(
        "--cleanup-sheet",
        action="store_true",
        help="Очистить лист: оставить только выбранные категории (без запуска парсинга)",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="",
        choices=["computer_tech", "light_electronics", "all_other"],
        help="Профиль категорий: computer_tech | light_electronics | all_other",
    )
    parser.add_argument(
        "--match-text",
        type=str,
        default="",
        help="Фильтр по тексту товара: ищет совпадение в названии, бренде, описании и URL",
    )
    args = parser.parse_args()

    try:
        if args.backfill_missing:
            backfill_missing(
                resume=args.resume,
                include_categories=args.categories,
                exclude_categories=args.exclude_categories,
                sheet_tab=args.sheet_tab,
                electronics_only=args.electronics_only,
                profile=args.profile,
                match_text=args.match_text,
            )
        elif args.clean_categories:
            clean_categories()
        elif args.discover_categories:
            discover_all_categories()
        else:
            main(
                resume=args.resume,
                append_remaining=args.append_remaining,
                include_categories=args.categories,
                exclude_categories=args.exclude_categories,
                sheet_tab=args.sheet_tab,
                electronics_only=args.electronics_only,
                cleanup_sheet=args.cleanup_sheet,
                profile=args.profile,
                match_text=args.match_text,
            )
    except ValueError as e:
        print(f"❌ Ошибка параметров: {e}")
