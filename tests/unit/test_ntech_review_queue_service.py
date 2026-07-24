"""Unit tests for N-Tech review queue helpers."""

import pandas as pd

from price_mixer.services import ntech_review_queue as svc
from price_mixer.services.ntech_review_categories import (
    build_ntech_review_handlers,
    build_ntech_review_handlers_from_runtime,
)


def test_build_review_queue_finish_payload_with_no_model_metric():
    payload, status = svc.build_review_queue_finish_payload(
        report_mode="cpu",
        report_title="Отчёт CPU N-Tech",
        report_items=[{"name": "CPU"}],
        scanned=3,
        queued=1,
        no_model=1,
        no_candidates=1,
        skipped_with_id=2,
        skipped_non_ntech=4,
        success_message="Процессоры N-Tech: в ручную очередь добавлено 1. Без модели: 1. Без кандидатов: 1.",
        empty_message="empty",
        report_subtitle="Обработано CPU: 3. В очереди: 1, без модели: 1, без кандидатов: 1.",
        empty_report_subtitle="empty subtitle",
        now_ts=100,
        finished_at=120,
    )

    assert payload == {
        "status": "ok",
        "scanned": 3,
        "queued": 1,
        "no_candidates": 1,
        "skipped_with_id": 2,
        "skipped_non_ntech": 4,
        "message": "Процессоры N-Tech: в ручную очередь добавлено 1. Без модели: 1. Без кандидатов: 1.",
        "matches": [],
        "no_match": [{"name": "CPU"}],
        "report_mode": "cpu",
        "report_title": "Отчёт CPU N-Tech",
        "report_subtitle": "Обработано CPU: 3. В очереди: 1, без модели: 1, без кандидатов: 1.",
        "no_model": 1,
    }
    assert status == {
        "running": False,
        "total": 3,
        "done": 3,
        "applied": 0,
        "skipped": 2,
        "percent": 100,
        "started_at": 100,
        "finished_at": 120,
        "message": payload["message"],
        "matches": [],
        "no_match": [{"name": "CPU"}],
        "report_mode": "cpu",
        "report_title": "Отчёт CPU N-Tech",
        "report_subtitle": payload["report_subtitle"],
    }


def test_build_review_queue_finish_payload_without_no_model_metric():
    payload, status = svc.build_review_queue_finish_payload(
        report_mode="peripheral",
        report_title="Отчёт периферии N-Tech",
        report_items=[{"name": "Mouse"}],
        scanned=2,
        queued=1,
        no_candidates=1,
        skipped_with_id=0,
        skipped_non_ntech=3,
        success_message="Периферия N-Tech: в ручную очередь добавлено 1. Без кандидатов: 1.",
        empty_message="empty",
        report_subtitle="Обработано позиций периферии: 2. В очереди: 1, без кандидатов: 1.",
        empty_report_subtitle="empty subtitle",
        now_ts=100,
        finished_at=120,
    )

    assert "no_model" not in payload
    assert payload["no_candidates"] == 1
    assert status["skipped"] == 1
    assert status["no_match"] == [{"name": "Mouse"}]


def test_build_review_queue_finish_payload_empty_result():
    payload, status = svc.build_review_queue_finish_payload(
        report_mode="board",
        report_title="Отчёт материнских плат N-Tech",
        report_items=[{"name": "Should be hidden in status"}],
        scanned=0,
        queued=3,
        no_model=2,
        no_candidates=1,
        skipped_with_id=4,
        skipped_non_ntech=5,
        success_message="success",
        empty_message="В текущем прайсе N-Tech нет материнских плат формата MB без ID.",
        report_subtitle="Обработано плат: 0.",
        empty_report_subtitle="В текущем прайсе материнские платы без ID не найдены.",
        now_ts=100,
        finished_at=120,
    )

    assert payload["scanned"] == 0
    assert payload["queued"] == 0
    assert payload["no_model"] == 0
    assert payload["no_candidates"] == 0
    assert payload["skipped_with_id"] == 4
    assert payload["skipped_non_ntech"] == 5
    assert payload["no_match"] == [{"name": "Should be hidden in status"}]
    assert status["total"] == 0
    assert status["skipped"] == 0
    assert status["no_match"] == []
    assert status["report_subtitle"] == "В текущем прайсе материнские платы без ID не найдены."


