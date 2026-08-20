import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote_plus

import requests
from flask import Flask, jsonify, render_template, request

import onliner_to_sheets as parser


APP_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = APP_DIR / "onliner_to_sheets.py"
HOST = os.getenv("ONLINER_UI_HOST", "127.0.0.1")
PORT = int(os.getenv("ONLINER_UI_PORT", "5055"))
MAX_LOG_LINES = 2500
SHEET_COUNT_CACHE_TTL = 20
TARGET_LOOKUP_TIMEOUT = (3, 8)
TARGET_LOOKUP_WORKERS = 4
TARGET_LOOKUP_SETTINGS_PATH = Path(
    os.getenv("PRICE_MIXER_ONLINER_API_SETTINGS", "/opt/price-mixer/onliner_api_settings.json")
)
TARGET_LOOKUP_URLS = (
    "https://catalog.onliner.by/sdapi/catalog.api/search/products?query={query}",
    "https://catalog.api.onliner.by/search/products?query={query}",
)
TARGET_PARENT_CATEGORY_HINTS = {
    "ssd": "SSD",
    "блок питания": "Блоки питания",
    "видеокарта": "Видеокарты",
    "ибп": "Источники бесперебойного питания",
    "ip-камера": "IP-камеры",
    "кабели и переходники": "Кабели, адаптеры, разветвители",
    "корпус": "Корпуса",
    "кулеры": "Кулеры",
    "материнская плата": "Материнские платы",
    "микрофон": "Микрофоны",
    "монитор": "Мониторы",
    "мышь": "Мыши",
    "наушники": "Наушники и гарнитуры",
    "ноутбук": "Ноутбуки",
    "оперативная память": "Оперативная память",
    "фотобумага": "Бумага и материалы для печати",
}
TARGET_MATCH_STOP_TOKENS = {
    "для",
    "черный",
    "черная",
    "черное",
    "белый",
    "белая",
    "белое",
    "серый",
    "серая",
    "серебристый",
    "блок",
    "питания",
    "видеокарта",
    "гарнитура",
    "кабель",
    "комплект",
    "корпус",
    "кулер",
    "монитор",
    "мышь",
    "наушники",
}

DEFAULT_CATEGORY_PRESET = [
    "cpu",
    "fan",
    "ssd",
    "externalhdd",
    "hdd",
    "display",
    "videocard",
    "powersupply",
    "chassis",
    "keyboards",
    "mouse",
    "peripheralkits",
    "sound",
    "soundbar",
    "soundcard",
    "wspeaker",
]

HOME_APPLIANCE_CATEGORY_SLUGS = {
    "aerogrill",
    "blender",
    "body_care",
    "dispenser",
    "disposer",
    "hairclipper",
    "hairdryer",
    "heater",
    "hoods",
    "humidifier",
    "iron",
    "multicooker",
    "oven_cooker",
    "refrigerator",
    "robotcleaner",
    "vacuum_acs",
    "vacuumcleaner",
    "washingmachine",
}

PRESETS = {
    "computer_tech": {
        "label": "Компьютерная техника",
        "description": "Компьютеры, комплектующие, сети, периферия и печать.",
        "tone": "green",
    },
    "home_appliances": {
        "label": "Бытовая техника",
        "description": "Кухня, уборка, климат и техника для ухода.",
        "tone": "amber",
    },
    "other_categories": {
        "label": "Остальные товары",
        "description": "Телефоны, ТВ, инструменты, дом, авто и прочие категории.",
        "tone": "blue",
    },
}

