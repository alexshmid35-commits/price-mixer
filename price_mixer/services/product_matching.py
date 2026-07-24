"""Product name matching and article-token helpers."""

import re
from difflib import SequenceMatcher


NAME_TOKEN_STOP_WORDS = {
    "для", "с", "и", "на", "по", "ret", "rtl", "oem", "box",
    "black", "white", "blue", "red", "green", "grey", "gray", "silver", "gold",
    "черный", "чёрный", "белый", "синий", "голубой", "красный", "зеленый", "зелёный",
    "серый", "серебристый", "золотой", "желтый", "жёлтый", "orange", "pink", "purple",
}

COLOR_WORDS = {
    "black", "white", "blue", "red", "green", "grey", "gray", "silver", "gold",
    "черный", "чёрный", "белый", "синий", "голубой", "красный", "зеленый", "зелёный",
    "серый", "серебристый", "золотой", "желтый", "жёлтый", "orange", "pink", "purple",
}

IMPORTANT_GENERIC_TOKENS = {
    "беспроводная", "беспроводной", "беспроводное", "wireless",
    "проводная", "проводной", "wired",
    "игровая", "игровой", "gaming",
    "гарнитура", "наушники", "headset", "headphones",
    "мышь", "мышка", "mouse",
    "клавиатура", "keyboard",
    "колонки", "колонка", "акустика", "speakers",
    "черный", "чёрный", "белый", "синий", "красный", "зеленый", "зелёный",
    "black", "white", "blue", "red", "green", "grey", "gray", "pink", "purple",
}

COLOR_GROUPS = [
    ("black", {"black", "черный", "чёрный", "черн", "blk", "bk"}),
    ("white", {"white", "белый", "wht", "wh"}),
    ("silver", {"silver", "grey", "gray", "серый", "серебристый", "серебро"}),
    ("blue", {"blue", "синий", "голубой", "dark blue"}),
    ("red", {"red", "красный"}),
    ("green", {"green", "зеленый", "зелёный"}),
    ("gold", {"gold", "золотой", "золото"}),
    ("yellow", {"yellow", "желтый", "жёлтый"}),
    ("orange", {"orange", "оранжевый"}),
    ("purple", {"purple", "violet", "фиолетовый"}),
    ("pink", {"pink", "розовый"}),
    ("brown", {"brown", "коричневый"}),
]
COLOR_CANON = {word: key for key, words in COLOR_GROUPS for word in words}

CATEGORY_GROUPS = [
    frozenset(["бп", "блок питания", "блоки питания", "psu", "power supply"]),
    frozenset(["ибп", "ибп ", "источник бесперебойного питания", "ups"]),
    frozenset(["мфу", "мфу ", "multifunctional", "принтер-сканер"]),
    frozenset(["принтер", "printer"]),
    frozenset(["сканер", "scanner"]),
    frozenset(["монитор", "monitor", "дисплей", "display"]),
    frozenset(["клавиатура", "keyboard"]),
    frozenset(["мышь", "мышка", "mouse"]),
    frozenset(["гарнитура", "наушники", "headset", "headphones"]),
    frozenset(["колонки", "колонка", "акустика", "speakers"]),
    frozenset(["корпус", "case"]),
    frozenset([
        "кулер", "cooler", "охладитель", "cooling",
        "кулер для процессора", "процессорный кулер",
    ]),
    frozenset(["видеокарта", "видеоадаптер", "gpu", "graphics"]),
    frozenset(["процессор", "cpu", "processor"]),
    frozenset(["материнская плата", "материнка", "motherboard", "mainboard"]),
    frozenset(["оперативная память", "память ddr", "озу", "ram"]),
    frozenset(["ssd", "ссд накопитель", "твердотельный накопитель"]),
    frozenset(["hdd", "жесткий диск", "жёсткий диск", "hdd накопитель"]),
    frozenset(["ноутбук", "laptop", "notebook"]),
    frozenset(["моноблок", "all in one", "all-in-one", "aio pc"]),
    frozenset(["планшет", "tablet"]),
    frozenset(["смартфон", "телефон", "phone", "smartphone"]),
    frozenset(["кабель", "cable", "шнур", "провод"]),
    frozenset(["разветвитель", "разветвитель для", "хаб", "hub", "splitter", "usb-хаб", "usb хаб", "usb-hub"]),
    frozenset(["dok-stantsiya", "dok stantsiya", "dock station", "док-станция", "док станция"]),
    frozenset(["адаптер", "adapter", "переходник", "конвертер"]),
    frozenset(["флеш", "флешка", "usb накопитель", "usb flash"]),
    frozenset(["роутер", "маршрутизатор", "router", "wi-fi роутер"]),
    frozenset(["коммутатор", "switch", "свитч"]),
    frozenset(["зарядное устройство", "сзу", "зарядка", "charger"]),
    frozenset(["источник питания", "блок питания для ноутбука"]),
    frozenset(["стабилизатор", "стабилизатор напряжения"]),
    frozenset(["термопаста", "термопрокладка", "thermal paste"]),
    frozenset(["кронштейн", "крепление", "bracket", "mount"]),
    frozenset(["внешний накопитель", "внешний жесткий диск", "portable hdd"]),
    frozenset(["картридж", "cartridge", "тонер"]),
    frozenset(["веб-камера", "вебкамера", "webcam", "web-cam", "web cam"]),
    frozenset(["микрофон", "microphone"]),
    frozenset(["удлинитель", "сетевой фильтр", "surge protector"]),
    frozenset(["охлаждающая подставка", "подставка для ноутбука"]),
    frozenset(["система охлаждения", "водяное охлаждение", "сжо", "aio cooler"]),
    frozenset(["вентилятор", "fan", "корпусной вентилятор"]),
    frozenset(["память", "модуль памяти"]),
]
CATEGORY_LOOKUP = {
    form.strip().lower(): group
    for group in CATEGORY_GROUPS
    for form in group
}