def test_run_review_queue_scan_tracks_common_ntech_counters():
    df = pd.DataFrame([
        {"Поставщик": "Other", "Название": "Target A", "Категория": "CPU", "OnlinerID": ""},
        {"Поставщик": "N-Tech", "Название": "Skip me", "Категория": "CPU", "OnlinerID": ""},
        {"Поставщик": "NTECH", "Название": "Already has id", "Категория": "CPU", "OnlinerID": "123"},
        {"Поставщик": "N-Tech", "Название": "No model", "Категория": "CPU", "OnlinerID": ""},
        {"Поставщик": "N-Tech", "Название": "No candidates", "Категория": "CPU", "OnlinerID": ""},
        {"Поставщик": "N-Tech", "Название": "Queued", "Категория": "CPU", "OnlinerID": ""},
    ])
    queue = {}

    def build_row_result(row_idx, row, name, category, now_ts):
        if name == "No model":
            return svc.no_model_review_item({"name": name, "row_idx": int(row_idx)})
        if name == "No candidates":
            return svc.no_candidates_review_item({"name": name, "row_idx": int(row_idx)})
        return svc.queued_review_item(
            name_key=name.lower(),
            queue_item={"name": name, "added_at": now_ts},
            report_item={"name": name, "row_idx": int(row_idx)},
        )

    result = svc.run_review_queue_scan(
        df,
        queue,
        now_ts=100,
        is_target_row=lambda row, name, category: name != "Skip me",
        build_row_result=build_row_result,
        row_category=lambda row: row.get("Категория", ""),
        normalize_catalog_category_name=lambda value: value,
        normalize_onliner_id=lambda value: str(value or "").strip(),
    )

    assert result == {
        "scanned": 3,
        "queued": 1,
        "no_model": 1,
        "no_candidates": 1,
        "skipped_with_id": 1,
        "skipped_non_ntech": 1,
        "report_items": [
            {"name": "No model", "row_idx": 3},
            {"name": "No candidates", "row_idx": 4},
            {"name": "Queued", "row_idx": 5},
        ],
    }
    assert queue == {"queued": {"name": "Queued", "added_at": 100}}


def test_run_review_queue_scan_can_be_scoped_to_iven_only():
    df = pd.DataFrame([
        {"Поставщик": "N-Tech", "Название": "Ноутбук N-Tech", "Категория": "Ноутбук", "OnlinerID": ""},
        {"Поставщик": "IVEN", "Название": "Ноутбук IVEN A", "Категория": "Ноутбук", "OnlinerID": ""},
        {"Поставщик": "IVEN", "Название": "Ноутбук IVEN B", "Категория": "Ноутбук", "OnlinerID": "123"},
    ])
    queue = {}

    result = svc.run_review_queue_scan(
        df,
        queue,
        now_ts=100,
        is_target_row=lambda row, name, category: "Ноутбук" in category,
        build_row_result=lambda row_idx, row, name, category, now_ts: svc.queued_review_item(
            name_key=name.lower(),
            queue_item={"name": name, "supplier": row.get("Поставщик"), "added_at": now_ts},
            report_item={"name": name, "supplier": row.get("Поставщик"), "row_idx": int(row_idx)},
        ),
        row_category=lambda row: row.get("Категория", ""),
        normalize_catalog_category_name=lambda value: value,
        normalize_onliner_id=lambda value: str(value or "").strip(),
        ntech_supplier_names=["IVEN"],
    )

    assert result["scanned"] == 1
    assert result["queued"] == 1
    assert result["skipped_non_ntech"] == 1
    assert result["skipped_with_id"] == 1
    assert list(queue) == ["ноутбук iven a"]
    assert queue["ноутбук iven a"]["supplier"] == "IVEN"