DISPLAY_NAME_OVERRIDES = {
    "additive4fuel": "Присадки в топливо",
    "air_filters": "Воздушные фильтры",
    "angle_grinder": "Углошлифмашины",
    "antivirus": "Антивирусы",
    "aquariumequip": "Оборудование для аквариумов",
    "art_goods": "Товары для творчества",
    "backpack": "Рюкзаки",
    "barcode": "Сканеры штрихкодов",
    "bath_furniture": "Мебель для ванной",
    "battery": "Аккумуляторы",
    "bed": "Кровати",
    "bedlinen": "Постельное белье",
    "benchgrinder": "Точильные станки",
    "bits_heads": "Биты и головки",
    "blower": "Воздуходувки",
    "body_care": "Уход за телом",
    "bolts_studs": "Болты и шпильки",
    "buildingkit": "Конструкторы",
    "cabin_filters": "Салонные фильтры",
    "cable": "Кабели",
    "carholder": "Автодержатели",
    "carpets_home": "Ковры",
    "cartridges": "Картриджи",
    "chainsaw": "Цепные пилы",
    "chair": "Стулья",
    "childcarseat": "Детские автокресла",
    "chiselshamdrills": "Зубила и буровые насадки",
    "collar": "Ошейники",
    "compressor": "Компрессоры",
    "computer_cleanin": "Чистящие средства для компьютеров",
    "desktoppc": "Настольные компьютеры",
    "digitalsignage": "Информационные панели",
    "dispenser": "Диспенсеры",
    "disposer": "Измельчители отходов",
    "dresser": "Комоды",
    "drillbits": "Сверла",
    "drills": "Дрели",
    "dvr": "Видеорегистраторы",
    "electric_panel": "Электрощиты",
    "electric_saw": "Электропилы",
    "engraver": "Граверы",
    "externalhdd": "Внешние SSD/HDD",
    "fan": "Кулеры и охлаждение",
    "faucet": "Смесители",
    "flowerpot": "Цветочные горшки",
    "fretsaw": "Лобзики",
    "gardenfurniture": "Садовая мебель",
    "gps": "GPS-навигаторы",
    "grinder": "Шлифмашины",
    "hairclipper": "Машинки для стрижки",
    "headphones_accs": "Аксессуары для наушников",
    "hedgetrimmers": "Кусторезы",
    "hifiaudio": "Hi-Fi аудио",
    "hoods": "Вытяжки",
    "household_tools": "Хозяйственные инструменты",
    "kitchen_table": "Кухонные столы",
    "laserlevel": "Лазерные уровни",
    "measuringacs": "Измерительные аксессуары",
    "metal_cutter": "Резаки по металлу",
    "microphones": "Микрофоны",
    "moddingpc": "Моддинг ПК",
    "monoblock": "Моноблоки",
    "mousepad": "Коврики для мыши",
    "multimeter": "Мультиметры",
    "nailer": "Нейлеры",
    "nas": "NAS-накопители",
    "optical": "Оптические приводы",
    "outdoor_light": "Уличное освещение",
    "oven_cooker": "Плиты и духовки",
    "peripheralkits": "Комплекты периферии",
    "photopaper": "Фотобумага",
    "powerline": "Powerline-адаптеры",
    "powerstations": "Портативные электростанции",
    "powertools_sp": "Специнструмент",
    "powertoolset": "Наборы электроинструмента",
    "printers": "Принтеры",
    "projectors": "Проекторы",
    "pump": "Насосы",
    "remote": "Пульты ДУ",
    "rotaryhammers": "Перфораторы",
    "scanner": "Сканеры",
    "screwdriver": "Шуруповерты",
    "shower_trays": "Душевые поддоны",
    "showerbox": "Душевые кабины",
    "shredder": "Шредеры",
    "siphon": "Сифоны",
    "sound": "Акустика",
    "switch": "Сетевые коммутаторы",
    "table": "Столы",
    "thermal": "Термопаста и термоинтерфейсы",
    "toolbox": "Ящики для инструментов",
    "tools_accum": "Аккумуляторный инструмент",
    "ups": "ИБП",
    "ups_battery": "Батареи для ИБП",
    "vibrators": "Вибраторы",
    "videodoorphone": "Видеодомофоны",
    "voltageregulator": "Стабилизаторы напряжения",
    "wantenna": "ТВ-антенны",
    "wardrobes": "Шкафы",
    "washbasin": "Раковины",
    "watch": "Часы",
    "water_bottles": "Бутылки для воды",
    "wirelessap": "Точки доступа Wi‑Fi",
    "woodrouter": "Фрезеры",
    "woodworking": "Деревообрабатывающий инструмент",
    "wrench": "Гаечные ключи",
    "wspeaker": "Портативные колонки",
    "xmaslights": "Новогодние гирлянды",
}

