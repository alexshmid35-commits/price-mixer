"""Category-specific N-Tech review queue handlers."""

from dataclasses import dataclass
import re

from price_mixer.services.ntech_review_queue import (
    no_candidates_review_item,
    no_model_review_item,
    queued_review_item,
    skip_review_row,
)


@dataclass(frozen=True)
class NTechReviewHandler:
    is_target: object
    build_row_result: object


def build_ntech_review_handlers_from_runtime(deps):
    handler_deps = {
        "normalize_name_key": deps["normalize_name_key"],
        "cpu_brand_model_key": lambda text: deps["review_cpu_brand_model_key"](text, deps["normalize_compact_name"]),
        "looks_like_cpu_name": deps["review_looks_like_cpu_name"],
        "find_cpu_review_candidates": lambda product_name, top_n=5: deps["review_find_cpu_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            normalize_compact_name=deps["normalize_compact_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "board_brand_model_key": deps["review_board_brand_model_key"],
        "find_board_review_candidates": lambda product_name, top_n=5: deps["review_find_board_candidates"](
            product_name,
            top_n=top_n,
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "monitor_brand_model_key": deps["review_monitor_brand_model_key"],
        "find_monitor_review_candidates": lambda product_name, top_n=5: deps["review_find_monitor_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "gpu_brand_model_key": deps["review_gpu_brand_model_key"],
        "find_gpu_review_candidates": lambda product_name, top_n=5: deps["review_find_gpu_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "ram_brand_model_key": deps["review_ram_brand_model_key"],
        "find_ram_review_candidates": lambda product_name, top_n=5: deps["review_find_ram_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "ssd_brand_model_key": lambda text: deps["review_ssd_brand_model_key"](
            text,
            normalize_compact_name=deps["normalize_compact_name"],
            raw_paren_article_tokens=deps["raw_paren_article_tokens"],
            is_spec_code=deps["is_spec_code"],
        ),
        "find_ssd_review_candidates": lambda product_name, top_n=5: deps["review_find_ssd_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            normalize_compact_name=deps["normalize_compact_name"],
            raw_paren_article_tokens=deps["raw_paren_article_tokens"],
            is_spec_code=deps["is_spec_code"],
        ),
        "psu_brand_model_key": deps["review_psu_brand_model_key"],
        "find_psu_review_candidates": lambda product_name, top_n=5: deps["review_find_psu_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "case_brand_model_key": deps["review_case_brand_model_key"],
        "looks_like_case_name": deps["review_looks_like_case_name"],
        "find_case_review_candidates": lambda product_name, top_n=5: deps["review_find_case_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "hdd_brand_model_key": lambda text: deps["review_hdd_brand_model_key"](
            text,
            raw_paren_article_tokens=deps["raw_paren_article_tokens"],
            is_spec_code=deps["is_spec_code"],
        ),
        "looks_like_hdd_name": deps["review_looks_like_hdd_name"],
        "find_hdd_review_candidates": lambda product_name, top_n=5: deps["review_find_hdd_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
            raw_paren_article_tokens=deps["raw_paren_article_tokens"],
            is_spec_code=deps["is_spec_code"],
        ),
        "cooler_brand_model_key": lambda text: deps["review_cooler_brand_model_key"](
            text,
            raw_paren_article_tokens=deps["raw_paren_article_tokens"],
        ),
        "looks_like_cooler_name": deps["review_looks_like_cooler_name"],
        "looks_like_liquid_cpu_cooling_name": deps["review_looks_like_liquid_cpu_cooling_name"],
        "find_cooler_review_candidates": lambda product_name, top_n=5: deps["review_find_cooler_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
            raw_paren_article_tokens=deps["raw_paren_article_tokens"],
        ),
        "printer_mfp_brand_model_key": deps["review_printer_mfp_brand_model_key"],
        "looks_like_printer_or_mfp_name": deps["review_looks_like_printer_or_mfp_name"],
        "find_printer_review_candidates": lambda product_name, top_n=5: deps["review_find_printer_candidates"](
            product_name,
            top_n=top_n,
            db_connection=deps["db_connection"],
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
        "looks_like_peripheral_name": deps["review_looks_like_peripheral_name"],
        "find_peripheral_review_candidates": lambda product_name, top_n=5: deps["review_find_peripheral_candidates"](
            product_name,
            top_n=top_n,
            db_find_top_candidates=deps["db_find_top_candidates"],
            db_find_exact_id_for_name=deps["db_find_exact_id_for_name"],
            infer_category=deps["infer_category"],
            normalize_catalog_category_name=deps["normalize_catalog_category_name"],
        ),
    }
    return build_ntech_review_handlers(handler_deps)


def build_ntech_review_handlers(deps):
    def supplier(row):
        return str(row.get("Поставщик", "") or "").strip()

    def best_source(candidates):
        return str((candidates[0] or {}).get("source", "") or "").strip() if candidates else ""

    def name_key(name):
        return deps["normalize_name_key"](name)

    def looks_like_case_fan_name(text):
        low = str(text or "").strip().lower()
        if not low:
            return False
        if re.search(r"\b(жестк|hdd|ssd)\b", low, flags=re.IGNORECASE):
            return False
        return bool(re.search(
            r"вентилятор|fan|комплект\s+вентиляторов|набор\s+\d+\s*в\s*\d+|"
            r"\b120x3\b|\b140x3\b|\btrio\b",
            low,
            flags=re.IGNORECASE,
        ))

    def cpu_is_target(row, name, category):
        return category == "Процессор" or deps["looks_like_cpu_name"](name)

    def cpu_row_result(row_idx, row, name, category, now_ts):
        local_brand, local_model = deps["cpu_brand_model_key"](name)
        if not local_brand or not local_model:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Процессор",
                "supplier": supplier(row),
                "cpu_brand": local_brand.upper() if local_brand else "",
                "cpu_model": local_model.upper() if local_model else "",
                "cpu_issue": "no_model",
                "cpu_issue_label": "Не удалось выделить модель CPU",
                "candidates": [],
            })
        candidates = deps["find_cpu_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Процессор",
                "supplier": supplier(row),
                "cpu_brand": local_brand.upper(),
                "cpu_model": local_model.upper(),
                "cpu_issue": "no_candidates",
                "cpu_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Процессор",
            "supplier": supplier(row),
            "cpu_brand": local_brand.upper(),
            "cpu_model": local_model.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_model}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "cpu_brand_model_manual",
            "reason_label": "Процессор: совпадение только по производителю и модели. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Процессор",
            "supplier": supplier(row),
            "cpu_brand": local_brand.upper(),
            "cpu_model": local_model.upper(),
            "cpu_issue": "queued",
            "cpu_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def board_is_target(row, name, category):
        return bool(name and re.match(r"^\s*MB\s+", name, flags=re.IGNORECASE))

    def board_row_result(row_idx, row, name, category, now_ts):
        board = deps["board_brand_model_key"](name)
        local_brand = board.get("brand", "")
        local_model = board.get("model", "")
        if not local_brand or not local_model:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Материнская плата",
                "supplier": supplier(row),
                "board_brand": local_brand.upper() if local_brand else "",
                "board_model": local_model.upper() if local_model else "",
                "board_issue": "no_model",
                "board_issue_label": "Не удалось выделить модель платы",
                "candidates": [],
            })
        candidates = deps["find_board_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Материнская плата",
                "supplier": supplier(row),
                "board_brand": local_brand.upper(),
                "board_model": local_model.upper(),
                "board_issue": "no_candidates",
                "board_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Материнская плата",
            "supplier": supplier(row),
            "board_brand": local_brand.upper(),
            "board_model": local_model.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_model}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "board_brand_model_manual",
            "reason_label": "Материнская плата: совпадение по бренду и модели. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Материнская плата",
            "supplier": supplier(row),
            "board_brand": local_brand.upper(),
            "board_model": local_model.upper(),
            "board_issue": "queued",
            "board_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def monitor_is_target(row, name, category):
        looks_like_monitor = bool(re.match(r'^\s*\d{2}(?:\.\d)?\s*"', name))
        return bool(name and (category == "Монитор" or looks_like_monitor))

    def monitor_row_result(row_idx, row, name, category, now_ts):
        monitor = deps["monitor_brand_model_key"](name)
        local_brand = monitor.get("brand", "")
        local_model = monitor.get("model", "")
        model_text = monitor.get("model_text", "")
        if not local_brand or not local_model:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Монитор",
                "supplier": supplier(row),
                "monitor_brand": local_brand.upper() if local_brand else "",
                "monitor_model": model_text,
                "monitor_issue": "no_model",
                "monitor_issue_label": "Не удалось выделить модель монитора",
                "candidates": [],
            })
        candidates = deps["find_monitor_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Монитор",
                "supplier": supplier(row),
                "monitor_brand": local_brand.upper(),
                "monitor_model": model_text,
                "monitor_issue": "no_candidates",
                "monitor_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Монитор",
            "supplier": supplier(row),
            "monitor_brand": local_brand.upper(),
            "monitor_model": model_text,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {model_text}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "monitor_brand_model_manual",
            "reason_label": "Монитор: совпадение по бренду и модели. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Монитор",
            "supplier": supplier(row),
            "monitor_brand": local_brand.upper(),
            "monitor_model": model_text,
            "monitor_issue": "queued",
            "monitor_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def gpu_is_target(row, name, category):
        looks_like_gpu = bool(re.search(
            r"видеокарта|geforce|radeon|(?:^|[^a-z0-9])rtx\s*\d{4}|(?:^|[^a-z0-9])rx\s*\d{3,4}",
            name,
            flags=re.IGNORECASE,
        ))
        return bool(name and (category == "Видеокарта" or looks_like_gpu))

    def gpu_row_result(row_idx, row, name, category, now_ts):
        gpu = deps["gpu_brand_model_key"](name)
        local_vendor = gpu.get("vendor", "")
        local_model = gpu.get("gpu_model", "")
        gpu_sku = str(gpu.get("sku", "") or "").upper()
        if not local_vendor or not local_model:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Видеокарта",
                "supplier": supplier(row),
                "gpu_vendor": local_vendor.upper() if local_vendor else "",
                "gpu_model": local_model.upper() if local_model else "",
                "gpu_sku": gpu_sku,
                "gpu_issue": "no_model",
                "gpu_issue_label": "Не удалось выделить модель видеокарты",
                "candidates": [],
            })
        candidates = deps["find_gpu_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Видеокарта",
                "supplier": supplier(row),
                "gpu_vendor": local_vendor.upper(),
                "gpu_model": local_model.upper(),
                "gpu_sku": gpu_sku,
                "gpu_issue": "no_candidates",
                "gpu_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Видеокарта",
            "supplier": supplier(row),
            "gpu_vendor": local_vendor.upper(),
            "gpu_model": local_model.upper(),
            "gpu_sku": gpu_sku,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_vendor.upper()} {local_model.upper()}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "gpu_brand_model_manual",
            "reason_label": "Видеокарта: совпадение по вендору, GPU и серии. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Видеокарта",
            "supplier": supplier(row),
            "gpu_vendor": local_vendor.upper(),
            "gpu_model": local_model.upper(),
            "gpu_sku": gpu_sku,
            "gpu_issue": "queued",
            "gpu_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def ram_is_target(row, name, category):
        looks_like_ram = bool(
            re.match(r"^\s*ddr[345]\b", name, flags=re.IGNORECASE)
            and not re.search(r"\bпэвм\b|\bкомпьютер\b|\bsoc[-\s]|\bматерин", name, flags=re.IGNORECASE)
        )
        return bool(name and (category == "Оперативная память" or looks_like_ram))

    def ram_row_result(row_idx, row, name, category, now_ts):
        ram = deps["ram_brand_model_key"](name)
        local_brand = ram.get("brand", "")
        local_sku = ram.get("sku", "")
        if not local_brand or (not local_sku and not ram.get("capacity_gb")):
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Оперативная память",
                "supplier": supplier(row),
                "ram_brand": local_brand.upper() if local_brand else "",
                "ram_sku": local_sku.upper() if local_sku else "",
                "ram_issue": "no_model",
                "ram_issue_label": "Не удалось выделить модель памяти",
                "candidates": [],
            })
        candidates = deps["find_ram_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Оперативная память",
                "supplier": supplier(row),
                "ram_brand": local_brand.upper(),
                "ram_sku": local_sku.upper(),
                "ram_issue": "no_candidates",
                "ram_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Оперативная память",
            "supplier": supplier(row),
            "ram_brand": local_brand.upper(),
            "ram_sku": local_sku.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_sku.upper()}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "ram_brand_model_manual",
            "reason_label": "Оперативная память: совпадение по бренду и коду модуля. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Оперативная память",
            "supplier": supplier(row),
            "ram_brand": local_brand.upper(),
            "ram_sku": local_sku.upper(),
            "ram_issue": "queued",
            "ram_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def ssd_is_target(row, name, category):
        looks_like_ssd = bool(
            re.search(r"(?:^|[^a-z0-9])ssd(?=$|[^a-z0-9])|nvme|m\.?2|твердотельн", name, flags=re.IGNORECASE)
            and not re.search(r"\bпэвм\b|\bкомпьютер\b|\bноутбук\b", name, flags=re.IGNORECASE)
        )
        return bool(name and (category == "SSD" or looks_like_ssd))

    def ssd_row_result(row_idx, row, name, category, now_ts):
        ssd = deps["ssd_brand_model_key"](name)
        local_brand = ssd.get("brand", "")
        local_code = str(ssd.get("code", "") or "").strip()
        local_model = str(ssd.get("model", "") or "").strip()
        if not local_code and not local_brand:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "SSD",
                "supplier": supplier(row),
                "ssd_brand": local_brand.upper() if local_brand else "",
                "ssd_model": local_model.upper() if local_model else "",
                "ssd_code": "",
                "ssd_issue": "no_model",
                "ssd_issue_label": "Не удалось выделить бренд/модель SSD",
                "candidates": [],
            })
        candidates = deps["find_ssd_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "SSD",
                "supplier": supplier(row),
                "ssd_brand": local_brand.upper() if local_brand else "",
                "ssd_model": local_model.upper() if local_model else "",
                "ssd_code": local_code.upper(),
                "ssd_issue": "no_candidates",
                "ssd_issue_label": "Кандидаты по коду/модели в БД не найдены",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "SSD",
            "supplier": supplier(row),
            "ssd_brand": local_brand.upper() if local_brand else "",
            "ssd_model": local_model.upper() if local_model else "",
            "ssd_code": local_code.upper(),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_code.upper()}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "ssd_bracket_code_manual",
            "reason_label": "SSD: приоритет точному коду в скобках, fallback по бренду+модели/объёму. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "SSD",
            "supplier": supplier(row),
            "ssd_brand": local_brand.upper() if local_brand else "",
            "ssd_model": local_model.upper() if local_model else "",
            "ssd_code": local_code.upper(),
            "ssd_issue": "queued",
            "ssd_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def psu_is_target(row, name, category):
        looks_like_psu = bool(
            re.search(r"^\s*бп\b|блок\s*питания|80\s*plus|(?:^|[^a-z0-9])psu(?=$|[^a-z0-9])", name, flags=re.IGNORECASE)
            and re.search(r"\b\d{3,4}\s*w\b", name, flags=re.IGNORECASE)
        )
        return bool(name and (category == "Блок питания" or looks_like_psu))

    def psu_row_result(row_idx, row, name, category, now_ts):
        psu = deps["psu_brand_model_key"](name)
        local_brand = psu.get("brand", "")
        local_watt = psu.get("watt", "")
        local_code = str(psu.get("code", "") or "").upper()
        if not local_brand or not local_watt:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Блок питания",
                "supplier": supplier(row),
                "psu_brand": local_brand.upper() if local_brand else "",
                "psu_model": (f"{local_watt}W" if local_watt else ""),
                "psu_code": local_code,
                "psu_issue": "no_model",
                "psu_issue_label": "Не удалось выделить бренд/мощность БП",
                "candidates": [],
            })
        candidates = deps["find_psu_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Блок питания",
                "supplier": supplier(row),
                "psu_brand": local_brand.upper(),
                "psu_model": f"{local_watt}W",
                "psu_code": local_code,
                "psu_issue": "no_candidates",
                "psu_issue_label": "Бренд/мощность найдены, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Блок питания",
            "supplier": supplier(row),
            "psu_brand": local_brand.upper(),
            "psu_model": f"{local_watt}W",
            "psu_code": local_code,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_watt}W",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "psu_brand_power_manual",
            "reason_label": "Блок питания: строгий матч по бренду, мощности, 80 PLUS/модульности/коду. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Блок питания",
            "supplier": supplier(row),
            "psu_brand": local_brand.upper(),
            "psu_model": f"{local_watt}W",
            "psu_code": local_code,
            "psu_issue": "queued",
            "psu_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def case_is_target(row, name, category):
        return bool(name and (category == "Корпус" or deps["looks_like_case_name"](name)))

    def case_row_result(row_idx, row, name, category, now_ts):
        case_meta = deps["case_brand_model_key"](name)
        local_brand = case_meta.get("brand", "")
        local_code = str(case_meta.get("code", "") or "").upper()
        local_series = str(case_meta.get("series", "") or "").upper()
        if not local_brand:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Корпус",
                "supplier": supplier(row),
                "case_brand": local_brand.upper() if local_brand else "",
                "case_model": local_series,
                "case_code": local_code,
                "case_issue": "no_model",
                "case_issue_label": "Не удалось выделить бренд/серию корпуса",
                "candidates": [],
            })
        candidates = deps["find_case_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Корпус",
                "supplier": supplier(row),
                "case_brand": local_brand.upper(),
                "case_model": local_series,
                "case_code": local_code,
                "case_issue": "no_candidates",
                "case_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Корпус",
            "supplier": supplier(row),
            "case_brand": local_brand.upper(),
            "case_model": local_series,
            "case_code": local_code,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_series or local_code}",
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "case_brand_model_manual",
            "reason_label": "Корпус: строгий матч по бренду, серии/коду, форм-фактору и признаку с БП/без БП. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Корпус",
            "supplier": supplier(row),
            "case_brand": local_brand.upper(),
            "case_model": local_series,
            "case_code": local_code,
            "case_issue": "queued",
            "case_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def hdd_is_target(row, name, category):
        return bool(name and (category == "Жесткий диск" or deps["looks_like_hdd_name"](name)))

    def hdd_row_result(row_idx, row, name, category, now_ts):
        hdd_meta = deps["hdd_brand_model_key"](name)
        local_brand = str(hdd_meta.get("brand", "") or "").strip()
        local_code = str(hdd_meta.get("code", "") or "").upper()
        local_capacity = str(hdd_meta.get("capacity", "") or "").strip()
        if not local_brand and not local_code:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Жесткий диск",
                "supplier": supplier(row),
                "hdd_brand": local_brand.upper() if local_brand else "",
                "hdd_code": "",
                "hdd_capacity": local_capacity,
                "hdd_issue": "no_model",
                "hdd_issue_label": "Не удалось выделить бренд/артикул HDD",
                "candidates": [],
            })
        candidates = deps["find_hdd_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Жесткий диск",
                "supplier": supplier(row),
                "hdd_brand": local_brand.upper() if local_brand else "",
                "hdd_code": local_code,
                "hdd_capacity": local_capacity,
                "hdd_issue": "no_candidates",
                "hdd_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Жесткий диск",
            "supplier": supplier(row),
            "hdd_brand": local_brand.upper() if local_brand else "",
            "hdd_code": local_code,
            "hdd_capacity": local_capacity,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_code or local_capacity}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "hdd_article_manual",
            "reason_label": "HDD: совпадение по бренду, артикулу в скобках, объёму и типу (внутр./внеш.). Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Жесткий диск",
            "supplier": supplier(row),
            "hdd_brand": local_brand.upper() if local_brand else "",
            "hdd_code": local_code,
            "hdd_capacity": local_capacity,
            "hdd_issue": "queued",
            "hdd_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def cooler_is_target(row, name, category):
        if not name:
            return False
        air_like = deps["looks_like_cooler_name"](name)
        liq_like = deps["looks_like_liquid_cpu_cooling_name"](name)
        fan_like = looks_like_case_fan_name(name)
        if category == "Охлаждение" and not (air_like or liq_like or fan_like):
            return False
        return category == "Кулер" or air_like or liq_like or fan_like

    def cooler_row_result(row_idx, row, name, category, now_ts):
        cooler_meta = deps["cooler_brand_model_key"](name)
        local_brand = str(cooler_meta.get("brand", "") or "").strip()
        local_code = str(cooler_meta.get("code", "") or "").upper()
        local_tdp = str(cooler_meta.get("tdp", "") or "").strip()
        if not local_brand and not local_code:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Охлаждение",
                "supplier": supplier(row),
                "cooler_brand": local_brand.upper() if local_brand else "",
                "cooler_code": "",
                "cooler_tdp": local_tdp,
                "cooler_issue": "no_model",
                "cooler_issue_label": "Не удалось выделить бренд/код охлаждения",
                "candidates": [],
            })
        candidates = deps["find_cooler_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Охлаждение",
                "supplier": supplier(row),
                "cooler_brand": local_brand.upper() if local_brand else "",
                "cooler_code": local_code,
                "cooler_tdp": local_tdp,
                "cooler_issue": "no_candidates",
                "cooler_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Охлаждение",
            "supplier": supplier(row),
            "cooler_brand": local_brand.upper() if local_brand else "",
            "cooler_code": local_code,
            "cooler_tdp": local_tdp,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_code or local_tdp}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "cooler_article_manual",
            "reason_label": "Охлаждение (кулер / СЖО): бренд, артикул, TDP, цвет. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Охлаждение",
            "supplier": supplier(row),
            "cooler_brand": local_brand.upper() if local_brand else "",
            "cooler_code": local_code,
            "cooler_tdp": local_tdp,
            "cooler_issue": "queued",
            "cooler_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def printer_is_target(row, name, category):
        return bool(name and (category == "Принтер и МФУ" or deps["looks_like_printer_or_mfp_name"](name)))

    def printer_row_result(row_idx, row, name, category, now_ts):
        pm_meta = deps["printer_mfp_brand_model_key"](name)
        local_brand = str(pm_meta.get("brand", "") or "").strip()
        local_article = str(pm_meta.get("article", "") or "").strip()
        local_model = str(pm_meta.get("model_display", "") or "").strip()
        local_mc = str(pm_meta.get("model_compact", "") or "").strip()
        if not local_brand and not local_article and len(local_mc) < 5:
            return no_model_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Принтер и МФУ",
                "supplier": supplier(row),
                "printer_brand": local_brand.upper() if local_brand else "",
                "printer_article": local_article.upper() if local_article else "",
                "printer_model": local_model,
                "printer_issue": "no_model",
                "printer_issue_label": "Не удалось выделить бренд / модель / артикул принтера или МФУ",
                "candidates": [],
            })
        candidates = deps["find_printer_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": "Принтер и МФУ",
                "supplier": supplier(row),
                "printer_brand": local_brand.upper() if local_brand else "",
                "printer_article": local_article.upper() if local_article else "",
                "printer_model": local_model,
                "printer_issue": "no_candidates",
                "printer_issue_label": "Модель найдена, но кандидатов в БД нет",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": "Принтер и МФУ",
            "supplier": supplier(row),
            "printer_brand": local_brand.upper() if local_brand else "",
            "printer_article": local_article.upper() if local_article else "",
            "printer_model": local_model,
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": f"{local_brand.upper()} {local_model or local_article}".strip(),
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "printer_article_manual",
            "reason_label": "Принтер / МФУ: бренд, модель, артикул в скобках. Подтверждение только вручную.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": "Принтер и МФУ",
            "supplier": supplier(row),
            "printer_brand": local_brand.upper() if local_brand else "",
            "printer_article": local_article.upper() if local_article else "",
            "printer_model": local_model,
            "printer_issue": "queued",
            "printer_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    def peripheral_is_target(row, name, category):
        return bool(
            name
            and (
                category in {"Клавиатура", "Мышь", "Наушники", "Акустика"}
                or deps["looks_like_peripheral_name"](name)
            )
        )

    def peripheral_row_result(row_idx, row, name, category, now_ts):
        candidates = deps["find_peripheral_review_candidates"](name, top_n=5)
        key = name_key(name)
        if not key:
            return skip_review_row()
        report_category = category if category in {"Клавиатура", "Мышь", "Наушники", "Акустика"} else "Периферия"
        if not candidates:
            return no_candidates_review_item({
                "name": name,
                "row_idx": int(row_idx),
                "category": report_category,
                "supplier": supplier(row),
                "peripheral_issue": "no_candidates",
                "peripheral_issue_label": "Кандидатов в БД не найдено",
                "candidates": [],
            })
        queue_item = {
            "name": name,
            "category": report_category,
            "supplier": supplier(row),
            "cleared_id": "",
            "cleared_score": 1.0,
            "onliner_name": name,
            "candidates": list(candidates),
            "added_at": now_ts,
            "reason": "peripheral_manual",
            "reason_label": "Периферия N-Tech: кандидаты найдены, требуется ручное подтверждение.",
        }
        report_item = {
            "name": name,
            "row_idx": int(row_idx),
            "category": report_category,
            "supplier": supplier(row),
            "peripheral_issue": "queued",
            "peripheral_issue_label": "Есть кандидаты, отправлено в ручную очередь",
            "best_source": best_source(candidates),
            "candidates": list(candidates),
        }
        return queued_review_item(key, queue_item, report_item)

    return {
        "cpu": NTechReviewHandler(cpu_is_target, cpu_row_result),
        "board": NTechReviewHandler(board_is_target, board_row_result),
        "monitor": NTechReviewHandler(monitor_is_target, monitor_row_result),
        "gpu": NTechReviewHandler(gpu_is_target, gpu_row_result),
        "ram": NTechReviewHandler(ram_is_target, ram_row_result),
        "ssd": NTechReviewHandler(ssd_is_target, ssd_row_result),
        "psu": NTechReviewHandler(psu_is_target, psu_row_result),
        "case": NTechReviewHandler(case_is_target, case_row_result),
        "hdd": NTechReviewHandler(hdd_is_target, hdd_row_result),
        "cooler": NTechReviewHandler(cooler_is_target, cooler_row_result),
        "printer": NTechReviewHandler(printer_is_target, printer_row_result),
        "peripheral": NTechReviewHandler(peripheral_is_target, peripheral_row_result),
    }