def test_build_ntech_review_handlers_cpu_queued_result():
    deps = {
        "normalize_name_key": lambda name: "cpu-key",
        "looks_like_cpu_name": lambda name: True,
        "cpu_brand_model_key": lambda name: ("AMD", "Ryzen 5 5600"),
        "find_cpu_review_candidates": lambda name, top_n=5: [{"source": "db", "id": "123"}],
    }
    handlers = build_ntech_review_handlers(_complete_ntech_deps(deps))

    result = handlers["cpu"].build_row_result(
        row_idx=7,
        row={"Поставщик": "N-Tech"},
        name="AMD Ryzen 5 5600",
        category="Процессор",
        now_ts=100,
    )

    assert result["action"] == "queued"
    assert result["name_key"] == "cpu-key"
    assert result["queue_item"]["reason"] == "cpu_brand_model_manual"
    assert result["queue_item"]["added_at"] == 100
    assert result["report_item"]["best_source"] == "db"


def test_build_ntech_review_handlers_routes_case_fans_to_cooling():
    handlers = build_ntech_review_handlers(_complete_ntech_deps({}))
    cooler = handlers["cooler"].is_target

    assert cooler(
        {},
        "Вентилятор 140mm Montech AX140 PWM (MNT-AX140-B) Black",
        "Охлаждение",
    ) is True
    assert cooler(
        {},
        "Вентилятор 120mm ADATA XPG VENTO R 120 ARGB PWM (НАБОР 3 в 1)",
        "Охлаждение",
    ) is True
    assert cooler({}, "Термопаста обычная", "Охлаждение") is False


def test_build_ntech_review_handlers_from_runtime_wires_cpu_dependencies():
    calls = {}

    def review_cpu_brand_model_key(name, normalize_compact_name):
        calls["brand_model"] = normalize_compact_name(name)
        return "AMD", "Ryzen 5 5600"

    def review_find_cpu_candidates(product_name, **kwargs):
        calls["candidate_kwargs"] = kwargs
        return [{"source": "runtime"}]

    runtime_deps = _complete_ntech_runtime_deps({
        "normalize_compact_name": lambda value: str(value).replace(" ", "").lower(),
        "review_cpu_brand_model_key": review_cpu_brand_model_key,
        "review_find_cpu_candidates": review_find_cpu_candidates,
    })
    handlers = build_ntech_review_handlers_from_runtime(runtime_deps)

    result = handlers["cpu"].build_row_result(
        row_idx=1,
        row={"Поставщик": "N-Tech"},
        name="AMD Ryzen 5 5600",
        category="Процессор",
        now_ts=200,
    )

    assert result["action"] == "queued"
    assert result["report_item"]["best_source"] == "runtime"
    assert calls["brand_model"] == "amdryzen55600"
    assert calls["candidate_kwargs"]["db_connection"] is runtime_deps["db_connection"]
    assert calls["candidate_kwargs"]["normalize_compact_name"] is runtime_deps["normalize_compact_name"]