MODE_OPTIONS = {
    "backfill": {
        "label": "Дописать только отсутствующее",
        "description": "Безопасный режим. Добавляет только то, чего нет в таблице.",
    },
    "full_parse": {
        "label": "Полный парсинг заново",
        "description": "Полностью очищает выбранный лист и переписывает его заново.",
    },
    "cleanup_only": {
        "label": "Очистить лист по категориям",
        "description": "Оставляет в листе только выбранные категории и ничего не парсит.",
    },
}


app = Flask(__name__)

job_lock = threading.Lock()
job_state = {
    "job_id": None,
    "status": "idle",
    "mode": "",
    "sheet_tab": parser.SHEET_TAB,
    "categories": [],
    "command": [],
    "started_at": None,
    "finished_at": None,
    "return_code": None,
    "message": "",
    "log_lines": deque(maxlen=MAX_LOG_LINES),
    "process": None,
    "stop_requested": False,
}
sheet_count_cache = {}
target_job_lock = threading.Lock()
target_job_state = {
    "job_id": None,
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "message": "",
    "total": 0,
    "processed": 0,
    "found": 0,
    "not_found": 0,
    "unavailable": 0,
    "written": 0,
    "scanned_categories": 0,
    "total_categories": 0,
    "current_category": "",
    "results": [],
    "thread": None,
}


def serialize_target_state():
    with target_job_lock:
        state = dict(target_job_state)
        thread = state.pop("thread", None)
        state["is_running"] = bool(thread and thread.is_alive())
        total = int(state.get("total") or 0)
        processed = int(state.get("processed") or 0)
        state["percent"] = int(processed / total * 100) if total else 0
        return state


def set_target_state(**kwargs):
    with target_job_lock:
        target_job_state.update(kwargs)


def normalize_target_items(raw_items):
    items = []
    seen = set()
    for item in raw_items or []:
        oid = str((item or {}).get("onliner_id") or "").strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        items.append({
            "onliner_id": oid,
            "name": str((item or {}).get("name") or "").strip(),
            "parent_category": str((item or {}).get("parent_category") or "").strip(),
            "strict_api": bool((item or {}).get("strict_api")),
        })
    return items


def _target_result(oid, name, category, url="", source=""):
    return {
        "onliner_id": str(oid or "").strip(),
        "name": str(name or "").strip(),
        "category": str(category or "").strip(),
        "url": str(url or "").strip(),
        "source": str(source or "").strip(),
    }


def _native_schema_category(schema):
    schema = schema or {}
    key = str(schema.get("key") or "").strip()
    return str(schema.get("name") or parser.CATEGORIES.get(key) or key).strip()


def _trusted_parent_category(parent_category, product_name=""):
    text = str(product_name or "").strip()
    if re.search(r"^\s*сетевая карта\b", text, flags=re.IGNORECASE):
        return "Сетевые адаптеры и сетевые карты"
    if re.search(r"^\s*разветвитель usb\b", text, flags=re.IGNORECASE):
        return "USB-хабы"
    if re.search(r"\bcooling fan\b", text, flags=re.IGNORECASE):
        return "Кулеры"
    if re.search(r"^\s*(?:вентилятор|радиатор)\b", text, flags=re.IGNORECASE):
        return "Кулеры"
    if re.search(r"^\s*спикерфон\b", text, flags=re.IGNORECASE):
        return "Спикерфоны"
    if re.search(r"^\s*телефон ip\b", text, flags=re.IGNORECASE):
        return "Проводные телефоны"
    if (
        re.search(r"^\s*кр[еe]пление\b", text, flags=re.IGNORECASE)
        and re.search(r"2[.,]?5.*3[.,]?5", text, flags=re.IGNORECASE)
    ):
        return "Моддинг, аксессуары для системных блоков"
    return TARGET_PARENT_CATEGORY_HINTS.get(str(parent_category or "").strip().casefold(), "")


