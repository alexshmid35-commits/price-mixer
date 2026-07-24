"""Product ID, name, category, and dataframe normalization helpers."""

import math
import re
from functools import lru_cache

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
    normalized = df["OnlinerID"].map(normalize_onliner_id)
    return int(normalized.eq("").sum())


def count_rows_with_duplicate_onliner_id(df):
    if df is None or getattr(df, "empty", False):
        return 0
    if "OnlinerID" not in df.columns:
        return 0
    normalized = df["OnlinerID"].map(normalize_onliner_id)
    counts = normalized[normalized.ne("")].value_counts()
    return int(counts[counts.gt(1)].sum())


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


def _fallback_category_token(text):
    """Return the legacy broad fallback used when no category rule matches."""
    norm = re.sub(r"[^a-zа-я0-9\+\s\-]", " ", str(text or "").strip().lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    tokens = re.findall(r"[a-zа-я0-9\+\-]+", norm)
    if not tokens:
        return "Без категории"
    return tokens[0].upper()


@lru_cache(maxsize=200_000)
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

    tool_brand_hint = re.search(
        r"\b(?:milwaukee|p\.?\s*i\.?\s*t\.?|teh|dewalt|makita|bosch|sturm|kolner|hanskonner|workpro|metabo)\b",
        norm_without_prefix,
        flags=re.IGNORECASE,
    )
    tool_target_hint = re.search(
        r"\b(?:дрел\w*|шуруповерт\w*|шуруповёрт\w*|перфоратор\w*|пробойник\w*|sds|"
        r"углошлиф\w*|ушм|болгарк\w*|шлифмашин\w*|электроинструмент\w*|бит\w*)\b",
        norm_without_prefix,
        flags=re.IGNORECASE,
    )

    if re.search(r"^\s*бумага\b", norm_without_prefix):
        return "Бумага и материалы для печати"

    if re.search(r"^\s*аксессуары для сервер", norm_without_prefix):
        return "Аксессуары для серверов"

    if re.search(r"\bвидеодомофон\w*\b|\bкоммуникатор\w*\s+dahua\b", norm_without_prefix):
        return "Видеодомофоны"

    if re.search(r"\b(?:анкер\w*|дюбель[\s\-]?гвозд\w*|гвозд\w*[\s\-]?анкер\w*)\b", norm_without_prefix):
        return "Крепеж"

    if re.search(r"\bблендер\w*\b", norm_without_prefix):
        return "Блендеры"

    if re.search(r"\bварочн\w+\s+панел\w*\b", norm_without_prefix):
        return "Варочные панели"

    if re.search(r"\b(?:кухонн\w+|настольн\w+)\s+плит\w*\b", norm_without_prefix):
        return "Кухонные плиты"

    if re.search(r"\bзарядн\w+\s+устройств\w+\s+для\s+инструмент\w*\b", norm_without_prefix):
        return "Зарядные устройства для инструмента"

    if re.search(r"\bчехол\w*\s+для\s+смартфон\w*\b", norm_without_prefix):
        return "Чехлы для смартфонов"

    if re.search(r"\bпарфюмированн\w+\s+гранул\w+\s+для\s+бель", norm_without_prefix):
        return "Средства для стирки"

    if re.search(r"\b(?:умн\w+\s+час\w*|smart\s*watch|apple\s+watch|amazfit|garmin\s+instinct)\b", norm_without_prefix):
        return "Умные часы"

    if re.search(r"\b(?:смарт[\s\-]?браслет\w*|smart\s*band)\b", norm_without_prefix):
        return "Умные часы"

    if re.search(r"\b(?:неттоп\w*|mini[\s\-]?pc|мини[\s\-]?пк|beelink)\b", norm_without_prefix):
        return "Системный блок"

    if re.search(r"\bip[\s\-]?камер\w*|\bвидеокамер\w+\s+ip\b", norm_without_prefix):
        return "IP-камеры"

    if re.search(r"\bcctv[\s\-]?камер\w*|\bкамер\w+\s+cctv\b", norm_without_prefix):
        return "Камеры CCTV"

    if re.search(r"\b(?:ip[\s\-]?)?видеорегистратор\w*\b|\bnvr\b|\bxvr\b", norm_without_prefix):
        return "Видеорегистраторы"

    if re.search(r"\bкамер\w+\s+видеонаблюден", norm_without_prefix):
        return "Камеры CCTV"

    if re.search(r"\bсканер\w*\s+штрих[\s\-]?код\w*\b|\bbarcode\s+scanner\b", norm_without_prefix):
        return "Сканеры штрих-кодов"

    if re.search(r"\bсканер\w*\b|\bscanner\b", norm_without_prefix):
        return "Сканеры"

    if re.search(r"\bсетевая\s+карт\w*|\bсетевой(?:\s+usb)?[\s\-]?адаптер\w*", norm_without_prefix):
        if re.search(r"wi[\s\-]?fi|wifi|bluetooth|802\.11", norm_without_prefix):
            return "Беспроводные адаптеры"
        return "Сетевые адаптеры"

    if re.search(r"\bсетев\w+\s+накопител\w*|\bnas\b", norm_without_prefix):
        return "Сетевые накопители (NAS)"

    if re.search(r"\bwi[\s\-]?fi\s+роутер\w*|\bроутер\w*|\bмаршрутизатор\w*", norm_without_prefix):
        return "Wi-Fi роутеры"

    if re.search(r"\bкоммутатор\w*\b|\bethernet\s+switch\b", norm_without_prefix):
        return "Коммутаторы"

    if re.search(r"\b(?:трансивер\w*|sfp[\s\-]?модул\w*|sfp\s+module|медиаконверт[ео]р\w*|преобразователь\w+.*ethernet|moxa\s+nport)\b", norm_without_prefix):
        return "Сеть"

    if re.search(r"\bмодул\w+\b", norm_without_prefix):
        if re.search(r"\b(?:altusen|aten|kvm|ka7\d|консол\w*)\b", norm_without_prefix):
            return "Кабели и переходники"
        if re.search(r"\b(?:sfp|xcvr|cisco|aruba|stack|moxa|ethernet|lan|gpio|edge[\s\-]?io)\b", norm_without_prefix):
            return "Сеть"

    if re.search(r"\bконтроллер\w*\b", norm_without_prefix):
        if re.search(r"\b(?:raid|perc|megaraid|lsi|broadcom|adaptec|gooxi|dell|hpe)\b", norm_without_prefix):
            return "Аксессуары для серверов"
        return "Сеть"

    if re.search(r"\b(?:poe[\s\-]?инжектор\w*|poe[\s\-]?сплиттер\w*|poe[\s\-]?удлинител\w*|hdmi\s+extender|разветвител\w+\s+hdmi)\b", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\b(?:коннектор\w*\s+rj|rj[\s\-]?45|розетк\w+\s+сетев\w*|патч[\s\-]?панел\w*)\b", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\b(?:ip\s*[\-]?\s*телефон\w*|телефон\w*\s+ip|телефон\w*\s+dect|dect[\s\-]?телефон\w*)\b", norm_without_prefix):
        return "Проводные телефоны"

    if re.search(r"\b(?:радиотелефон\w*|система\s+dect)\b", norm_without_prefix):
        return "Радиотелефоны DECT"

    if re.search(r"\b(?:voip\s*[\-]?\s*шлюз\w*|ip\s*[\-]?\s*атс)\b", norm_without_prefix):
        return "Проводные телефоны"

    if re.search(r"\b(?:шкаф\s+коммутационн\w*|шкаф\s+монтажн\w*|шкаф\s+серверн\w*|серверн\w+\s+шкаф\w*|стойк\w+\s+19)\b", norm_without_prefix):
        return "Шкафы"

    if re.search(r"\b(?:рельс\w*|салазк\w*|монтажн\w+\s+комплект\w*|комплект\w+\s+для\s+монтаж\w+\s+в\s+стойк\w*|корзин\w*|направляющ\w+|полк\w+)\b", norm_without_prefix) and re.search(
        r"\b(?:сервер\w*|supermicro|apc|ups|ibm|hp|hpe|dell|chenbro|ablecom|aic|caswell|moxa|powerman|cyberpower|gooxi|inwin|fsp|lenovo|matrox|qnap|qsan|silverstone|цмо|5bites)\b",
        norm_without_prefix,
    ):
        return "Аксессуары для серверов"

    if re.search(r"\bсерверн\w+\s+платформ\w*|\bплатформ\w+.*(?:gooxi|lga|c621|msi|cubi|pro\s+dp)|\bсервер\b", norm_without_prefix):
        return "Компьютеры"

    if re.search(r"\b(?:аккумулятор\w*|батаре\w+)\s+для\s+(?:ups|ибп)\b|^\s*12v\b.*\b(?:аккумулятор|батаре)", norm_without_prefix):
        return "Аккумуляторы для ИБП"

    if re.search(r"\bаккумулятор\w*\s+для\s+инструмент\w*", norm_without_prefix):
        return "Аккумуляторы для инструмента"

    if re.search(r"\bвнешн\w+\s+аккумулятор\w*|\bpower\s*bank\b|\bpowerbank\b", norm_without_prefix):
        return "Внешние аккумуляторы"

    if re.search(r"\b(?:батарейк\w*|аккумулятор\w*)\b", norm_without_prefix) and re.search(
        r"\b(?:aa|аа|aaa|ааа|aaaa|\d?cr\s?\d+|lr\s?\d+|pr\s?\d+|zinc[\s\-]?air|hr6|hr03|ncr18650|18650|nimh|li[\s\-]?ion|литиев\w*)\b|\d+\s*(?:mah|мач|мaч)\b",
        norm_without_prefix,
    ):
        return "Батарейки, аккумуляторы, зарядные"

    if re.search(r"\b(?:сзу|азу|сетев\w+\s+зарядн\w+\s+устройств\w*|автомобильн\w+\s+зарядн\w+|беспроводн\w+\s+(?:зу|зарядн\w+))\b", norm_without_prefix):
        return "Зарядные устройства"

    if re.search(r"\b(?:блок\w*\s+распределени\w+\s+питани\w*|сетев\w+\s+фильтр\w*|\bpdu\b|удлинител\w+\s+сетев\w*|стабилизатор\w*)", norm_without_prefix):
        return "Стабилизаторы и сетевые фильтры"

    if re.search(r"\b(?:внешн\w+\s+батарейн\w+\s+блок\w*|батарейн\w+\s+блок\w+.*online)\b", norm_without_prefix):
        return "Аккумуляторы для ИБП"

    if re.search(r"\bблок\w*\s+для\s+сбор\w+\s+чернил", norm_without_prefix):
        return "Принтеры"

    if re.search(r"\bфото[\s\-]?бумаг\w*|\bхолст\w*.*\bструйн\w+\s+печати\b", norm_without_prefix):
        return "Фотобумага"

    if re.search(r"\bшредер\w*\b", norm_without_prefix):
        return "Шредеры"

    if re.search(r"\bламинатор\w*\b", norm_without_prefix):
        return "Ламинаторы"

    if re.search(r"\bпылесос\w*\b", norm_without_prefix):
        return "Пылесосы"

    if re.search(r"\bкондиционер\w*\s+для\s+бель", norm_without_prefix):
        return "Средства для стирки"

    if re.search(r"\bкапсул\w+\s+для\s+стирк", norm_without_prefix):
        return "Средства для стирки"

    if re.search(r"\bкапсул\w+\s+для\s+посудомоечн", norm_without_prefix):
        return "Средства для посудомоечных машин"

    if re.search(r"\b(?:влажн\w+\s+)?чистящ\w+\s+салфетк\w*|\bсалфетк\w+\s+для\s+техник", norm_without_prefix):
        return "Чистящие средства"

    if re.search(r"\bпланшет\w*\b|\bipad\b", norm_without_prefix):
        return "Планшеты"

    if re.search(r"\b(?:набор|комплект)\b", norm_without_prefix) and re.search(
        r"\b(?:a4tech|acer|genius|logitech|defender|sven|hp|msi|oklick|smartbuy|crown|клавиатур|keyboard|mouse|мышь|combo|wireless\s+desktop|desktop\s+mk|mk\d{3}|km[\s\-]?\d+|fg\d+|occ\d+)\b",
        norm_without_prefix,
    ):
        return "Комплекты периферии"

    if re.search(r"\bкомплект\w*\s+видеонаблюдени\w*", norm_without_prefix):
        return "Камеры CCTV"

    if re.search(r"\bкресл\w+\b|\bburokrat\b|\bбюрократ\b", norm_without_prefix):
        return "Офисные кресла"

    if re.search(r"\bконструктор\w+\s+lego\b|\blego\b", norm_without_prefix):
        return "Конструкторы"

    if re.search(r"\b(?:гирлянд\w*|дюралайт|светодиодн\w+\s+шнур\w*)\b", norm_without_prefix):
        return "Новогоднее освещение"

    if re.search(r"\bсветодиодн\w+\s+ламп\w*", norm_without_prefix):
        return "Уличное освещение"

    if re.search(r"\bпрожектор\w*\b", norm_without_prefix):
        return "Уличное освещение"

    if re.search(r"\b(?:дождевател\w*|пистолет[\s\-]?распылител\w*|систем\w+\s+туманообразовани\w*)\b", norm_without_prefix):
        return "Системы автоматического полива, распылители"

    if re.search(r"\bполивочн\w+\s+шланг\w*", norm_without_prefix):
        return "Поливочные шланги"

    if re.search(r"\bпроекционн\w+\s+экран\w*|\bэкран\w*\s+для\s+проектор|\bэкран\w*\s+cactus", norm_without_prefix):
        return "Проекционные экраны"

    if re.search(r"\bантенн\w+\b", norm_without_prefix):
        return "Антенны беспроводной связи"

    if re.search(r"\bтермоголовк\w+\s+для\s+принтер", norm_without_prefix):
        return "Принтеры"

    if re.search(r"\b(?:отрезчик\w*|нож\s+отрезчика)\s+для\s+принтер", norm_without_prefix):
        return "Принтеры"

    if re.search(r"\b(?:вызывн\w+\s+панел\w*|панел\w+\s+управлени\w+\s+сигнализац\w*|считывател\w*|терминал\w*\s+контрол\w+\s+доступ\w*)\b", norm_without_prefix):
        return "Видеодомофоны"

    if re.search(r"\b(?:монтажн\w+\s+коробк\w+|пульт\w+.*камер\w+|блок\w+\s+сигнализац\w+|изолятор\w+\s+сигнал\w+|каркас\w+\s+монтажн\w+)\b", norm_without_prefix) and re.search(
        r"\b(?:dahua|hikvision|tiandy|acv|видеонаблюден)\b",
        norm_without_prefix,
    ):
        return "Камеры CCTV"

    if re.search(r"\b(?:шлагбаум\w*|стрел\w+\s+для\s+шлагбаум\w*|турникет\w*)\b", norm_without_prefix):
        return "Системы контроля доступа"

    if re.search(r"\b(?:умн\w+\s+дверн\w+\s+замок\w*|smart\s+tuya)\b", norm_without_prefix):
        return "Умный дом"

    if re.search(r"\bмежсетев\w+\s+экран\w*|\bfirewall\b", norm_without_prefix):
        return "Сеть"

    if re.search(r"\bпереключател\w+\b", norm_without_prefix) and re.search(r"\b(?:aten|kvm|hdmi|usb|ps\s*2)\b", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\bкартридер\w*|\bcard\s*reader\b", norm_without_prefix):
        return "Картридеры"

    if re.search(r"\bрюкзак\w*\b|\bbackpack\b", norm_without_prefix):
        return "Рюкзаки"

    if re.search(r"\bисточник\w*\s+бесперебойн\w+\s+питани\w+|\bups\b", norm_without_prefix):
        return "ИБП"

    if re.search(r"\b(?:беспроводн\w+\s+мост\w*|wireless\s+bridge)\b", norm_without_prefix):
        return "Точки доступа Wi-Fi"

    if re.search(r"\b(?:заточн\w+\s+станок\w*|точильн\w+\s+станок\w*)\b", norm_without_prefix):
        return "Точильные станки"

    if re.search(r"\b(?:отбойн\w+\s+молоток\w*|перфоратор\w*\s+и\s+отбойн)\b", norm_without_prefix):
        return "Перфораторы и отбойные молотки"

    if re.search(r"\bплиткорез\w*\b", norm_without_prefix):
        return "Плиткорезы и отрезные станки"

    if re.search(r"\b(?:леск\w+\s+для\s+триммер\w*|триммерн\w+\s+леск\w*)\b", norm_without_prefix):
        return "Аксессуары для газонной техники, кусторезов и садовых ножниц"

    if re.search(r"\bящик\w+\s+для\s+инструмент", norm_without_prefix):
        return "Ящики для инструментов"

    if re.search(r"\bстяжк\w+\s+(?:нейлонов\w+|кабельн\w*)", norm_without_prefix):
        return "Кабельный крепеж"

    if re.search(r"\b(?:диск\w+\s+dvd|dvd[\s\-]?[rw])\b", norm_without_prefix):
        return "Оптические приводы"

    if re.search(r"\b(?:hdmi|displayport|dp|vga)\b.*\b(?:переходник|адаптер|extender|разветвител)", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\b(?:khadas|myir|firefly)\b", norm_without_prefix):
        return "Компьютеры"

    if re.search(r"\b(?:металлодетектор\w*)\b", norm_without_prefix):
        return "Металлодетекторы"

    if re.search(r"\b(?:аэрофритюрниц\w*|air\s+fryer)\b", norm_without_prefix):
        return "Аэрофритюрницы"

    if re.search(r"\bсушильн\w+\s+машин\w*", norm_without_prefix):
        return "Сушильные машины"

    if re.search(r"\b(?:плат\w*\s+(?:расширени\w+|интерфейсн\w+)|райзер\w+|pci[\s\-]?ex)\b", norm_without_prefix):
        return "Аксессуары для серверов"

    if re.search(r"\bстойк\w+\b", norm_without_prefix) and not re.search(r"\bстойк\w+\s+для\b", norm_without_prefix):
        return "Кронштейны"

    if re.search(r"\bдержател\w+\b", norm_without_prefix):
        if tool_target_hint or tool_brand_hint or re.search(r"\b(?:головок|workpro|maxpiler)\b", norm_without_prefix):
            return "Хозяйственные инструменты"
        return "Кронштейны"

    if re.search(r"\b(?:консоль\w*|переключател\w+)\b", norm_without_prefix) and re.search(r"\b(?:aten|kvm|altusen)\b", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\b(?:преобразователь\w+|moxa)\b", norm_without_prefix):
        return "Сеть"

    if re.search(r"\bтелефон\w*\b", norm_without_prefix) and re.search(r"\b(?:panasonic|ritmix|texel)\b", norm_without_prefix):
        return "Проводные телефоны"

    if re.search(r"\bepson\s+c13", norm_without_prefix):
        return "Картриджи"

    if re.search(r"\bстойк\w+\s+для\s+микрофон\w*", norm_without_prefix):
        return "Акустика"

    if re.search(r"колонк|акустик|speaker", norm_without_prefix):
        return "Акустика"

    if re.search(r"\bнаушник\w*|\bгарнитур\w*|\bheadset\b|\bheadphones\b", norm_without_prefix):
        return "Наушники"

    if re.search(r"\bмикрофон\w*\b", norm_without_prefix):
        return "Микрофоны"

    if re.search(r"\bсаундбар\w*|\bsoundbar\b", norm_without_prefix):
        return "Саундбары"

    if re.search(r"\bинформационн\w+\s+панел\w*", norm_without_prefix):
        return "Информационные панели"

    if re.search(r"\bпроектор\w*\b", norm_without_prefix):
        return "Проекторы"

    if re.search(r"\bстойк\w*\s+для\b", norm_without_prefix) and tool_target_hint:
        return "Строительный, слесарный, монтажный инструмент"

    if re.search(
        r"\b(?:патрон\w*|ключ\s+патрон\w*|насадк\w*|адаптер\w*|переходник\w*|удлинитель\s+кабел\w*)\b",
        norm_without_prefix,
    ) and (tool_target_hint or tool_brand_hint):
        return "Строительный, слесарный, монтажный инструмент"

    if re.search(r"\bдрел\w*[\s\-]?шуруповерт\w*|\bдрел\w*[\s\-]?шуруповёрт\w*|\bгайковерт\w*|\bгайковёрт\w*|\bшуруповерт\w*|\bшуруповёрт\w*|\bэлектроотвертк\w*", norm_without_prefix):
        return "Шуруповерты, гайковерты, электроотвертки"

    if re.search(r"\bперфоратор\w*\b", norm_without_prefix):
        return "Перфораторы"

    if re.search(r"\bдрел\w*\b", norm_without_prefix):
        return "Дрели"

    if re.search(r"\b(?:углошлиф\w*|ушм|болгарк\w*|шлифмашин\w*|шлифовальн\w+\s+машин\w*)\b", norm_without_prefix):
        return "Шлифмашины"

    if re.search(r"\bгравер\w*\b", norm_without_prefix):
        return "Граверы"

    if re.search(r"\b(?:отрезн\w+\s+диск\w*|круг\w+\s+лепестков\w*|шлифовальн\w+\s+диск\w*)\b", norm_without_prefix):
        return "Шлифовальные диски, насадки, листы"

    if re.search(r"\bкоронк\w*\b", norm_without_prefix):
        return "Коронки"

    if re.search(r"\b(?:бит\w+|насадк\w+)\b", norm_without_prefix) and tool_brand_hint:
        return "Биты и насадки"

    if re.search(r"\b(?:диск\w*|круг\w*)\s+шлифовальн\w*|\bкруг\w*\s+лепестков\w*", norm_without_prefix):
        return "Шлифовальные диски, насадки, листы"

    if re.search(r"\bструбцин\w*|\bотвертк\w*|\bотвёртк\w*", norm_without_prefix):
        return "Хозяйственные инструменты"

    if re.search(r"^\s*(?:mb|motherboard|мат\s+плат|материнск)", norm_without_prefix):
        return "Материнская плата"

    if re.search(
        r"^\s*(?:углов\w+\s+)?(?:переходник\w*|адаптер\w*|удлинитель\s+кабел\w*)\b",
        norm_without_prefix,
    ) and (tool_target_hint or tool_brand_hint):
        return "Строительный, слесарный, монтажный инструмент"

    if re.search(r"^\s*(?:кабель|cable|патч[\s\-]?корд|переходник|удлинитель)\b", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"^\s*\d+(?:tb|тб)\b", norm_without_prefix) and not re.search(r"\bssd\b|usb|flash|флеш", norm_without_prefix):
        return "Жесткий диск"

    if re.search(r"\b(?:sata|sas|7200\s*rpm|5400\s*rpm|3\s*5|2\s*5)\b", norm_without_prefix) and re.search(
        r"\b(?:wd|western\s+digital|seagate|toshiba|ultrastar|exos|gold|ironwolf)\b",
        norm_without_prefix,
    ) and not re.search(r"\bssd\b|usb|flash|флеш", norm_without_prefix):
        return "Жесткий диск"

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

    if re.search(r"\b(?:сверл\w*|бур\w*)\b", norm_without_prefix):
        return "Сверла и буры"

    if re.search(r"\bстойк\w*\s+для\b", norm_without_prefix) and tool_target_hint:
        return "Строительный, слесарный, монтажный инструмент"
    if re.search(
        r"\b(?:патрон\w*|ключ\s+патрон\w*|насадк\w*|адаптер\w*|переходник\w*|удлинитель\s+кабел\w*)\b",
        norm_without_prefix,
    ) and (tool_target_hint or tool_brand_hint):
        return "Строительный, слесарный, монтажный инструмент"

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

    if re.search(r"\bugreen\b", norm_without_prefix) and re.search(r"\b(?:us158|30345)\b", norm_without_prefix):
        return "Кабели и переходники"

    usb_hub_model_hint = re.search(
        r"\b(?:uhb[\s\-]|dhub[\s\-]|dub[\s\-]\w+|hub[\s\-]?\d+|cm(?:219|806)\b|wf12\b|ou2270p\b|"
        r"uh\d{3,4}c?\b)\b|(?:[2345678]xusb)|(?:1in\s*-\s*\d+out)",
        norm_without_prefix,
    )
    if re.search(r"usb[\s\-]?хаб|usb[\s\-]?hub|\bhub\b|док[\s\-]?станц", norm_without_prefix):
        return "USB-хабы"

    if re.search(r"разветвител[ья]?\s+usb", norm_without_prefix) and usb_hub_model_hint:
        return "USB-хабы"

    if re.search(r"разветвител[ья]?\s+usb", norm_without_prefix):
        return "Кабели и переходники"

    if re.search(r"\bнабор\b", norm_without_prefix) and re.search(
        r"logitech|defender|sven|клавиатур|keyboard|wireless\s+desktop|desktop\s+mk|mk\d{3}",
        norm_without_prefix,
    ):
        return "Комплекты периферии"

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
        ("USB-хабы", [r"usb[\s\-]?хаб", r"usb[\s\-]?hub", r"\bhub\b", r"док[\s\-]?станц"]),
        ("Накопители USB", [
            r"накопител[ьи]?\s+usb",
            r"usb[\s\-]?(?:flash|drive)",
            r"\b(?:micro\s*sd|microsd|sdhc|sdxc|карта\s+памяти)\b",
            r"\bflash\b",
            r"флеш",
        ]),
        ("Кабели и переходники", [r"разветвител[ья]?\s+usb"]),
        ("Кабели и переходники", [r"кабель", r"переходник", r"адаптер", r"патч[\s\-]?корд"]),
    ]

    for category_name, patterns in category_rules:
        for pattern in patterns:
            if re.search(pattern, norm_without_prefix):
                return category_name

    return _fallback_category_token(norm)


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
        "моноблоки": "Моноблоки",
        "принтер": "Принтеры",
        "принтеры": "Принтеры",
        "принтеримфу": "Принтеры",
        "мфу": "Принтеры",
        "картридж": "Картриджи",
        "картриджи": "Картриджи",
        "сумка": "Сумки и чехлы для ноутбуков",
        "сумки": "Сумки и чехлы для ноутбуков",
        "коврик": "Коврики для мыши",
        "коврики": "Коврики для мыши",
        "внешний": "Внешние накопители",
        "жидкостное": "Охлаждение",
        "смартфон": "Смартфоны",
        "смартфоны": "Смартфоны",
        "видеодомофон": "Видеодомофоны",
        "видеодомофоны": "Видеодомофоны",
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
    preserve_titles = {
        "офисные кресла и стулья",
    }
    if text.lower() in preserve_titles:
        return text

    aliases = {
        "процессоры": "Процессор",
        "процессор": "Процессор",
        "cpu": "Процессор",
        "кулеры": "Кулеры",
        "кулер": "Кулеры",
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
        "принтеры и мфу": "Принтеры",
        "принтеры": "Принтеры",
        "printers": "Принтеры",
        "принтер": "Принтеры",
        "мфу": "Принтеры",
        "ноутбуки": "Ноутбук",
        "ноутбук": "Ноутбук",
        "компьютер": "Компьютеры",
        "компьютеры": "Компьютеры",
        "desktoppc": "Компьютеры",
        "моноблок": "Моноблоки",
        "моноблоки": "Моноблоки",
        "monoblock": "Моноблоки",
        "системные блоки": "Компьютеры",
        "системный блок": "Компьютеры",
        "cartridges": "Картриджи",
        "cable": "Кабели и переходники",
        "сумки и чехлы для ноутбуков": "Сумки и чехлы для ноутбуков",
        "наушники": "Наушники",
        "наушники и гарнитуры": "Наушники",
        "смартфоны": "Смартфоны",
        "телевизоры": "Телевизоры",
        "стабилизаторы, сетевые фильтры, удлинители": "Стабилизаторы и сетевые фильтры",
        "мыши": "Мышь",
        "компьютерные мыши": "Мышь",
        "портативные колонки": "Портативные колонки",
        "клавиатуры": "Клавиатура",
        "usb флеш-накопители": "Накопители USB",
        "умные часы": "Умные часы",
        "умный дом": "Умный дом",
        "угловые шлифмашины (болгарки)": "Углошлифмашины",
        "углошлифмашины": "Углошлифмашины",
        "smart home": "Умный дом",
        "smart_home": "Умный дом",
        "smarthome": "Умный дом",
        "экосистемы умного дома, датчики, центры управления": "Умный дом",
        "планшеты": "Планшеты",
        "ups": "ИБП",
        "источники бесперебойного питания": "ИБП",
        "switch": "Коммутаторы",
        "mousepad": "Коврики для мыши",
        "карты памяти": "Карты памяти",
        "usb-хабы": "USB-хабы",
        "уличное освещение и прожекторы": "Уличное освещение",
        "уличное освещение": "Уличное освещение",
        "wi-fi роутеры": "Wi-Fi роутеры",
        "sound": "Акустика",
        "внешние накопители": "Внешние накопители",
        "саундбары": "Саундбары",
        "комплекты периферии": "Комплекты периферии",
        "wirelessap": "Точки доступа Wi-Fi",
        "беспроводные адаптеры": "Беспроводные адаптеры",
        "боксы для накопителей": "Боксы для накопителей",
        "thermal": "Кулеры",
        "веб-камеры": "Веб-камеры",
        "ip-камеры": "IP-камеры",
        "аккумуляторы для ибп": "Аккумуляторы для ИБП",
        "ups battery": "Аккумуляторы для ИБП",
        "батарейки, аккумуляторы, зарядные": "Батарейки, аккумуляторы, зарядные",
        "графические планшеты": "Графические планшеты",
        "зарядные устройства": "Зарядные устройства",
        "кабельный крепеж": "Кабельный крепеж",
        "наборы периферии": "Комплекты периферии",
        "подставки для ноутбуков, телефонов, планшетов": "Подставки для ноутбуков, телефонов, планшетов",
        "портативные зарядные устройства": "Внешние аккумуляторы",
        "проводные телефоны": "Проводные телефоны",
        "проекционные экраны": "Проекционные экраны",
        "сети по электропроводке (powerline)": "Сети по электропроводке (Powerline)",
        "powerline": "Сети по электропроводке (Powerline)",
        "moddingpc": "Моддинг ПК",
        "картридеры": "Картридеры",
        "headphones accs": "Аксессуары для наушников",
        "игровые приставки": "Игровые приставки",
        "игровые контроллеры и аксессуары": "Игровые контроллеры и аксессуары",
        "computer cleanin": "Чистящие средства",
        "сетевые адаптеры": "Сетевые адаптеры",
        "сетевые адаптеры и сетевые карты": "Сетевые адаптеры",
        "dsl-модемы": "DSL-модемы",
        "звуковые карты": "Звуковые карты",
        "optical": "Оптические приводы",
        "коврики для мыши": "Коврики для мыши",
        "usb2": "Накопители USB",
        "usb2.0": "Накопители USB",
        "usb3": "Накопители USB",
        "usb3.0": "Накопители USB",
        "usb3.1": "Накопители USB",
        "usb3.2": "Накопители USB",
        "additive4fuel": "Присадки для авто",
        "air filters": "Воздушные фильтры",
        "angle grinder": "Углошлифмашины",
        "angle_grinder": "Углошлифмашины",
        "anglegrinder": "Углошлифмашины",
        "antivirus": "Антивирусы",
        "aquariumequip": "Оборудование для аквариумов",
        "art goods": "Товары для творчества",
        "art_goods": "Товары для творчества",
        "artgoods": "Товары для творчества",
        "backpack": "Рюкзаки",
        "barcode": "Сканеры штрих-кодов",
        "bath furniture": "Мебель для ванной",
        "battery": "Батарейки, аккумуляторы, зарядные",
        "benchgrinder": "Точильные станки",
        "bed": "Кровати",
        "bedlinen": "Постельное белье",
        "bits heads": "Биты и насадки",
        "blower": "Воздуходувки",
        "body care": "Уход за телом",
        "body_care": "Уход за телом",
        "bodycare": "Уход за телом",
        "bolts studs": "Крепеж",
        "buildingkit": "Строительные наборы",
        "cabin filters": "Салонные фильтры",
        "carholder": "Автомобильные держатели",
        "carpets home": "Ковры",
        "chainsaw": "Цепные электро- и бензопилы",
        "chair": "Стулья",
        "childcarseat": "Детские автокресла",
        "chiselshamdrills": "Перфораторы и отбойные молотки",
        "collar": "Ошейники",
        "compressor": "Компрессоры",
        "digitalsignage": "Информационные панели",
        "dispenser": "Диспенсеры",
        "disposer": "Измельчители отходов",
        "dresser": "Комоды",
        "drillbits": "Сверла и буры",
        "drills": "Дрели",
        "dvr": "Видеорегистраторы",
        "engraver": "Граверы",
        "electric panel": "Электрические щиты",
        "electric_panel": "Электрические щиты",
        "electricpanel": "Электрические щиты",
        "electric saw": "Цепные электро- и бензопилы",
        "electric_saw": "Цепные электро- и бензопилы",
        "electricsaw": "Цепные электро- и бензопилы",
        "faucet": "Смесители",
        "flowerpot": "Цветочные горшки",
        "fretsaw": "Лобзики",
        "gardenfurniture": "Садовая мебель",
        "gps": "GPS-навигаторы",
        "grinder": "Шлифмашины",
        "hairclipper": "Машинки для стрижки",
        "headphones accs": "Аксессуары для наушников",
        "hedgetrimmers": "Кусторезы",
        "hifiaudio": "Hi-Fi аудио",
        "hoods": "Вытяжки",
        "household tools": "Хозяйственные инструменты",
        "household_tools": "Хозяйственные инструменты",
        "householdtools": "Хозяйственные инструменты",
        "kitchen table": "Кухонные столы",
        "laserlevel": "Лазерные уровни",
        "measuringacs": "Измерительные принадлежности",
        "metal cutter": "Плиткорезы и отрезные станки",
        "microphones": "Микрофоны",
        "multimeter": "Мультиметры",
        "nailer": "Гвоздезабиватели",
        "nas": "Сетевые накопители (NAS)",
        "outdoor light": "Уличное освещение",
        "outdoor_light": "Уличное освещение",
        "outdoorlight": "Уличное освещение",
        "oven cooker": "Кухонные плиты",
        "photopaper": "Фотобумага",
        "powerstations": "Портативные электростанции",
        "powertools sp": "Специнструмент",
        "powertools_sp": "Специнструмент",
        "powertoolssp": "Специнструмент",
        "powertoolset": "Наборы электроинструмента",
        "powertool chucks": "Строительный, слесарный, монтажный инструмент",
        "powertool_chucks": "Строительный, слесарный, монтажный инструмент",
        "powertoolchucks": "Строительный, слесарный, монтажный инструмент",
        "projectors": "Проекторы",
        "pump": "Насосы",
        "remote": "Пульты ДУ",
        "rotaryhammers": "Перфораторы",
        "scanner": "Сканеры",
        "screwdriver": "Шуруповерты, гайковерты, электроотвертки",
        "shower trays": "Душевые поддоны",
        "shredder": "Шредеры",
        "siphon": "Сифоны",
        "table": "Столы",
        "toolbox": "Ящики для инструментов",
        "tools accum": "Аккумуляторы для инструмента",
        "vibrators": "Вибраторы для бетона",
        "videodoorphone": "Видеодомофоны",
        "видеодомофон": "Видеодомофоны",
        "видеодомофоны": "Видеодомофоны",
        "wantenna": "Антенны беспроводной связи",
        "wardrobes": "Шкафы",
        "washbasin": "Умывальники",
        "water bottles": "Бутылки для воды",
        "watch": "Часы",
        "woodrouter": "Фрезеры",
        "woodworking": "Деревообработка",
        "wrench": "Гаечные ключи",
        "xmaslights": "Новогоднее освещение",
    }
    alias = aliases.get(text.lower(), "")
    if alias:
        if alias.lower() in low_to_real:
            return low_to_real.get(alias.lower(), alias)
        return alias

    inferred = infer_category(text)
    if inferred and inferred != "Без категории" and inferred != _fallback_category_token(text):
        if inferred.lower() in low_to_real:
            return low_to_real.get(inferred.lower(), inferred)
        return inferred
    # Catalog titles are user-facing. Preserve the full native title instead of
    # leaking infer_category's uppercased first-token fallback into the UI.
    return text


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