def _complete_ntech_deps(overrides):
    deps = {
        "normalize_name_key": lambda name: str(name or "").lower(),
        "cpu_brand_model_key": lambda name: ("", ""),
        "looks_like_cpu_name": lambda name: False,
        "find_cpu_review_candidates": lambda name, top_n=5: [],
        "board_brand_model_key": lambda name: {},
        "find_board_review_candidates": lambda name, top_n=5: [],
        "monitor_brand_model_key": lambda name: {},
        "find_monitor_review_candidates": lambda name, top_n=5: [],
        "gpu_brand_model_key": lambda name: {},
        "find_gpu_review_candidates": lambda name, top_n=5: [],
        "ram_brand_model_key": lambda name: {},
        "find_ram_review_candidates": lambda name, top_n=5: [],
        "ssd_brand_model_key": lambda name: {},
        "find_ssd_review_candidates": lambda name, top_n=5: [],
        "psu_brand_model_key": lambda name: {},
        "find_psu_review_candidates": lambda name, top_n=5: [],
        "case_brand_model_key": lambda name: {},
        "looks_like_case_name": lambda name: False,
        "find_case_review_candidates": lambda name, top_n=5: [],
        "hdd_brand_model_key": lambda name: {},
        "looks_like_hdd_name": lambda name: False,
        "find_hdd_review_candidates": lambda name, top_n=5: [],
        "cooler_brand_model_key": lambda name: {},
        "looks_like_cooler_name": lambda name: False,
        "looks_like_liquid_cpu_cooling_name": lambda name: False,
        "find_cooler_review_candidates": lambda name, top_n=5: [],
        "printer_mfp_brand_model_key": lambda name: {},
        "looks_like_printer_or_mfp_name": lambda name: False,
        "find_printer_review_candidates": lambda name, top_n=5: [],
        "looks_like_peripheral_name": lambda name: False,
        "find_peripheral_review_candidates": lambda name, top_n=5: [],
    }
    deps.update(overrides)
    return deps


def _complete_ntech_runtime_deps(overrides):
    deps = {
        "normalize_name_key": lambda name: "runtime-key",
        "normalize_compact_name": lambda value: str(value or ""),
        "raw_paren_article_tokens": lambda value: [],
        "is_spec_code": lambda value: False,
        "db_connection": object(),
        "db_find_top_candidates": lambda *args, **kwargs: [],
        "db_find_exact_id_for_name": lambda *args, **kwargs: "",
        "infer_category": lambda value: "",
        "normalize_catalog_category_name": lambda value: value,
        "review_cpu_brand_model_key": lambda name, normalize_compact_name: ("", ""),
        "review_looks_like_cpu_name": lambda name: True,
        "review_find_cpu_candidates": lambda product_name, **kwargs: [],
        "review_board_brand_model_key": lambda name: {},
        "review_find_board_candidates": lambda product_name, **kwargs: [],
        "review_monitor_brand_model_key": lambda name: {},
        "review_find_monitor_candidates": lambda product_name, **kwargs: [],
        "review_gpu_brand_model_key": lambda name: {},
        "review_find_gpu_candidates": lambda product_name, **kwargs: [],
        "review_ram_brand_model_key": lambda name: {},
        "review_find_ram_candidates": lambda product_name, **kwargs: [],
        "review_ssd_brand_model_key": lambda name, **kwargs: {},
        "review_find_ssd_candidates": lambda product_name, **kwargs: [],
        "review_psu_brand_model_key": lambda name: {},
        "review_find_psu_candidates": lambda product_name, **kwargs: [],
        "review_case_brand_model_key": lambda name: {},
        "review_looks_like_case_name": lambda name: False,
        "review_find_case_candidates": lambda product_name, **kwargs: [],
        "review_hdd_brand_model_key": lambda name, **kwargs: {},
        "review_looks_like_hdd_name": lambda name: False,
        "review_find_hdd_candidates": lambda product_name, **kwargs: [],
        "review_cooler_brand_model_key": lambda name, **kwargs: {},
        "review_looks_like_cooler_name": lambda name: False,
        "review_looks_like_liquid_cpu_cooling_name": lambda name: False,
        "review_find_cooler_candidates": lambda product_name, **kwargs: [],
        "review_printer_mfp_brand_model_key": lambda name: {},
        "review_looks_like_printer_or_mfp_name": lambda name: False,
        "review_find_printer_candidates": lambda product_name, **kwargs: [],
        "review_looks_like_peripheral_name": lambda name: False,
        "review_find_peripheral_candidates": lambda product_name, **kwargs: [],
    }
    deps.update(overrides)
    return deps