def _target_match_tokens(value):
    tokens = re.findall(r"[a-zа-яё0-9]+", str(value or "").casefold())
    return {
        token for token in tokens
        if len(token) >= 3 and token not in TARGET_MATCH_STOP_TOKENS
    }


def _target_name_match_score(local_name, candidate_name):
    local_tokens = _target_match_tokens(local_name)
    candidate_tokens = _target_match_tokens(candidate_name)
    shared = local_tokens & candidate_tokens
    distinctive = {
        token for token in shared
        if len(token) >= 5 and re.search(r"[a-zа-яё]", token) and re.search(r"\d", token)
    }
    if distinctive:
        return (2, len(distinctive), len(shared))
    if len(shared) >= 3:
        return (1, 0, len(shared))
    return None


def _target_result_from_product(item, product, source):
    category = _native_schema_category((product or {}).get("schema") or {})
    if not category:
        return None
    return _target_result(
        item.get("onliner_id", ""),
        product.get("full_name") or product.get("name") or item.get("name", ""),
        category,
        product.get("html_url", ""),
        source,
    )


def _fetch_target_products(query):
    encoded_query = quote_plus(query)
    had_response = False
    routes = _load_target_proxy_routes()
    for url_template in TARGET_LOOKUP_URLS:
        for proxies in routes:
            try:
                response = requests.get(
                    url_template.format(query=encoded_query),
                    timeout=TARGET_LOOKUP_TIMEOUT,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; PriceMixerTargetLookup/1.0)"},
                    proxies=proxies,
                )
                had_response = True
                if response.status_code == 200:
                    return (response.json() or {}).get("products", [])
            except Exception:
                continue
    return [] if had_response else None


def _load_target_proxy_routes():
    try:
        with open(TARGET_LOOKUP_SETTINGS_PATH, encoding="utf-8") as settings_file:
            settings = json.load(settings_file) or {}
    except Exception:
        settings = {}

    routes = []
    for item in settings.get("proxy_pool") or []:
        if isinstance(item, str):
            proxy_url = item.strip()
            proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
        elif isinstance(item, dict):
            http_proxy = str(item.get("http") or item.get("all") or "").strip()
            https_proxy = str(item.get("https") or item.get("all") or http_proxy).strip()
            proxies = {key: value for key, value in {"http": http_proxy, "https": https_proxy}.items() if value}
        else:
            proxies = {}
        if proxies:
            routes.append(proxies)
    if settings.get("allow_direct", True) or not routes:
        routes.append(None)
    return routes


def resolve_target_item_by_id(item, api_available=True):
    oid = str(item.get("onliner_id") or "").strip()
    if not oid:
        return None
    strict_api = bool(item.get("strict_api"))
    hint_category = _trusted_parent_category(item.get("parent_category"), item.get("name"))
    if api_available:
        products = _fetch_target_products(oid)
        if products is None:
            if strict_api:
                return {"onliner_id": oid, "_lookup_unavailable": True}
            return (
                _target_result(oid, item.get("name", ""), hint_category, source="category_parent_hint")
                if hint_category else {"onliner_id": oid, "_lookup_unavailable": True}
            )
        for product in products or []:
            if str(parser.safe_get_catalog_id(product) or "").strip() != oid:
                continue
            result = _target_result_from_product(item, product, "catalog_api_id")
            if result:
                return result

        products = _fetch_target_products(item.get("name", ""))
        if products is None:
            if strict_api:
                return {"onliner_id": oid, "_lookup_unavailable": True}
            return (
                _target_result(oid, item.get("name", ""), hint_category, source="category_parent_hint")
                if hint_category else {"onliner_id": oid, "_lookup_unavailable": True}
            )
        for product in products or []:
            if str(parser.safe_get_catalog_id(product) or "").strip() != oid:
                continue
            result = _target_result_from_product(item, product, "catalog_api_id")
            if result:
                return result
        if strict_api:
            return None
        if hint_category:
            return _target_result(oid, item.get("name", ""), hint_category, source="category_parent_hint")

        best = None
        for product in products or []:
            result = _target_result_from_product(item, product, "catalog_api_name")
            if not result:
                continue
            score = _target_name_match_score(
                item.get("name", ""),
                product.get("full_name") or product.get("extended_name") or product.get("name", ""),
            )
            if score and (best is None or score > best[0]):
                best = (score, result)
        if best:
            return best[1]

    if hint_category:
        return _target_result(oid, item.get("name", ""), hint_category, source="category_parent_hint")
    return None