SPEC_CODE_PREFIXES = {
    "SFF", "SAS", "SATA", "SASATA", "PCIE", "PCIEX", "M2",
    "USB", "HDMI", "DISPLAYPORT", "THUNDERBOLT", "DIMM", "SODIMM",
    "DDR", "LPDDR", "ATX", "EPS", "NVME", "OCU", "OCULINK",
    "SOC", "SOCKET", "LGA", "WIFI", "LAN", "BT", "ARGB", "RGB", "RAID",
}

ARTICLE_LIKE_BRAND_TOKENS = {
    "a4tech", "1stplayer", "2power", "2e", "3q", "4gamers", "5bites",
}

MEASURE_UNITS = {
    "MM", "CM", "M", "W", "V", "A", "MHZ", "GHZ",
    "TB", "GB", "MB", "KB", "DPI", "PPI", "RPM", "HZ",
    "BIT", "BITS", "MS", "NM", "G", "KG", "LM",
}


def name_tokens(text):
    words = re.findall(r"[a-zа-я0-9]+", str(text or "").lower())
    out = []
    seen = set()

    def push(token):
        token = str(token or "").strip()
        if len(token) < 3 or token in NAME_TOKEN_STOP_WORDS or token in seen:
            return
        seen.add(token)
        out.append(token)

    for word in words:
        push(word)
        match = re.match(r"^(\d{2,4})(w|mhz|gb|tb)$", word)
        if match:
            push(match.group(1))
            continue
        match = re.match(r"^(\d{2,4})(mm)$", word)
        if match:
            push(match.group(1))
    return out


def normalize_compact_name(text):
    return re.sub(r"[^a-zа-я0-9]+", "", str(text or "").lower())


