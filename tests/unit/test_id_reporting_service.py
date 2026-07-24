"""Unit tests for Onliner ID reporting payload helpers."""

import pandas as pd

from price_mixer.services import id_reporting as svc


def test_build_id_replace_candidates_payload_requires_name_or_query():
    assert svc.build_id_replace_candidates_payload({}, settings={}) == {"items": []}


def test_build_id_replace_candidates_payload_includes_current_id_when_allowed():
    payload = svc.build_id_replace_candidates_payload(
        {
            "name": "SSD",
            "category": "SSD",
            "onliner_id": " 123 ",
            "limit": 10,
        },
        settings={"no_id_search": {"max_candidates": 20}},
        db_get_product_by_id=lambda oid: {"name": "Current SSD", "url": "https://catalog.onliner.by/ssd/123"},
        db_find_exact_id_for_name=lambda name: {"id": "123", "name": "Duplicate current", "url": "", "score": 1},
        db_find_top_candidates=lambda name, **kwargs: [{"id": "456", "name": "Alt SSD", "url": "u", "score": 0.8765}],
        category_path_hints=lambda category: ["/ssd/"],
    )

    assert payload == {
        "items": [
            {
                "id": "123",
                "name": "Current SSD",
                "url": "https://catalog.onliner.by/ssd/123",
                "score": 0.0,
                "source": "current",
            },
            {
                "id": "456",
                "name": "Alt SSD",
                "url": "u",
                "score": 0.876,
                "source": "local_db",
            },
        ]
    }


def test_build_id_replace_candidates_payload_hides_current_name_when_category_path_mismatches():
    payload = svc.build_id_replace_candidates_payload(
        {"query": "Mouse", "category": "Мышь", "onliner_id": "123"},
        db_get_product_by_id=lambda oid: {"name": "Wrong", "url": "https://catalog.onliner.by/ssd/123"},
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
        category_path_hints=lambda category: ["/mouse/"],
    )

    assert payload["items"][0] == {
        "id": "123",
        "name": "Текущий ID 123",
        "url": "",
        "score": 0.0,
        "source": "current",
    }


def test_build_id_replace_candidates_payload_respects_exclude_current_and_limit():
    calls = {}

    def top_candidates(name, **kwargs):
        calls.update(kwargs)
        return [{"id": str(100 + idx), "name": f"Item {idx}", "url": "", "score": idx / 100} for idx in range(20)]

    payload = svc.build_id_replace_candidates_payload(
        {"name": "SSD", "onliner_id": "123", "exclude_current": "true", "limit": 50},
        settings={"no_id_search": {"max_candidates": 12}},
        db_find_top_candidates=top_candidates,
        db_find_exact_id_for_name=lambda name: None,
    )

    assert calls["top_n"] == 12
    assert len(payload["items"]) == 12
    assert payload["items"][0]["id"] == "119"
    assert all(item["source"] == "local_db" for item in payload["items"])


def test_build_id_replace_candidates_payload_uses_manual_query_and_preserves_match_details():
    calls = []

    payload = svc.build_id_replace_candidates_payload(
        {"name": "Полное длинное имя поставщика", "query": "IS-47-XT", "limit": 10},
        db_find_top_candidates=lambda name, **kwargs: calls.append(name) or [{
            "id": "3830919",
            "name": "Кулер для процессора ID-Cooling IS-47-XT",
            "url": "u",
            "score": 0.995,
            "source": "local_db",
            "reason": "article_like",
        }],
        db_find_exact_id_for_name=lambda name: None,
        specialized_candidates=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("custom query must not use category-specific matching")
        ),
    )

    assert calls == ["IS-47-XT"]
    assert payload["items"][0]["reason"] == "article_like"
    assert payload["items"][0]["source"] == "local_db"


def test_build_id_replace_candidates_payload_merges_specialized_candidates():
    payload = svc.build_id_replace_candidates_payload(
        {"name": "Процессор AMD Ryzen 5 3600", "category": "Процессор", "limit": 10},
        specialized_candidates=lambda name, **kwargs: [{
            "id": "1558780",
            "name": "Процессор AMD Ryzen 5 3600",
            "score": 0.999,
            "source": "cpu_db_seed",
            "reason": "cpu_model",
        }],
        db_find_top_candidates=lambda *args, **kwargs: [],
        db_find_exact_id_for_name=lambda name: None,
    )

    assert payload["items"] == [{
        "id": "1558780",
        "name": "Процессор AMD Ryzen 5 3600",
        "url": "",
        "score": 0.999,
        "source": "cpu_db_seed",
        "reason": "cpu_model",
    }]


def test_build_duplicate_onliner_ids_payload_handles_empty_and_clean_df():
    empty_payload = svc.build_duplicate_onliner_ids_payload(
        pd.DataFrame(),
        build_duplicate_onliner_id_issues=lambda df: (_ for _ in ()).throw(AssertionError("should not inspect empty df")),
    )

    assert empty_payload["message"] == "В текущем прайсе нет строк для проверки."

    clean_payload = svc.build_duplicate_onliner_ids_payload(
        pd.DataFrame({"Название": ["SSD"]}),
        build_duplicate_onliner_id_issues=lambda df: (0, []),
    )

    assert clean_payload == {
        "status": "ok",
        "problem_ids": 0,
        "problem_rows": 0,
        "items": [],
        "message": "Одинаковых OnlinerID у разных товаров не найдено.",
    }


def test_build_duplicate_onliner_ids_payload_reports_issues():
    issues = [{"onliner_id": "123"}, {"onliner_id": "123"}]

    payload = svc.build_duplicate_onliner_ids_payload(
        pd.DataFrame({"Название": ["A", "B"]}),
        build_duplicate_onliner_id_issues=lambda df: (1, issues),
    )

    assert payload == {
        "status": "ok",
        "problem_ids": 1,
        "problem_rows": 2,
        "items": issues,
        "message": "Найдено одинаковых OnlinerID: 1. Строк для проверки: 2.",
    }
