"""Product ID, name, category, and dataframe normalization helpers."""

import math
import re

import numpy as np
import pandas as pd


def normalize_onliner_id(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    return text


def count_rows_without_onliner_id(df):
    if df is None or getattr(df, "empty", False):
        return 0
    if "OnlinerID" not in df.columns:
        return len(df)
    return sum(1 for _, row in df.iterrows() if not normalize_onliner_id(row.get("OnlinerID", "")))


def count_rows_with_duplicate_onliner_id(df):
    if df is None or getattr(df, "empty", False):
        return 0
    if "OnlinerID" not in df.columns:
        return 0
    counts = {}
    for _, row in df.iterrows():
        oid = normalize_onliner_id(row.get("OnlinerID", ""))
        if not oid:
            continue
        counts[oid] = counts.get(oid, 0) + 1
    duplicate_ids = {oid for oid, cnt in counts.items() if cnt > 1}
    if not duplicate_ids:
        return 0
    return sum(1 for _, row in df.iterrows() if normalize_onliner_id(row.get("OnlinerID", "")) in duplicate_ids)


def normalize_name_key(name):
    text = str(name or "").strip().lower()
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    # No truncation: avoid collisions between long similar names.
    return text


def build_item_category_keys(row):
    """Stable category keys: product name plus optional supplier, without oid/article."""
    keys = []
    name = str(row.get("Название", "")).strip()
    supplier = str(row.get("Поставщик", "")).strip().lower()
    name_key = normalize_name_key(name)
    if supplier and name_key:
        keys.append(f"sname:{supplier}:{name_key}")
    if name_key:
        keys.append(f"name:{name_key}")
    seen = set()
    out = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def build_item_category_key(row):
    keys = build_item_category_keys(row)
    return keys[0] if keys else ""


def infer_category(name):
    """Infer broad internal category from a product name."""
    text = str(name or "").strip().lower()
    if not text:
        return "Без категории"

    text_without_prefix = re.sub(r"^\[[^\]]+\]\s*", "", text).strip()
    norm = re.sub(r"[^a-zа-я0-9\+\s\-]", " ", text)
    norm = re.sub(r"\s+", " ", norm).strip()
    norm_without_prefix = re.sub(r"[^a-zа-я0-9\+\s\-]", " ", text_without_prefix)
    norm_without_prefix = re.sub(r"\s+", " ", norm_without_prefix).strip()

    if re.search(r"^\s*(?:mb|motherboard|мат\s+плат|материнск)", norm_without_prefix):
        return "Материнская плата"

    if re.search(r"^\s*(?:кабель|cable|патч[\s\-]?корд|переходник|удлинитель)\b", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\b(компьютер|моноблок)\b|системный\s+блок|\bпэвм\s+tgpc\b|\btgpc\s+office\b|gaming\s+(?:black|white)|\bdesktop\s+pc\b|iven\s+(?:office|home|pro|ultra)", norm_without_prefix):
        return "Системный блок"

    if re.search(
        r"жидкостн|\baio\b|water[\s\-]?cool|водяного\s+охлаждения|охлажд|термопаст|термопроклад|водян|сжо|радиатор|вентилятор",
        norm_without_prefix,
    ):
        return "Охлаждение"

    if re.search(r"\bкронштейн\w*\b", norm_without_prefix):
        return "Кронштейны"

    monitor_by_name = bool(re.search(r"\bмонитор\b|\bdisplay\b", norm_without_prefix))
    monitor_by_specs = bool(
        re.search(r"^\s*\d{2}(?:[\.,]\d)?\s*[\"”]", text_without_prefix)
        and re.search(r"\b(ips|va|tn|oled|qhd|uhd|hdr|hdmi|vga|displayport|dp)\b|(?:\d{3,4}\s*x\s*\d{3,4})|\b\d{2,3}\s*(?:hz|гц)\b", norm_without_prefix)
    )
    if monitor_by_name or monitor_by_specs:
        return "Монитор"

    if re.search(r"web[\s\-]?cam|web[\s\-]?кам|веб[\s\-]?кам|камера\s+logitech", norm_without_prefix):
        return "Периферия"

    if re.search(r"\bклавиатур|keyboard", norm_without_prefix):
        return "Клавиатура"

    if re.search(r"колонк|акустик|soundbar|speaker", norm_without_prefix):
        return "Акустика"

    if re.search(r"\bмышь\b|\bмыши\b|\bmouse\b|игровая\s+мышь", norm_without_prefix):
        return "Мышь"

    if re.search(r"наушник|гарнитур|headset|headphones", norm_without_prefix):
        return "Наушники"

    if re.search(r"wi[\s\-]?fi|wifi|bluetooth|сетевой\s+usb[\s\-]?адаптер|usb[\s\-]?адаптер.*802\.11", norm_without_prefix):
        return "Сеть"

    if re.search(r"\b(?:micro\s*sd|microsd|sdhc|sdxc|карта\s+памяти)\b", norm_without_prefix):
        return "Накопители USB"

    has_case_words = bool(re.search(r"\bкорпус\b|\bcase\b|midi[\s\-]?tower|mini[\s\-]?tower", norm))
    no_psu_hint = bool(re.search(r"\bбез\s+бп\b|\bбез\s+блока\s+питания\b|\bno\s*psu\b|\bwithout\s+psu\b", norm))
    if has_case_words:
        return "Корпус"

    if re.search(r"\bбп\b|блок питания|power supply|\bpsu\b", norm) and not no_psu_hint:
        return "Блок питания"

    if re.search(r"\bкабель\b|\bcable\b|\bпереходник\b|\badapter\b|\bадаптер\b|\bпатч[\s\-]?корд\b", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\b(dvdrw|dvd[\s\-]?rw|оптическ(?:ий|ий привод)|привод\s+dvd)\b", norm_without_prefix):
        return "Периферия"

    if re.search(r"разветвител[ья]?\s+usb|usb[\s\-]?hub|\bhub\b", norm_without_prefix):
        return "Периферия"

    if re.search(r"\bнабор\b", norm_without_prefix) and re.search(
        r"logitech|defender|sven|клавиатур|keyboard|wireless\s+desktop|desktop\s+mk|mk\d{3}",
        norm_without_prefix,
    ):
        return "Клавиатура"

    if re.search(r"\bssd\b|\bnvme\b|\bm\.?2\b|твердотельн", norm_without_prefix):
        return "SSD"

    if re.search(r"\bhdd\b|жестк|винчестер", norm_without_prefix):
        return "Жесткий диск"

    usb_version_storage_hint = bool(
        re.search(r"\busb\s*[23](?:\s*\d)?\b|\busb[23](?:\s*\d)?\b", norm_without_prefix)
        and re.search(r"\b\d+(?:gb|гб|tb|тб)\b", norm_without_prefix)
    )
    if (
        re.search(r"накопител[ьи]?\s+usb|usb[\s\-]?(?:flash|drive)|\bflash\b|флеш", norm_without_prefix)
        or usb_version_storage_hint
    ):
        return "Накопители USB"

    if re.search(r"\bсумк|чехол для ноутбука|laptop bag|notebook bag|laptop case", norm_without_prefix):
        return "Сумки и чехлы для ноутбуков"

    category_rules = [
        ("Системный блок", [r"\bкомпьютер\b", r"\bмоноблок\b"]),
        ("Системный блок", [r"системный блок", r"\bпэвм\b", r"\btgpc\b", r"iven\s+(?:office|home|pro|ultra)"]),
        ("Аксессуары", [
            r"чехол для планшета",
            r"\bшасси\b",
            r"подставка для ноутбука",
        ]),
        ("Оперативная память", [r"\bddr[345]\b", r"оперативн", r"\bram\b", r"so[\s\-]?dimm", r"\bdimm\b"]),
        ("Охлаждение", [
            r"жидкостн",
            r"\baio\b",
            r"water[\s\-]?cool",
            r"система\s+водяного\s+охлаждения",
            r"водяного\s+охлаждения",
            r"охлажд",
            r"термопаст",
            r"термопроклад",
            r"водян",
            r"сжо",
            r"радиатор",
            r"вентилятор",
        ]),
        ("Ноутбук", [r"(?<!для )ноутбук", r"\blaptop\b", r"\bnotebook\b"]),
        ("Кулер", [r"\bкулер\b", r"cooler"]),
        ("Процессор", [r"(?<!для\s)процессор", r"\bcpu\b", r"\bintel core\b", r"\bryzen\b"]),
        ("Материнская плата", [
            r"материн",
            r"\bmotherboard\b",
            r"\bmb\b",
            r"\bb[34567]\d{2}m?\b",
            r"\bh[456]\d{2}m?\b",
            r"\bz[67]\d{2}\b",
            r"\bx[45667]\d{2}\b",
            r"\ba[3567]\d{2}\b",
        ]),
        ("SSD", [r"\bssd\b", r"\bnvme\b", r"\bm\.?2\b", r"твердотельн"]),
        ("Жесткий диск", [r"\bhdd\b", r"жестк", r"винчестер"]),
        ("Видеокарта", [r"видеокарт", r"\bgpu\b", r"geforce", r"radeon", r"\brtx\b", r"\bgtx\b", r"\brx\s?\d{3,4}\b"]),
        ("Корпус", [r"\bкорпус\b", r"midi[\s\-]?tower", r"mini[\s\-]?tower", r"full[\s\-]?tower"]),
        ("Блок питания", [r"\bбп\b", r"блок питания", r"power supply", r"\bpsu\b"]),
        ("Кронштейны", [r"\bкронштейн\w*\b"]),
        ("Монитор", [r"монитор", r"display"]),
        ("Принтер и МФУ", [r"\bпринтер\b", r"\bпринтеры\b", r"\bмфу\b", r"\bmfp\b"]),
        ("Аксессуары", [r"коврик", r"mouse[\s\-]?pad", r"mousepad"]),
        ("Клавиатура", [r"клавиатур"]),
        ("Мышь", [r"\bмышь\b", r"\bмыши\b", r"\bmouse\b", r"игровая мышь", r"беспроводная мышь"]),
        ("Наушники", [r"наушник", r"гарнитур"]),
        ("Акустика", [r"колонк", r"акустик", r"soundbar"]),
        ("Сеть", [r"роутер", r"маршрутизатор", r"коммутатор", r"точка доступа", r"wifi", r"wi[\s\-]fi"]),
        ("Накопители USB", [
            r"накопител[ьи]?\s+usb",
            r"usb[\s\-]?(?:flash|drive)",
            r"\b(?:micro\s*sd|microsd|sdhc|sdxc|карта\s+памяти)\b",
            r"\bflash\b",
            r"флеш",
        ]),
        ("Кабели и переходники", [r"кабель", r"переходник", r"адаптер", r"патч[\s\-]?корд"]),
    ]

    for category_name, patterns in category_rules:
        for pattern in patterns:
            if re.search(pattern, norm_without_prefix):
                return category_name

    tokens = re.findall(r"[a-zа-я0-9\+\-]+", norm)
    if not tokens:
        return "Без категории"
    return tokens[0].upper()


def normalize_internal_category_name(category):
    """Collapse transient/legacy internal category labels to the canonical UI category."""
    text = str(category or "").strip()
    if not text:
        return ""
    compact = text.lower().replace(",", ".").replace(" ", "")
    aliases = {
        "компьютер": "Системный блок",
        "компьютеры": "Системный блок",
        "моноблок": "Системный блок",
        "моноблоки": "Системный блок",
        "usb2": "Накопители USB",
        "usb2.0": "Накопители USB",
        "usb3": "Накопители USB",
        "usb3.0": "Накопители USB",
        "usb3.1": "Накопители USB",
        "usb3.2": "Накопители USB",
    }
    return aliases.get(compact, text)


def normalize_catalog_category_name(raw_name, available_categories=None):
    """Normalize an All_Catalog category name to an internal category name."""
    text = str(raw_name or "").strip()
    if not text:
        return ""
    available_categories = set(available_categories or [])
    low_to_real = {str(c).strip().lower(): str(c).strip() for c in available_categories if str(c).strip()}
    direct = low_to_real.get(text.lower())
    if direct:
        return direct

    aliases = {
        "процессоры": "Процессор",
        "процессор": "Процессор",
        "cpu": "Процессор",
        "кулеры": "Кулер",
        "кулер": "Кулер",
        "охлаждение": "Охлаждение",
        "сжо": "Охлаждение",
        "материнские платы": "Материнская плата",
        "материнская плата": "Материнская плата",
        "mb": "Материнская плата",
        "оперативная память": "Оперативная память",
        "ram": "Оперативная память",
        "ssd": "SSD",
        "жесткие диски": "Жесткий диск",
        "жесткий диск": "Жесткий диск",
        "hdd": "Жесткий диск",
        "видеокарты": "Видеокарта",
        "видеокарта": "Видеокарта",
        "gpu": "Видеокарта",
        "блоки питания": "Блок питания",
        "блок питания": "Блок питания",
        "бп": "Блок питания",
        "корпуса": "Корпус",
        "корпус": "Корпус",
        "кронштейны": "Кронштейны",
        "кронштейн": "Кронштейны",
        "мониторы": "Монитор",
        "монитор": "Монитор",
        "принтеры и мфу": "Принтер и МФУ",
        "принтеры": "Принтер и МФУ",
        "принтер": "Принтер и МФУ",
        "мфу": "Принтер и МФУ",
        "ноутбуки": "Ноутбук",
        "ноутбук": "Ноутбук",
        "компьютер": "Системный блок",
        "компьютеры": "Системный блок",
        "моноблок": "Системный блок",
        "моноблоки": "Системный блок",
        "системные блоки": "Системный блок",
        "системный блок": "Системный блок",
        "usb2": "Накопители USB",
        "usb2.0": "Накопители USB",
        "usb3": "Накопители USB",
        "usb3.0": "Накопители USB",
        "usb3.1": "Накопители USB",
        "usb3.2": "Накопители USB",
    }
    alias = aliases.get(text.lower(), "")
    if alias:
        if alias.lower() in low_to_real:
            return low_to_real.get(alias.lower(), alias)
        return alias

    inferred = infer_category(text)
    if inferred and inferred != "Без категории":
        if inferred.lower() in low_to_real:
            return low_to_real.get(inferred.lower(), inferred)
        return inferred
    return ""


def normalize_consolidated_columns(df):
    if df is None or df.empty:
        return df
    rename_map = {}
    for col in df.columns:
        text = str(col)
        compact = text.replace("\xa0", "").strip()
        if text == "РќР°Р·РІР°РЅРёРµ":
            rename_map[col] = "Название"
        elif text == "Р¦РµРЅР°":
            rename_map[col] = "Цена"
        elif text == "РџРѕСЃС‚Р°РІС‰РёРє":
            rename_map[col] = "Поставщик"
        elif text == "Р“Р°СЂР°РЅС‚РёСЏ":
            rename_map[col] = "Гарантия"
        elif compact in {"РРЦ", "Р Р Р¦"} or text == "Р\xa0Р\xa0Р¦":
            rename_map[col] = "РРЦ"
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def round_price_to_90(value):
    """Round price to nearest ten using legacy 1-4 down, 5-9 up behavior."""
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return np.nan
    v = float(v)
    if v <= 0:
        return 0.0
    whole = int(math.floor(v))
    last_digit = whole % 10
    if last_digit <= 4:
        rounded = whole - last_digit
    else:
        rounded = whole + (10 - last_digit)
    return float(rounded)
