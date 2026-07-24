"""Report presets for N-Tech and supplier laptop review endpoints."""

from __future__ import annotations


NTECH_CATEGORY_REVIEW_CONFIG = {
    "usb": {
        "label": "Накопители USB",
        "categories": {"Накопители USB", "SDHC", "SDXC", "КАРТРИДЕР"},
    },
    "cables": {
        "label": "Кабели / переходники",
        "categories": set(),
    },
    "network": {
        "label": "Сеть",
        "categories": {"Сеть", "СЕТЕВОЙ", "СЕТЕВАЯ", "СЕТЕВОЕ", "WEB"},
    },
    "ups": {
        "label": "ИБП",
        "categories": {"ИБП", "АККУМУЛЯТОРНАЯ"},
    },
    "keyboard": {
        "label": "Клавиатуры",
        "categories": {"Клавиатура"},
    },
    "mouse": {
        "label": "Мыши",
        "categories": {"Мышь", "КОВРИК"},
    },
    "headphones": {
        "label": "Наушники / микрофоны",
        "categories": {"Наушники", "МИКРОФОН"},
    },
    "audio": {
        "label": "Акустика",
        "categories": {"Акустика"},
    },
    "misc": {
        "label": "Прочее",
        "categories": {
            "MICRO",
            "СУМКА",
            "КАРТРИДЖ",
            "ВНЕШНИЙ",
            "КОМПЛЕКТ",
            "DEFENDER",
            "АВТОМАТИЧЕСКИЙ",
            "ОЧИЩАЮЩИЙ",
            "ПОДСТАВКА",
            "КОРЗИНА",
            "Кабели и переходники",
            "РАЙЗЕР",
            "КОННЕКТОР",
            "ЗАГЛУШКА",
            "РАМКА",
        },
    },
}


_CORE_REVIEW_PRESETS = {
    "cpu": {
        "title": "Отчёт CPU N-Tech",
        "success": "Процессоры N-Tech",
        "processed": "Обработано CPU",
        "empty": "В текущем прайсе N-Tech нет товаров категории «Процессор» без ID. Сейчас CPU встречаются только внутри ПЭВМ/системных блоков.",
        "empty_report": "В текущем прайсе CPU без ID не найдено.",
    },
    "board": {
        "title": "Отчёт материнских плат N-Tech",
        "success": "Материнки N-Tech",
        "processed": "Обработано плат",
        "empty": "В текущем прайсе N-Tech нет материнских плат формата MB без ID.",
        "empty_report": "В текущем прайсе материнские платы без ID не найдены.",
    },
    "monitor": {
        "title": "Отчёт мониторов N-Tech",
        "success": "Мониторы N-Tech",
        "processed": "Обработано мониторов",
        "empty": "В текущем прайсе N-Tech нет мониторов без ID.",
        "empty_report": "В текущем прайсе мониторы без ID не найдены.",
    },
    "gpu": {
        "title": "Отчёт видеокарт N-Tech",
        "success": "Видеокарты N-Tech",
        "processed": "Обработано видеокарт",
        "empty": "В текущем прайсе N-Tech нет видеокарт без ID.",
        "empty_report": "В текущем прайсе видеокарты без ID не найдены.",
    },
    "ram": {
        "title": "Отчёт оперативной памяти N-Tech",
        "success": "Оперативка N-Tech",
        "processed": "Обработано памяти",
        "empty": "В текущем прайсе N-Tech нет оперативной памяти без ID.",
        "empty_report": "В текущем прайсе оперативная память без ID не найдена.",
    },
    "ssd": {
        "title": "Отчёт SSD N-Tech",
        "success": "SSD N-Tech",
        "processed": "Обработано SSD",
        "empty": "В текущем прайсе N-Tech нет SSD без ID.",
        "empty_report": "В текущем прайсе SSD без ID не найдены.",
    },
    "psu": {
        "title": "Отчёт блоков питания N-Tech",
        "success": "Блоки питания N-Tech",
        "processed": "Обработано БП",
        "empty": "В текущем прайсе N-Tech нет блоков питания без ID.",
        "empty_report": "В текущем прайсе блоки питания без ID не найдены.",
    },
    "case": {
        "title": "Отчёт корпусов N-Tech",
        "success": "Корпуса N-Tech",
        "processed": "Обработано корпусов",
        "empty": "В текущем прайсе N-Tech нет корпусов без ID.",
        "empty_report": "В текущем прайсе корпуса без ID не найдены.",
    },
    "hdd": {
        "title": "Отчёт HDD N-Tech",
        "success": "HDD N-Tech",
        "processed": "Обработано HDD",
        "empty": "В текущем прайсе N-Tech нет HDD без ID.",
        "empty_report": "В текущем прайсе HDD без ID не найдены.",
    },
    "cooler": {
        "title": "Отчёт охлаждения N-Tech",
        "success": "Охлаждение N-Tech",
        "processed": "Обработано позиций охлаждения",
        "empty": "В текущем прайсе N-Tech нет позиций охлаждения без ID.",
        "empty_report": "В текущем прайсе охлаждение без ID не найдено.",
    },
    "printer": {
        "title": "Отчёт принтеров и МФУ N-Tech",
        "success": "Принтеры и МФУ N-Tech",
        "processed": "Обработано принтеров и МФУ",
        "empty": "В текущем прайсе N-Tech нет принтеров или МФУ без ID.",
        "empty_report": "В текущем прайсе принтеры / МФУ без ID не найдены.",
    },
    "peripheral": {
        "title": "Отчёт периферии N-Tech",
        "success": "Периферия N-Tech",
        "processed": "Обработано позиций периферии",
        "empty": "В текущем прайсе N-Tech нет периферии без ID.",
        "empty_report": "В текущем прайсе периферия без ID не найдена.",
        "include_no_model": False,
    },
}