def _target_source_note(results):
    counts = Counter(str(item.get("source") or "").strip() for item in results or [])
    return (
        " Источники: точный ID — "
        f"{counts.get('catalog_api_id', 0)}, поиск по названию — "
        f"{counts.get('catalog_api_name', 0)}, безопасная категория из названия — "
        f"{counts.get('category_parent_hint', 0)}."
    )


def run_target_lookup_in_background(items):
    job_id = str(uuid.uuid4())[:8]
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    set_target_state(
        job_id=job_id,
        status="running",
        started_at=started_at,
        finished_at=None,
        message="Ищу категории по OnlinerID, названию и безопасным подсказкам.",
        total=len(items),
        processed=0,
        found=0,
        not_found=0,
        unavailable=0,
        written=0,
        scanned_categories=0,
        total_categories=len(parser.CATEGORIES),
        current_category="",
        results=[],
    )

    def worker():
        wanted = {item["onliner_id"]: item for item in items}
        resolved = {}
        unavailable = set()
        not_found = set()
        try:
            processed = 0
            with ThreadPoolExecutor(max_workers=min(TARGET_LOOKUP_WORKERS, max(len(items), 1))) as pool:
                futures = {pool.submit(resolve_target_item_by_id, item, True): item for item in items}
                for future in as_completed(futures):
                    oid = futures[future]["onliner_id"]
                    try:
                        result = future.result()
                    except Exception:
                        result = {"onliner_id": oid, "_lookup_unavailable": True}
                    if result and result.get("_lookup_unavailable"):
                        unavailable.add(oid)
                    elif result:
                        resolved[result["onliner_id"]] = result
                    else:
                        not_found.add(oid)
                    processed += 1
                    set_target_state(
                        processed=processed,
                        found=len(resolved),
                        not_found=len(not_found),
                        unavailable=len(unavailable),
                        written=len(resolved),
                    )
            set_target_state(
                found=len(resolved),
                not_found=len(not_found),
                unavailable=len(unavailable),
                written=len(resolved),
            )

            results = [resolved[oid] for oid in wanted if oid in resolved]
            missing = [oid for oid in wanted if oid in not_found]
            unavailable_ids = [oid for oid in wanted if oid in unavailable]
            missing_note = (
                " Оставлены в «Требует сортировки»: Onliner API не вернул карточку по ID."
                if missing else ""
            )
            unavailable_note = (
                " API Onliner недоступен по сети для "
                f"{len(unavailable_ids)} ID: они оставлены в очереди, повторите допарсинг позже."
                if unavailable_ids else ""
            )
            set_target_state(
                status="completed",
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                message=(
                    f"Готово. Найдено {len(results)}, не найдено {len(missing)}, "
                    f"API недоступен для {len(unavailable_ids)}."
                    f"{_target_source_note(results)}{missing_note}{unavailable_note}"
                ),
                processed=len(items),
                found=len(results),
                not_found=len(missing),
                unavailable=len(unavailable_ids),
                written=len(results),
                current_category="",
                results=results,
            )
        except Exception as exc:
            set_target_state(
                status="failed",
                finished_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                message=f"Ошибка точечного допарсинга: {exc}",
                processed=len(resolved),
                found=len(resolved),
                not_found=max(len(items) - len(resolved), 0),
                unavailable=0,
                written=len(resolved),
                current_category="",
                results=list(resolved.values()),
            )

    thread = threading.Thread(target=worker, daemon=True)
    set_target_state(thread=thread)
    thread.start()