def normalize_match_text(text):
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"\(([^()]*)\)", lambda match: " " if is_color_only_chunk(match.group(1)) else f" {match.group(1)} ", raw)
    raw = re.sub(r"[^a-zа-я0-9]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def paren_chunks(text):
    return [str(item).strip() for item in re.findall(r"\(([^()]*)\)", str(text or "")) if str(item).strip()]


def is_color_only_chunk(text):
    words = [word for word in re.findall(r"[a-zа-я0-9]+", str(text or "").lower()) if len(word) >= 3]
    if not words:
        return False
    return all(word in COLOR_WORDS for word in words)


def model_hint_tokens(text, tgpc_pc_code_queries=None, extract_article_candidates=None):
    raw = str(text or "")
    out = set(article_like_tokens(
        raw,
        tgpc_pc_code_queries=tgpc_pc_code_queries,
        extract_article_candidates=extract_article_candidates,
    ))
    out.update(fan_series_match_tokens(raw))
    for chunk in paren_chunks(raw):
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{3,}", chunk):
            norm = normalize_compact_name(token)
            upper = norm.upper()
            if (
                len(norm) >= 4
                and any(ch.isdigit() for ch in norm)
                and any(ch.isalpha() for ch in norm)
                and not re.match(r"^\d+[xX][A-Z]", upper)
                and not is_spec_code(upper)
            ):
                out.add(norm)
    for token in name_tokens(raw):
        if len(token) >= 4 and any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
            upper = token.upper()
            if not re.match(r"^\d+[xX][A-Z]", upper) and not is_spec_code(upper):
                out.add(token)
    out.difference_update(ARTICLE_LIKE_BRAND_TOKENS)
    refined = set()
    for token in out:
        refined.add(token)
        match = re.match(r"([a-z]{1,5}\d{2,5}[a-z]{0,3})", token)
        if match:
            refined.add(match.group(1))
    return refined


def token_family_match(left_tokens, right_tokens):
    left_set = set(left_tokens or [])
    right_set = set(right_tokens or [])
    if not left_set or not right_set:
        return set()
    hits = set()
    for left in left_set:
        for right in right_set:
            if left == right:
                hits.add(left)
                continue
            short, long = (left, right) if len(left) <= len(right) else (right, left)
            if len(short) >= 8 and long.startswith(short):
                hits.add(short)
    return hits


_VARIANT_TOKEN_NOISE = {
    "am", "atx", "cl", "ddr", "dpi", "gb", "gbe", "ghz", "hz", "lga", "lpddr",
    "mb", "mbps", "mhz", "mm", "nvme", "pc", "pcie", "rpm", "sata", "tb", "usb", "w",
}


def variant_model_tokens(text):
    raw = str(text or "").lower()
    chunks = re.findall(r"[a-zа-яё0-9]+", raw, flags=re.IGNORECASE)
    chunks += [normalize_compact_name(token) for token in re.findall(r"[a-z0-9]+(?:[-_/][a-z0-9]+)+", raw)]
    out = set()
    for token in chunks:
        token = normalize_compact_name(token)
        if len(token) < 3 or not any(ch.isdigit() for ch in token) or not any(ch.isalpha() for ch in token):
            continue
        letters = "".join(ch for ch in token if ch.isalpha())
        if not letters or letters in _VARIANT_TOKEN_NOISE or any(
            letters.startswith(prefix) for prefix in ("ddr", "pcie", "sata", "usb")
        ):
            continue
        if re.fullmatch(r"\d+(?:gb|tb|mb|w|hz|ghz|mhz|mm|rpm|mbps)", token):
            continue
        out.add(token)
    return out


def conflicting_variant_tokens(left_text, right_text):
    def grouped(text):
        groups = {}
        for token in variant_model_tokens(text):
            signature = re.sub(r"\d+", "#", token)
            if signature.count("#") > 2 or len(signature.replace("#", "")) < 1:
                continue
            groups.setdefault(signature, set()).add(token)
        return groups

    left = grouped(left_text)
    right = grouped(right_text)
    conflicts = set()
    for signature in set(left) & set(right):
        if left[signature] & right[signature]:
            continue
        conflicts.add(signature)
    return conflicts


def capacity_tokens(text):
    raw = str(text or "").strip().lower().replace(",", ".")
    hits = set()
    kit_pattern = r"\b(\d{1,2})\s*[xх]\s*(\d+(?:\.\d+)?)\s*gb\b"
    for count, size in re.findall(kit_pattern, raw):
        total = float(count) * float(size)
        total_text = str(int(total)) if total.is_integer() else str(total).rstrip("0").rstrip(".")
        hits.add(f"{total_text}gb")
    raw_without_kits = re.sub(kit_pattern, " ", raw)
    for num, unit in re.findall(r"(\d+(?:[\.,]\d+)?)\s*(tb|gb)", raw_without_kits):
        norm_num = str(num)
        if "." in norm_num:
            norm_num = norm_num.rstrip("0").rstrip(".")
        hits.add(f"{norm_num}{unit}")
    return hits


def important_name_tokens(text):
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    tokens = []
    seen = set()
    for token in re.findall(r"[a-zа-я0-9]+", raw):
        if len(token) < 3 or token in IMPORTANT_GENERIC_TOKENS or token.isdigit() or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def ordered_token_hits(left_tokens, right_tokens):
    right_set = set(right_tokens or [])
    return [token for token in (left_tokens or []) if token in right_set]


def color_tokens(text):
    raw = re.sub(r"[^a-zа-яёa-z0-9]+", " ", str(text or "").lower())
    hits = set()
    for word, canon in COLOR_CANON.items():
        if f" {word} " in f" {raw} ":
            hits.add(canon)
    return hits


def variant_modifier_tokens(text):
    raw = re.sub(r"[^a-zа-яё0-9]+", " ", str(text or "").lower())
    modifiers = {"plus", "nano", "mini", "max", "pro", "ultra", "digital", "ex", "rgb", "argb"}
    return {word for word in modifiers if f" {word} " in f" {raw} "}


def connection_variant_tokens(text):
    raw = str(text or "").lower()
    out = set()
    if re.search(r"\bps\s*[/.-]?\s*2\b", raw, flags=re.IGNORECASE):
        out.add("ps2")
    if re.search(r"\busb(?:\s*[- ]?\s*[abc])?\b", raw, flags=re.IGNORECASE):
        out.add("usb")
    if re.search(r"\bbluetooth\b|\bbt\s*\d", raw, flags=re.IGNORECASE):
        out.add("bluetooth")
    if re.search(r"\b2[.,]4\s*(?:ghz|ггц)\b", raw, flags=re.IGNORECASE):
        out.add("wireless24")
    return out


def mount_model_key(text, brand_compact=""):
    raw = str(text or "").split("http", 1)[0].split("(", 1)[0].strip()
    if not re.search(r"\bкронштейн\w*\b|\bmount\b", raw, flags=re.IGNORECASE):
        return ""
    words = re.findall(r"[a-zа-яё0-9]+", raw.lower(), flags=re.IGNORECASE)
    start = -1
    for idx, word in enumerate(words):
        if normalize_compact_name(word) == brand_compact:
            start = idx + 1
            break
    if start < 0:
        return ""
    skip = {
        "black", "white", "grey", "gray", "silver", "черный", "чёрный", "белый",
        "серый", "серебристый", "для", "монитора", "мониторов", "жк",
    }
    model_words = [word for word in words[start:] if word not in skip]
    return normalize_compact_name(" ".join(model_words))


def extract_product_category(name):
    raw = str(name or "").strip().lower()
    words = re.split(r"[\s,.(]+", raw)
    for size in (3, 2, 1):
        prefix = " ".join(words[:size])
        if prefix in CATEGORY_LOOKUP:
            return CATEGORY_LOOKUP[prefix]
    return None


def product_categories_compatible(left_category, right_category):
    if not left_category or not right_category or left_category == right_category:
        return True
    cable_markers = {
        "кабель", "cable", "шнур", "провод", "адаптер", "adapter",
        "переходник", "конвертер", "разветвитель", "хаб", "hub", "splitter",
        "usb-хаб", "usb хаб", "usb-hub",
    }
    return bool(set(left_category) & cable_markers and set(right_category) & cable_markers)


def is_spec_code(norm_upper):
    norm_upper = str(norm_upper or "").upper()
    if re.match(r"^\d+(?:GBE|G)$", norm_upper):
        return True
    return any(norm_upper.startswith(prefix) for prefix in SPEC_CODE_PREFIXES)


def motherboard_model_search_tokens(text):
    raw = str(text or "").strip()
    if not re.match(r"^\s*(?:MB|материнск|motherboard)\b", raw, flags=re.IGNORECASE):
        return []
    cleaned = re.sub(r"^\s*MB\s+", "", raw, flags=re.IGNORECASE).strip()
    brands = r"asrock|gigabyte|asus|msi|biostar|colorful|maxsun"
    match = re.match(
        rf"^\s*(?P<brand>{brands})\s+(?P<model>.+?)\s+(?:soc|socket)[-\s]?[a-z0-9-]+\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    brand = match.group("brand").strip()
    model = re.sub(r"\([^)]+\)", " ", match.group("model") or "")
    model = re.sub(r"\s+", " ", model).strip(" -_/")
    if not model:
        return []

    out = []
    seen = set()

    def add(value):
        token = re.sub(r"\s+", " ", str(value or "")).strip()
        key = token.lower()
        if token and len(normalize_compact_name(token)) >= 4 and key not in seen:
            seen.add(key)
            out.append(token)

    add(f"{brand} {model}")
    add(model)
    words = model.split()
    if len(words) > 2:
        add(f"{brand} {' '.join(words[:2])}")
        add(" ".join(words[:2]))
    return out[:4]


def raw_paren_article_tokens(text):
    raw_text = str(text or "")
    found = []
    seen = set()
    for match in re.finditer(r"\(\s*([A-Za-z][A-Za-z0-9.\-/]{5,})\s*\)", raw_text):
        token = match.group(1).strip()
        if not (any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)):
            continue
        norm = normalize_compact_name(token)
        if is_spec_code(norm.upper()) or norm in seen:
            continue
        seen.add(norm)
        found.append(token)
    return found


def strict_identity_article_tokens(text):
    return {normalize_compact_name(token) for token in raw_strict_identity_article_tokens(text)}


def raw_strict_identity_article_tokens(text):
    raw = str(text or "")
    out = []
    seen = set()

    for pattern in [
        r"\b[A-Z0-9]{2,4}\.[A-Z0-9]{4,8}\.[A-Z0-9]{3}\b",
        r"\b\d{1,2}[A-Z]{1,3}-\d{3}XRU\b",
        r"\b9S6-[A-Z0-9]{4,8}-[A-Z0-9]{3,4}\b",
    ]:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            token = str(match.group(0) or "").strip()
            norm = normalize_compact_name(token)
            if (
                norm
                and norm not in seen
                and len(norm) >= 7
                and any(ch.isdigit() for ch in norm)
                and any(ch.isalpha() for ch in norm)
            ):
                seen.add(norm)
                out.append(token)
    return out


def raw_search_tokens(text):
    raw_text = str(text or "")
    out = []
    seen_norm = set()

    def add_search_token(token):
        token = str(token or "").strip()
        norm = normalize_compact_name(token)
        if token and norm and norm not in seen_norm:
            seen_norm.add(norm)
            out.append(token)

    for token in motherboard_model_search_tokens(raw_text):
        add_search_token(token)
    for token in apple_article_base_tokens(raw_text):
        add_search_token(token)
    for token in raw_strict_identity_article_tokens(raw_text):
        add_search_token(token)
    for token in raw_paren_article_tokens(raw_text):
        add_search_token(token)
    for token in fan_series_search_tokens(raw_text):
        add_search_token(token)
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{3,}", raw_text):
        if not (any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)):
            continue
        upper = token.upper()
        norm = normalize_compact_name(token)
        if is_spec_code(norm.upper()) or re.match(r"^\d+[xX][A-Z]", upper):
            continue
        match = re.match(r"^\d+([A-Z]{1,4})$", upper)
        if match and match.group(1) in {"MM", "CM", "W", "V", "A", "MHZ", "GHZ", "DPI", "HZ", "RPM"}:
            continue
        add_search_token(token)
    for match in re.finditer(
        r"\b(RX|GTX|RTX|R[0-9]|HD|VEGA|ARC)\s+(\d{3,4})\s*(XT|Ti|TI|XTX|SUPER|M|S)?\b",
        raw_text,
        re.IGNORECASE,
    ):
        combined = match.group(1) + match.group(2) + (match.group(3) or "")
        if combined not in out:
            out.append(combined)
    return out[:5]