def build_core_review_start_kwargs(mode):
    """Build the runtime arguments for a core N-Tech category."""
    preset = dict(_CORE_REVIEW_PRESETS[mode])
    include_no_model = bool(preset.get("include_no_model", True))

    def success_message(scan):
        message = (
            f"{preset['success']}: в ручную очередь добавлено {scan['queued']}."
        )
        if include_no_model and scan["no_model"]:
            message += f" Без модели: {scan['no_model']}."
        if scan["no_candidates"]:
            message += f" Без кандидатов: {scan['no_candidates']}."
        return message

    def report_subtitle(scan):
        message = (
            f"{preset['processed']}: {scan['scanned']}. "
            f"В очереди: {scan['queued']}, "
        )
        if include_no_model:
            message += f"без модели: {scan['no_model']}, "
        return message + f"без кандидатов: {scan['no_candidates']}."

    return {
        "report_mode": mode,
        "report_title": preset["title"],
        "handler_mode": mode,
        "include_no_model": include_no_model,
        "success_message": success_message,
        "empty_message": preset["empty"],
        "report_subtitle": report_subtitle,
        "empty_report_subtitle": preset["empty_report"],
    }


def build_generic_review_start_kwargs(key, config, is_target_row, build_row_result):
    """Build runtime arguments for one generic N-Tech category group."""
    label = str(config.get("label") or "Категория").strip()
    return {
        "report_mode": f"ntech_{key}",
        "report_title": f"Отчёт: {label} N-Tech",
        "is_target_row": is_target_row,
        "build_row_result": build_row_result,
        "include_no_model": False,
        "success_message": lambda scan: (
            f"{label} N-Tech: в ручную очередь добавлено {scan['queued']}."
            + (
                f" Без кандидатов: {scan['no_candidates']}."
                if scan["no_candidates"]
                else ""
            )
        ),
        "empty_message": (
            f"В текущем прайсе N-Tech нет позиций «{label}» без ID."
        ),
        "report_subtitle": lambda scan: (
            f"Обработано позиций: {scan['scanned']}. "
            f"В очереди: {scan['queued']}, "
            f"без кандидатов: {scan['no_candidates']}."
        ),
        "empty_report_subtitle": (
            f"В текущем прайсе позиции «{label}» без ID не найдены."
        ),
    }


def build_laptop_review_start_kwargs(
    supplier,
    report_mode,
    is_target_row,
    build_row_result,
):
    """Build runtime arguments for one supplier laptop review."""
    return {
        "report_mode": report_mode,
        "report_title": f"Отчёт ноутбуков {supplier}",
        "is_target_row": is_target_row,
        "build_row_result": build_row_result,
        "include_no_model": False,
        "supplier_names": [supplier],
        "success_message": lambda scan: (
            f"Ноутбуки {supplier}: в ручную очередь добавлено {scan['queued']}."
            + (
                f" Без кандидатов: {scan['no_candidates']}."
                if scan["no_candidates"]
                else ""
            )
        ),
        "empty_message": (
            f"В текущем прайсе {supplier} нет ноутбуков без ID."
        ),
        "report_subtitle": lambda scan: (
            f"Обработано ноутбуков {supplier}: {scan['scanned']}. "
            f"В очереди: {scan['queued']}, "
            f"без кандидатов: {scan['no_candidates']}."
        ),
        "empty_report_subtitle": (
            f"В текущем прайсе ноутбуки {supplier} без ID не найдены."
        ),
    }