def should_keep_log_line(line):
    text = str(line or "").strip()
    if not text:
        return False

    keep_prefixes = (
        "▶️ Запуск:",
        "🚀",
        "📚",
        "📄",
        "🔎",
        "🧩",
        "🔌",
        "📊 Категорий:",
        "📦 Парсим категорию:",
        "🔁 Backfill категории:",
        "✅ Найдено",
        "✅ Backfill",
        "📊 Backfill завершён.",
        "📊 Завершено:",
        "🧹",
        "⏸️",
        "⏹️",
        "⚠️",
        "❌",
        "💾",
        "ℹ️",
    )
    if text.startswith(keep_prefixes):
        return True

    if text.startswith("+ записано:"):
        return not text.startswith("+ записано: 0")

    if text.startswith("+ backfill добавлено:"):
        return not text.startswith("+ backfill добавлено: 0")

    return False


def category_title(slug):
    return DISPLAY_NAME_OVERRIDES.get(slug, parser.CATEGORIES.get(slug, slug))


def build_category_list():
    items = []
    for slug, title in sorted(parser.CATEGORIES.items(), key=lambda x: category_title(x[0]).lower()):
        items.append(
            {
                "slug": slug,
                "title": category_title(slug),
                "raw_title": title,
            }
        )
    return items


def build_category_groups():
    it_slugs = set(parser.COMPUTER_TECH_CATEGORY_SLUGS) | {
        "desktoppc",
        "monoblock",
        "keyboards",
        "mouse",
        "mousepad",
        "sound",
        "soundcard",
        "wspeaker",
        "peripheralkits",
        "usbhub",
        "usbflash",
        "headphones",
        "headphones_accs",
    }
    media_slugs = {
        "tv",
        "wallmount",
        "console",
        "soundbar",
        "mobile",
    }
    all_items = build_category_list()
    grouped = {"it": [], "media": [], "other": []}
    for item in all_items:
        if item["slug"] in it_slugs:
            bucket = "it"
        elif item["slug"] in media_slugs:
            bucket = "media"
        else:
            bucket = "other"
        grouped[bucket].append(item)
    return grouped


def build_presets():
    all_slugs = set(parser.CATEGORIES.keys())
    computer_categories = all_slugs & set(parser.COMPUTER_TECH_CATEGORY_SLUGS)
    home_categories = all_slugs & HOME_APPLIANCE_CATEGORY_SLUGS
    profile_categories = {
        "computer_tech": computer_categories,
        "home_appliances": home_categories,
        "other_categories": all_slugs - computer_categories - home_categories,
    }

    presets = {}
    for key, data in PRESETS.items():
        presets[key] = {
            "label": data["label"],
            "description": data["description"],
            "tone": data["tone"],
            "categories": sorted(profile_categories[key]),
        }
    return presets


def extract_progress(log_lines, selected_categories, progress_state=None):
    completed = 0
    total = len(selected_categories or [])
    page_match = None

    for line in reversed(list(log_lines)):
        if not page_match:
            page_match = re.search(r"страница\s+(\d+)", line, flags=re.IGNORECASE)

        m = re.search(r"Категорий:\s*(\d+)\s*/\s*(\d+)", line)
        if m:
            completed = int(m.group(1))
            total = int(m.group(2))
            break

    percent = int((completed / total) * 100) if total else 0
    current_page = int(page_match.group(1)) if page_match else None
    if current_page is None and progress_state:
        current = progress_state.get("current") or {}
        next_page = current.get("next_page")
        if next_page is not None:
            try:
                current_page = max(int(next_page) - 1, 1)
            except Exception:
                current_page = None
    return {
        "completed_categories": completed,
        "total_categories": total,
        "remaining_categories": max(total - completed, 0),
        "percent": percent,
        "current_page": current_page,
    }