def fan_series_search_tokens(text):
    raw = str(text or "")
    out = []
    for pattern in _FAN_SERIES_PATTERNS:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            series = re.sub(r"\s+", " ", str(match.group("series") or "")).strip()
            size = str(match.group("size") or "").strip()
            variant = str(match.groupdict().get("variant") or "").strip()
            if not series or not size:
                continue
            out.append(f"{series} {size}".strip())
            if variant:
                out.append(f"{series} {size} {variant}".strip())
    return out


def fan_series_match_tokens(text):
    raw = str(text or "")
    out = set()
    for pattern in _FAN_SERIES_PATTERNS:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            series = normalize_compact_name(match.group("series") or "")
            size = str(match.group("size") or "").strip()
            variant = normalize_compact_name(match.groupdict().get("variant") or "")
            if not series or not size:
                continue
            base = f"{series}{size}"
            out.add(base)
            if variant:
                out.add(f"{base}{variant}")
    return out


def apple_article_base_tokens(text):
    raw = str(text or "")
    if not re.search(r"\b(?:apple|macbook|iphone|ipad|imac|mac\s+mini|airpods)\b", raw, flags=re.IGNORECASE):
        return set()
    out = set()

    def add(token):
        norm = normalize_compact_name(token)
        if re.fullmatch(r"a\d{4}", norm):
            return
        if (
            len(norm) == 5
            and any(ch.isdigit() for ch in norm)
            and any(ch.isalpha() for ch in norm)
        ):
            out.add(norm)

    for match in re.finditer(r"\b([A-Za-z0-9]{5})([A-Za-z]{2})/[A-Za-z]\b", raw):
        add(match.group(1))
    for match in re.finditer(r"\b([A-Za-z0-9]{5})(?=[\s)\],;:/-]|$)", raw):
        add(match.group(1))
    return out


_FAN_SERIES_PATTERNS = [
    r"\b(?P<series>crystal)\s*(?P<size>120|140)(?:\s+(?P<variant>white|black|snow|бел\w*|черн\w*))?",
    r"\b(?P<series>ice\s*fan|icefan)\s*(?P<size>120|240|360)(?:\s+argb)?(?:\s+(?P<variant>snow|white|black|бел\w*|черн\w*))?",
    r"\b(?P<series>boreas)\s*(?P<size>120|140)(?:\s+(?P<variant>white|black|бел\w*|черн\w*))?",
]


def numeric_model_tokens(text):
    raw = str(text or "")
    out = set()

    def add(token):
        value = str(token or "").strip()
        if not re.match(r"^\d{3,6}$", value):
            return
        if value in {"1200", "1600", "1800", "2400", "2800", "3200", "3600"}:
            return
        out.add(value)

    for match in re.finditer(r"\(\s*(\d{3,6})\s*\)", raw):
        add(match.group(1))
    for match in re.finditer(
        r"\b(?:сумк\w*|чехл\w*|рюкзак\w*|bag|case)\b.{0,120}?\b(\d{3,6})\b",
        raw,
        flags=re.IGNORECASE,
    ):
        add(match.group(1))
    return out


def numeric_article_codes(text):
    return {
        re.sub(r"\D+", "", match.group(0))
        for match in re.finditer(r"\b\d{3}[- ]\d{6}\b", str(text or ""))
    }


def fan_pack_count(text):
    raw = str(text or "").lower()
    if not re.search(r"вентилятор|fan|vento", raw, flags=re.IGNORECASE):
        return 0
    if re.search(r"\btrio\b|трио", raw, flags=re.IGNORECASE):
        return 3
    match = re.search(r"набор\s*(\d{1,2})\s*(?:в|in)\s*1", raw, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{2,3})\s*[xх]\s*(\d{1,2})\b", raw, flags=re.IGNORECASE)
    if match:
        return int(match.group(2))
    match = re.search(r"\b(?:x|х)(\d{1,2})\b", raw, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    if re.search(r"\bкомплект(?:\s+вентиляторов)?\b", raw, flags=re.IGNORECASE):
        return 2
    return 0


def article_like_tokens(text, tgpc_pc_code_queries=None, extract_article_candidates=None):
    raw = str(text or "")
    out = set()
    apple_context = bool(re.search(r"\b(?:apple|macbook|iphone|ipad|imac|mac\s+mini|airpods)\b", raw, flags=re.IGNORECASE))

    def add(norm):
        upper = norm.upper()
        if str(norm or "").lower() in ARTICLE_LIKE_BRAND_TOKENS:
            return
        if apple_context and re.fullmatch(r"a\d{4}", str(norm or "").lower()):
            return
        if re.match(r"^\d+[xX][A-Z]", upper):
            return
        match = re.match(r"^\d+([A-Z]{1,4})$", upper)
        if match and match.group(1) in MEASURE_UNITS:
            return
        if (
            len(norm) >= 5
            and any(ch.isdigit() for ch in norm)
            and any(ch.isalpha() for ch in norm)
            and not is_spec_code(upper)
        ):
            out.add(norm)

    for token in raw_paren_article_tokens(raw):
        add(normalize_compact_name(token))
    out.update(apple_article_base_tokens(raw))
    if tgpc_pc_code_queries:
        for token in tgpc_pc_code_queries(raw):
            add(normalize_compact_name(token))
    if extract_article_candidates:
        for token in extract_article_candidates(raw):
            add(normalize_compact_name(token))
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-/]{3,}", raw):
        add(normalize_compact_name(token))
        parts = re.split(r"[-/]", token)
        if len(parts) > 1:
            for part in parts:
                add(normalize_compact_name(part))
    for match in re.finditer(
        r"\b(RX|GTX|RTX|R[0-9]|HD|VEGA|ARC)\s+(\d{3,4})\s*(XT|Ti|TI|XTX|SUPER|M|S)?\b",
        raw,
        re.IGNORECASE,
    ):
        combined = match.group(1) + match.group(2) + (match.group(3) or "")
        add(normalize_compact_name(combined))
    for match in re.finditer(r"\b([A-Za-z]{1,4}[-]?\d{3,5}[A-Za-z]{0,3})\b", raw):
        add(normalize_compact_name(match.group(1)))
    return out


def extract_tgpc_pc_code(text):
    raw = str(text or "").strip()
    for pattern in [
        r"\b(\d{4,6})\s+[A-ZА-Яa-zа-я]-[Xx]\b",
        r"\((\d{4,6})\s+[A-ZА-Яa-zа-я]-[Xx]\)",
        r"\b(\d{4,6})[A-ZА-Яa-zа-я]-[Xx]\b",
    ]:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def extract_gpu_model(text):
    raw = normalize_match_text(str(text or ""))
    match = re.search(r"\b(rtx|gtx)\s*(\d{3,4})\s*(ti|super)?\b", raw, flags=re.IGNORECASE)
    if match:
        parts = [match.group(1).upper(), match.group(2)]
        if match.group(3):
            parts.append(match.group(3).upper())
        return "".join(parts)
    match = re.search(r"\b(rx)\s*(\d{3,4})\s*(xt|gre|xtx)?\b", raw, flags=re.IGNORECASE)
    if match:
        parts = ["RX", match.group(2)]
        if match.group(3):
            parts.append(match.group(3).upper())
        return "".join(parts)
    match = re.search(r"\barc\s+(a\d{3})\b", raw, flags=re.IGNORECASE)
    if match:
        return "ARC" + match.group(1).upper()
    return ""