def load_progress_state_for_sheet(sheet_tab):
    for progress_file in (parser.BACKFILL_PROGRESS_FILE, parser.PROGRESS_FILE):
        try:
            if progress_file.exists():
                state = json.loads(progress_file.read_text(encoding="utf-8"))
                if state.get("sheet_tab") == sheet_tab:
                    return state
        except Exception:
            continue
    return None


def get_items_count(sheet_tab):
    progress_state = load_progress_state_for_sheet(sheet_tab)
    if progress_state and "next_row" in progress_state:
        try:
            return max(int(progress_state["next_row"]) - 2, 0)
        except Exception:
            pass

    now = time.time()
    cached = sheet_count_cache.get(sheet_tab)
    if cached and (now - cached["ts"] <= SHEET_COUNT_CACHE_TTL):
        return cached["count"]

    try:
        sheet = parser.authorize_google_sheets(sheet_tab=sheet_tab)
        count = max(int(sheet.row_count or 1) - 1, 0)
        sheet_count_cache[sheet_tab] = {"count": count, "ts": now}
        return count
    except Exception:
        if cached:
            return cached["count"]
        return None


def serialize_state():
    with job_lock:
        process = job_state["process"]
        progress_state = load_progress_state_for_sheet(job_state["sheet_tab"])
        progress = extract_progress(job_state["log_lines"], job_state["categories"], progress_state=progress_state)
        items_count = get_items_count(job_state["sheet_tab"])
        return {
            "job_id": job_state["job_id"],
            "status": job_state["status"],
            "mode": job_state["mode"],
            "sheet_tab": job_state["sheet_tab"],
            "items_count": items_count,
            "categories": list(job_state["categories"]),
            "command": list(job_state["command"]),
            "started_at": job_state["started_at"],
            "finished_at": job_state["finished_at"],
            "return_code": job_state["return_code"],
            "message": job_state["message"],
            "is_running": bool(process and process.poll() is None),
            "log": "\n".join(job_state["log_lines"]),
            "progress": progress,
        }


def append_log_line(line):
    clean = str(line).rstrip("\n")
    if not should_keep_log_line(clean):
        return
    with job_lock:
        job_state["log_lines"].append(clean)


def set_job_state(**kwargs):
    with job_lock:
        for key, value in kwargs.items():
            if key == "log_lines":
                job_state["log_lines"] = deque(value, maxlen=MAX_LOG_LINES)
            else:
                job_state[key] = value


def classify_job_result(return_code, stop_requested=False):
    stopped_codes = {-signal.SIGINT, 128 + signal.SIGINT}
    if stop_requested or return_code in stopped_codes:
        return "stopped", "Остановлено. Прогресс сохранён, можно продолжить позже."
    if return_code == 0:
        return "completed", "Задача завершена успешно."
    return "failed", "Задача завершилась с ошибкой."


def build_command(payload):
    mode = payload["mode"]
    selected_categories = payload["categories"]
    if not selected_categories:
        raise ValueError("Нужно выбрать хотя бы одну категорию.")

    cmd = [sys.executable, "-u", str(SCRIPT_PATH)]

    if mode == "backfill":
        cmd.append("--backfill-missing")
    elif mode == "cleanup_only":
        cmd.append("--cleanup-sheet")
    elif mode != "full_parse":
        raise ValueError("Неизвестный режим запуска.")

    cmd.extend(["--sheet-tab", payload["sheet_tab"]])
    cmd.extend(["--categories", ",".join(selected_categories)])

    if payload["resume"]:
        cmd.append("--resume")
    if payload["match_text"]:
        cmd.extend(["--match-text", payload["match_text"]])
    if payload["profile"]:
        cmd.extend(["--profile", payload["profile"]])
    if payload["electronics_only"]:
        cmd.append("--electronics-only")

    return cmd