def motherboard_match_key(text):
    raw = str(text or "").strip()
    if not raw:
        return {}
    if not (
        re.match(r"^\s*MB\b", raw, flags=re.IGNORECASE)
        or re.search(r"\bматеринск\w*\s+плат\w*\b|\bmotherboard\b|\bmainboard\b", raw, flags=re.IGNORECASE)
    ):
        return {}

    cleaned = re.sub(r"^\s*MB\s+", "", raw, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^\s*(?:материнск\w*\s+плат\w*|motherboard|mainboard)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    brands = r"asrock|gigabyte|asus|msi|biostar|colorful|maxsun"
    brand = ""
    brand_match = re.search(rf"\b({brands})\b", cleaned, flags=re.IGNORECASE)
    if brand_match:
        brand = brand_match.group(1).lower()
        cleaned = re.sub(rf"^\s*{re.escape(brand_match.group(1))}\s+", "", cleaned, flags=re.IGNORECASE).strip()

    model_head = re.split(r"\b(?:socket|soc)[-\s]?[a-z0-9-]+\b|\s*\(rev\.|\s*,", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    model_head = re.sub(r"\([^)]+\)", " ", model_head)
    model_head = re.sub(r"\s+", " ", model_head).strip(" -_/")
    model = normalize_compact_name(model_head)
    if not model:
        return {}

    chipset_match = re.search(r"\b([a-z]\d{3,4}[a-z]?)\b", model_head, flags=re.IGNORECASE)
    chipset = normalize_compact_name(chipset_match.group(1)) if chipset_match else ""
    features = set()
    for feature, pattern in [
        ("wifi", r"wi[\s-]?fi(?:\s*\d+[a-z]*)?"),
        ("gamingx", r"gaming\s*x"),
        ("aorus", r"\baorus\b"),
        ("elite", r"\belite\b"),
        ("ds3h", r"\bds3h\b"),
        ("d3hp", r"\bd3hp\b"),
        ("d2h", r"\bd2h\b"),
        ("eagle", r"\beagle\b"),
        ("ice", r"\bice\b"),
    ]:
        if re.search(pattern, model_head, flags=re.IGNORECASE):
            features.add(feature)
    return {"brand": brand, "model": model, "chipset": chipset, "features": features}


def motherboard_model_match(local, onliner):
    left = motherboard_match_key(local)
    right = motherboard_match_key(onliner)
    if not left or not right:
        return None
    if left.get("brand") and right.get("brand") and left.get("brand") != right.get("brand"):
        return {"score": 0.04, "match": False, "reason": "motherboard_brand_mismatch"}

    local_model = left.get("model", "")
    remote_model = right.get("model", "")
    if local_model and remote_model:
        if local_model == remote_model:
            return {"score": 0.996, "match": True, "reason": "motherboard_model"}
        short, long = (local_model, remote_model) if len(local_model) <= len(remote_model) else (remote_model, local_model)
        if len(short) >= 8 and long.startswith(short):
            left_features = set(left.get("features") or set())
            right_features = set(right.get("features") or set())
            if left_features - right_features:
                return {"score": 0.35, "match": False, "reason": "motherboard_model_mismatch"}
            return {"score": 0.92, "match": True, "reason": "motherboard_model_close"}

    if left.get("chipset") and left.get("chipset") == right.get("chipset"):
        return {"score": 0.35, "match": False, "reason": "motherboard_model_mismatch"}
    return {"score": 0.18, "match": False, "reason": "motherboard_model_mismatch"}


def calc_name_match(
    local_name,
    onliner_name,
    extract_article=None,
    preferred_brand_token=None,
    tgpc_pc_code_queries=None,
    extract_article_candidates=None,
):
    local = str(local_name or "").strip()
    onliner = str(onliner_name or "").strip()
    if not local or not onliner:
        return {"score": 0.0, "match": False, "reason": "no_name"}

    local_identity_articles = strict_identity_article_tokens(local)
    onliner_identity_articles = strict_identity_article_tokens(onliner)
    if local_identity_articles and onliner_identity_articles:
        if local_identity_articles & onliner_identity_articles:
            return {"score": 1.0, "match": True, "reason": "strict_article"}
        return {"score": 0.16, "match": False, "reason": "strict_article_conflict"}

    if conflicting_variant_tokens(local, onliner):
        return {"score": 0.14, "match": False, "reason": "model_variant_conflict"}

    local_numeric_articles = numeric_article_codes(local)
    onliner_numeric_articles = numeric_article_codes(onliner)
    if local_numeric_articles and onliner_numeric_articles and not (local_numeric_articles & onliner_numeric_articles):
        return {"score": 0.12, "match": False, "reason": "numeric_article_conflict"}

    local_modifiers = variant_modifier_tokens(local)
    onliner_modifiers = variant_modifier_tokens(onliner)
    local_connections = connection_variant_tokens(local)
    onliner_connections = connection_variant_tokens(onliner)

    local_category = extract_product_category(local)
    onliner_category = extract_product_category(onliner)
    local_tgpc_code = extract_tgpc_pc_code(local)
    onliner_tgpc_code = extract_tgpc_pc_code(onliner)
    if local_tgpc_code:
        if onliner_tgpc_code:
            if local_tgpc_code != onliner_tgpc_code:
                return {"score": 0.04, "match": False, "reason": "tgpc_code_mismatch"}
            local_gpu = extract_gpu_model(local)
            onliner_gpu = extract_gpu_model(onliner)
            if local_gpu and onliner_gpu and local_gpu != onliner_gpu:
                return {"score": 0.35, "match": False, "reason": "tgpc_gpu_mismatch"}
            return {"score": 1.0, "match": True, "reason": "tgpc_code_exact"}

    board_match = motherboard_model_match(local, onliner)
    if board_match is not None:
        return board_match

    local_fan_pack = fan_pack_count(local)
    onliner_fan_pack = fan_pack_count(onliner)
    local_fan_series = fan_series_match_tokens(local)
    onliner_fan_series = fan_series_match_tokens(onliner)
    fan_series_hits = local_fan_series & onliner_fan_series
    if fan_series_hits:
        exact_variant_hit = any(not re.search(r"(?:120|140|240|360)$", token) for token in fan_series_hits)
        score = 0.995 if exact_variant_hit else 0.965
        if local_fan_pack:
            if onliner_fan_pack:
                score = min(0.999, score + 0.006)
            else:
                score = min(score, 0.78)
        return {"score": round(score, 3), "match": True, "reason": "fan_series"}

    extract_article = extract_article or (lambda value: "")
    art_local = str(extract_article(local) or "").upper()
    art_onliner = str(extract_article(onliner) or "").upper()
    if art_local and art_onliner and art_local == art_onliner:
        if local_fan_pack and not onliner_fan_pack:
            return {"score": 0.72, "match": True, "reason": "article_pack_mismatch"}
        score = 1.0
        local_capacity = capacity_tokens(local)
        onliner_capacity = capacity_tokens(onliner)
        local_colors = color_tokens(local)
        onliner_colors = color_tokens(onliner)
        if local_capacity and onliner_capacity and not (local_capacity & onliner_capacity):
            score = min(score, 0.84)
        if local_colors:
            if onliner_colors and not (local_colors & onliner_colors):
                score = min(score, 0.88)
            elif not onliner_colors:
                score = min(score, 0.97)
        if local_connections and onliner_connections and not (local_connections & onliner_connections):
            score = min(score, 0.78)
        return {"score": score, "match": score >= 0.74, "reason": "article"}

    local_numeric_models = numeric_model_tokens(local)
    onliner_numeric_models = numeric_model_tokens(onliner)
    if local_numeric_models and onliner_numeric_models and (local_numeric_models & onliner_numeric_models):
        return {"score": 0.995, "match": True, "reason": "numeric_model"}

    local_apple_articles = apple_article_base_tokens(local)
    onliner_apple_articles = apple_article_base_tokens(onliner)
    if local_apple_articles and onliner_apple_articles:
        if local_apple_articles & onliner_apple_articles:
            return {"score": 1.0, "match": True, "reason": "apple_article"}
        return {"score": 0.18, "match": False, "reason": "apple_article_conflict"}

    local_article_like = article_like_tokens(local, tgpc_pc_code_queries, extract_article_candidates)
    onliner_article_like = article_like_tokens(onliner, tgpc_pc_code_queries, extract_article_candidates)
    if local_article_like and onliner_article_like and (local_article_like & onliner_article_like):
        local_capacity = capacity_tokens(local)
        onliner_capacity = capacity_tokens(onliner)
        local_colors = color_tokens(local)
        onliner_colors = color_tokens(onliner)
        shared_articles = local_article_like & onliner_article_like
        local_specific_articles = {token for token in local_article_like if len(token) >= 6}
        onliner_specific_articles = {token for token in onliner_article_like if len(token) >= 6}
        local_high_specific = {token for token in local_article_like if len(token) >= 10}
        onliner_high_specific = {token for token in onliner_article_like if len(token) >= 10}
        score = 0.995 if any(len(token) >= 6 for token in shared_articles) else 0.97
        if local_specific_articles and onliner_specific_articles and not (local_specific_articles & onliner_specific_articles):
            score = 0.90
        if local_high_specific and onliner_high_specific and not (local_high_specific & onliner_high_specific):
            score = min(score, 0.88)
        if (local_identity_articles or onliner_identity_articles) and not (
            shared_articles & (local_identity_articles | onliner_identity_articles)
        ):
            score = min(score, 0.72)
        capacity_conflict = bool(local_capacity and onliner_capacity and not (local_capacity & onliner_capacity))
        if capacity_conflict:
            score = min(score, 0.83)
        if local_colors:
            if onliner_colors and (local_colors & onliner_colors) and not capacity_conflict:
                color_coverage = len(local_colors & onliner_colors) / max(1, len(local_colors))
                score = max(score, 0.995 if color_coverage >= 1.0 else 0.97)
            elif onliner_colors:
                score = min(score, 0.88)
            elif score > 0.90:
                score = max(0.0, score - 0.02)
        if local_connections and onliner_connections and not (local_connections & onliner_connections):
            score = min(score, 0.78)
        return {"score": score, "match": score >= 0.74, "reason": "article_like"}

    local_paren_models = model_hint_tokens(" ".join(paren_chunks(local)), tgpc_pc_code_queries, extract_article_candidates)
    onliner_paren_models = model_hint_tokens(" ".join(paren_chunks(onliner)), tgpc_pc_code_queries, extract_article_candidates)
    paren_intersection = token_family_match(local_paren_models, onliner_paren_models)
    if paren_intersection:
        if local_fan_pack and not onliner_fan_pack:
            return {"score": 0.72, "match": True, "reason": "paren_pack_mismatch"}
        return {"score": 0.94, "match": True, "reason": "paren_model"}

    local_models = model_hint_tokens(local, tgpc_pc_code_queries, extract_article_candidates)
    onliner_models = model_hint_tokens(onliner, tgpc_pc_code_queries, extract_article_candidates)
    model_intersection = token_family_match(local_models, onliner_models)
    if model_intersection:
        base_score = 0.90 if local_paren_models and model_intersection.intersection(local_paren_models) else 0.84
        local_variants = variant_model_tokens(local)
        onliner_variants = variant_model_tokens(onliner)
        if model_intersection & local_variants & onliner_variants:
            base_score = max(base_score, 0.98)
        local_capacity = capacity_tokens(local)
        onliner_capacity = capacity_tokens(onliner)
        local_colors = color_tokens(local)
        onliner_colors = color_tokens(onliner)
        if local_capacity and onliner_capacity and (local_capacity & onliner_capacity):
            base_score = max(base_score, 0.92)
        if local_colors and onliner_colors:
            if local_colors & onliner_colors:
                base_score = min(0.999, base_score + 0.015)
            else:
                base_score = min(base_score, 0.88)
        elif local_colors and not onliner_colors:
            base_score = min(base_score, 0.95)
        if local_fan_pack:
            if onliner_fan_pack:
                base_score = max(base_score, 0.985 if local_fan_pack == onliner_fan_pack else 0.94)
            else:
                base_score = min(base_score, 0.72)
        return {"score": base_score, "match": True, "reason": "model_token"}
    if local_fan_pack and onliner_fan_pack:
        clean_local_for_pack = normalize_match_text(local)
        clean_onliner_for_pack = normalize_match_text(onliner)
        pack_local_tokens = set(name_tokens(clean_local_for_pack))
        pack_onliner_tokens = set(name_tokens(clean_onliner_for_pack))
        pack_hits = pack_local_tokens & pack_onliner_tokens
        pack_brand_local = normalize_compact_name((preferred_brand_token or (lambda value: ""))(local))
        pack_brand_onliner = normalize_compact_name((preferred_brand_token or (lambda value: ""))(onliner))
        if pack_brand_local and pack_brand_local == pack_brand_onliner and len(pack_hits) >= 3:
            pack_score = 0.96
            pack_local_colors = color_tokens(local)
            pack_onliner_colors = color_tokens(onliner)
            if pack_local_colors and pack_onliner_colors:
                pack_score = 0.985 if (pack_local_colors & pack_onliner_colors) else 0.94
            local_vento_r = bool(re.search(r"\bvento\s+r\b", local, flags=re.IGNORECASE))
            onliner_vento_r = bool(re.search(r"\bvento\s+r\b", onliner, flags=re.IGNORECASE))
            if local_vento_r and onliner_vento_r:
                pack_score = min(0.995, pack_score + 0.006)
            elif local_vento_r and not onliner_vento_r:
                pack_score = min(pack_score, 0.965)
            return {"score": pack_score, "match": True, "reason": "fan_pack_tokens"}
    if local_article_like and onliner_article_like and not token_family_match(local_article_like, onliner_article_like):
        return {"score": 0.18, "match": False, "reason": "article_conflict"}

    # Supplier names and Onliner names often use different category wording.
    # Exact article/model evidence above is stronger than that noisy prefix.
    if not product_categories_compatible(local_category, onliner_category):
        return {"score": 0.02, "match": False, "reason": "category_mismatch"}

    clean_local = normalize_match_text(local)
    clean_onliner = normalize_match_text(onliner)
    local_capacity = capacity_tokens(clean_local)
    onliner_capacity = capacity_tokens(clean_onliner)
    local_colors = color_tokens(clean_local)
    onliner_colors = color_tokens(clean_onliner)
    local_tokens = set(name_tokens(clean_local))
    onliner_tokens = set(name_tokens(clean_onliner))
    important_local = important_name_tokens(local)
    important_onliner = important_name_tokens(onliner)
    important_hits = ordered_token_hits(important_local, important_onliner)
    preferred_brand_token = preferred_brand_token or (lambda value: "")
    brand_local = normalize_compact_name(preferred_brand_token(local))
    brand_onliner = normalize_compact_name(preferred_brand_token(onliner))
    same_brand = bool(brand_local and brand_onliner and brand_local == brand_onliner)
    overlap = 0.0
    if local_tokens and onliner_tokens:
        overlap = len(local_tokens & onliner_tokens) / max(1, min(len(local_tokens), len(onliner_tokens)))
    seq = (
        SequenceMatcher(None, " ".join(sorted(local_tokens))[:300], " ".join(sorted(onliner_tokens))[:300]).ratio()
        if local_tokens and onliner_tokens else 0.0
    )
    raw_seq = SequenceMatcher(None, clean_local[:260], clean_onliner[:260]).ratio()
    score = (0.58 * overlap) + (0.24 * seq) + (0.18 * raw_seq)

    local_compact = normalize_compact_name(clean_local)
    onliner_compact = normalize_compact_name(clean_onliner)
    if local_compact and onliner_compact and (local_compact in onliner_compact or onliner_compact in local_compact):
        score += 0.08
    if same_brand:
        score += 0.05
    if len(important_hits) >= 2:
        score += 0.12
        if same_brand:
            score += 0.08
    if len(important_hits) >= 3:
        score += 0.05
    if local_capacity and onliner_capacity:
        if local_capacity & onliner_capacity:
            score += 0.10
        else:
            score -= 0.14
    if local_colors and onliner_colors and (local_colors & onliner_colors):
        score += 0.03
    elif local_colors and onliner_colors:
        score = min(score, 0.88)
    elif local_colors and not onliner_colors:
        score = min(score, 0.95)
    if local_models and onliner_models and not model_intersection:
        score -= 0.22
    if local_paren_models and onliner_models and not (local_paren_models & onliner_models):
        score -= 0.10
    if local_numeric_models and onliner_numeric_models and not (local_numeric_models & onliner_numeric_models):
        score = min(score, 0.74)
    if local_fan_pack:
        if onliner_fan_pack:
            score += 0.10 if local_fan_pack == onliner_fan_pack else 0.04
        else:
            score -= 0.18
    if local_modifiers - onliner_modifiers:
        score = min(score, 0.90)
    if onliner_modifiers - local_modifiers:
        score = min(score, 0.94)
    shared_modifiers = local_modifiers & onliner_modifiers
    if shared_modifiers:
        score += min(0.18, 0.09 * len(shared_modifiers))

    local_mount_model = mount_model_key(local, brand_local)
    onliner_mount_model = mount_model_key(onliner, brand_onliner)
    if same_brand and local_mount_model and onliner_mount_model:
        if local_mount_model == onliner_mount_model:
            score = max(score, 0.995)
        elif local_mount_model.startswith(onliner_mount_model) or onliner_mount_model.startswith(local_mount_model):
            score = min(score, 0.92)
        else:
            score = min(score, 0.78)

    score = round(min(1.0, max(0.0, score)), 3)
    if local_tgpc_code and not onliner_tgpc_code:
        score = round(min(score, 0.72), 3)

    ok = (
        score >= 0.64
        or overlap >= 0.78
        or raw_seq >= 0.84
        or (same_brand and len(important_hits) >= 2 and score >= 0.72)
    )
    reason = "brand_model_tokens" if same_brand and len(important_hits) >= 2 else "tokens"
    return {"score": float(score), "match": bool(ok), "reason": reason}


def harden_base_verify_result(
    local_name,
    verify_result,
    lookup_catalog_match_details=None,
    calc_match=None,
    article_tokens=None,
):
    result = dict(verify_result or {})
    status = str(result.get("status", "")).strip().lower()
    if status != "match":
        return result

    catalog_name = str(result.get("catalog_name", "")).strip()
    if not catalog_name:
        return result

    calc_match = calc_match or calc_name_match
    article_tokens = article_tokens or article_like_tokens
    comparison = calc_match(local_name, catalog_name)
    comparison_score = float(comparison.get("score", 0.0) or 0.0)
    local_articles = article_tokens(local_name)
    catalog_articles = article_tokens(catalog_name)
    article_intersection = bool(local_articles and catalog_articles and (local_articles & catalog_articles))

    if local_articles and catalog_articles and not article_intersection:
        guessed = lookup_catalog_match_details(local_name) if callable(lookup_catalog_match_details) else None
        return _base_verify_mismatch_result(result, guessed, catalog_name, min(comparison_score, 0.49))

    if article_intersection or comparison_score >= 0.62:
        result["score"] = max(float(result.get("score", 0.0) or 0.0), round(comparison_score, 3))
        return result

    if comparison_score >= 0.48:
        result.update({"status": "unverified", "score": round(comparison_score, 3)})
        return result

    guessed = lookup_catalog_match_details(local_name) if callable(lookup_catalog_match_details) else None
    return _base_verify_mismatch_result(result, guessed, catalog_name, comparison_score)


def _base_verify_mismatch_result(result, guessed, fallback_catalog_name, score):
    result.update({
        "status": "mismatch",
        "score": round(score, 3),
        "catalog_id": str((guessed or {}).get("id", "")).strip() or str(result.get("catalog_id", "")).strip(),
        "catalog_name": str((guessed or {}).get("model", "")).strip() or fallback_catalog_name,
        "url": str((guessed or {}).get("url", "")).strip() or str(result.get("url", "")).strip(),
    })
    return result