def run_job_in_background(command, payload):
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    job_id = str(uuid.uuid4())[:8]

    with job_lock:
        job_state["job_id"] = job_id
        job_state["status"] = "running"
        job_state["mode"] = payload["mode"]
        job_state["sheet_tab"] = payload["sheet_tab"]
        job_state["categories"] = list(payload["categories"])
        job_state["command"] = list(command)
        job_state["started_at"] = started_at
        job_state["finished_at"] = None
        job_state["return_code"] = None
        job_state["message"] = "Задача запущена."
        job_state["log_lines"] = deque(maxlen=MAX_LOG_LINES)
        job_state["stop_requested"] = False

    def worker():
        append_log_line(f"▶️ Запуск: {' '.join(command)}")
        proc = subprocess.Popen(
            command,
            cwd=str(APP_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        set_job_state(process=proc)

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                append_log_line(line)
        finally:
            return_code = proc.wait()
            finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
            with job_lock:
                stop_requested = bool(job_state.get("stop_requested"))
            status, message = classify_job_result(return_code, stop_requested=stop_requested)
            set_job_state(
                process=None,
                status=status,
                return_code=return_code,
                finished_at=finished_at,
                message=message,
            )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def parse_payload(raw_payload):
    categories = raw_payload.get("categories") or []
    categories = [str(item).strip() for item in categories if str(item).strip()]
    categories = [slug for slug in categories if slug in parser.CATEGORIES]

    payload = {
        "mode": str(raw_payload.get("mode") or "backfill").strip(),
        "sheet_tab": str(raw_payload.get("sheet_tab") or parser.SHEET_TAB).strip() or parser.SHEET_TAB,
        "categories": categories,
        "resume": bool(raw_payload.get("resume")),
        "match_text": str(raw_payload.get("match_text") or "").strip(),
        "profile": str(raw_payload.get("profile") or "").strip(),
        "electronics_only": bool(raw_payload.get("electronics_only")),
    }
    return payload


@app.get("/")
def index():
    return render_template(
        "ui_index.html",
        categories=build_category_list(),
        category_groups=build_category_groups(),
        presets=build_presets(),
        default_sheet_tab=parser.SHEET_TAB,
        mode_options=MODE_OPTIONS,
        profile_options=[
            {"value": "", "label": "Без профиля"},
            {"value": "computer_tech", "label": "Компьютерная техника"},
            {"value": "light_electronics", "label": "Потребительская электроника"},
            {"value": "all_other", "label": "Все остальные"},
        ],
    )


@app.get("/api/status")
def api_status():
    return jsonify(serialize_state())


@app.post("/api/run")
def api_run():
    payload = parse_payload(request.get_json(force=True, silent=False) or {})

    with job_lock:
        process = job_state["process"]
        if process and process.poll() is None:
            return jsonify({"ok": False, "error": "Сейчас уже выполняется другая задача. Сначала останови или дождись завершения."}), 409

    try:
        command = build_command(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    run_job_in_background(command, payload)
    return jsonify({"ok": True, "status": serialize_state()})


@app.post("/api/stop")
def api_stop():
    with job_lock:
        process = job_state["process"]
        if not process or process.poll() is not None:
            return jsonify({"ok": False, "error": "Активная задача не найдена."}), 400
        pid = process.pid

    os.killpg(pid, signal.SIGINT)
    append_log_line("⏹️ Отправлен SIGINT для корректной остановки.")
    set_job_state(
        stop_requested=True,
        message="Останавливаю задачу и сохраняю прогресс...",
    )
    return jsonify({"ok": True, "status": serialize_state()})


@app.post("/api/price-mixer/run")
def api_price_mixer_run():
    items = normalize_target_items((request.get_json(force=True, silent=False) or {}).get("items"))
    if not items:
        return jsonify({"ok": False, "error": "Очередь товаров пуста."}), 400
    with target_job_lock:
        thread = target_job_state.get("thread")
        if thread and thread.is_alive():
            return jsonify({"ok": False, "error": "Точечный допарсинг уже выполняется."}), 409
    run_target_lookup_in_background(items)
    return jsonify({"ok": True, "status": serialize_target_state()})


@app.get("/api/price-mixer/status")
def api_price_mixer_status():
    return jsonify(serialize_target_state())


if __name__ == "__main__":
    print(f"UI server: http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
