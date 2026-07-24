import pandas as pd

from price_mixer.services.category_reference import (
    build_categories_payload,
    build_category_catalog_payload,
    build_supplier_categories_payload,
    build_suppliers_payload,
)


def _norm_category(value):
    return str(value or "").strip()


def _norm_id(value):
    return str(value or "").strip()


def _sort_key(name):
    order = {"CPU": 0, "SSD": 1, "Кабель": 2}
    return (order.get(name, 99), name.lower())


def _canonical_supplier(value):
    return {"ntech": "N-Tech"}.get(str(value or "").replace("-", "").lower(), str(value or "").strip())


def test_build_categories_payload_counts_rows_and_without_id():
    df = pd.DataFrame([
        {"Название": "CPU A", "Категория": "CPU", "OnlinerID": "1"},
        {"Название": "CPU B", "Категория": "CPU", "OnlinerID": ""},
        {"Название": "SSD A", "Категория": "SSD", "OnlinerID": "2"},
    ])

    assert build_categories_payload(
        df,
        normalize_category=_norm_category,
        normalize_onliner_id=_norm_id,
        category_sort_key=_sort_key,
    ) == {
        "categories": [
            {"name": "CPU", "count": 2, "without_id": 1},
            {"name": "SSD", "count": 1, "without_id": 0},
        ]
    }


def test_build_category_catalog_payload_merges_priority_overrides_markups_and_rows():
    df = pd.DataFrame([
        {"Категория": "Монитор"},
        {"Категория": "Требует сортировки · родитель: CPU"},
    ])

    payload = build_category_catalog_payload(
        priority_categories=["CPU"],
        overrides={"a": "SSD"},
        markups={"Кабель": {"percent": 10}},
        df=df,
        row_category=lambda row, overrides: row.get("Категория", ""),
        normalize_category=_norm_category,
        is_sorting_review_category=lambda name: str(name).startswith("Требует сортировки"),
        category_sort_key=_sort_key,
    )

    assert payload == {"categories": ["CPU", "SSD", "Кабель", "Монитор"]}


def test_build_suppliers_payload_returns_sorted_unique_names():
    df = pd.DataFrame({"Поставщик": ["N-Tech", "IVEN", "N-Tech", "", None]})

    assert build_suppliers_payload(df) == {"suppliers": ["IVEN", "N-Tech"]}


def test_build_supplier_categories_payload_marks_hidden_and_examples():
    df = pd.DataFrame([
        {"Поставщик": "N-Tech", "Категория": "CPU", "Название": "CPU A", "Цена": 10, "РРЦ": 12, "Цена без скидки": 15},
        {"Поставщик": "N-Tech", "Категория": "CPU", "Название": "CPU B", "Цена": 20, "РРЦ": 24, "Цена без скидки": 30},
        {"Поставщик": "N-Tech", "Категория": "SSD", "Название": "SSD A", "Цена": 30, "РРЦ": 36, "Цена без скидки": 45},
        {"Поставщик": "IVEN", "Категория": "CPU", "Название": "Other"},
        {"Поставщик": "N-Tech", "Категория": "Требует сортировки", "Название": "Skip"},
    ])

    payload = build_supplier_categories_payload(
        df,
        supplier="N-Tech",
        visibility_map={"N-Tech": ["SSD"]},
        canonical_supplier_name=_canonical_supplier,
        normalize_category=_norm_category,
        is_sorting_review_category=lambda name: str(name).startswith("Требует сортировки"),
        category_sort_key=_sort_key,
    )

    assert payload == {
        "status": "ok",
        "categories": [
            {
                "name": "CPU",
                "count": 3,
                "hidden": False,
                "examples": ["CPU A", "CPU B", "Other"],
                "items": [
                    {"name": "CPU A", "wholesale": "10", "rrc": "12", "no_discount": "15"},
                    {"name": "CPU B", "wholesale": "20", "rrc": "24", "no_discount": "30"},
                    {"name": "Other", "wholesale": "", "rrc": "", "no_discount": ""},
                ],
                "search_text": "CPU A CPU B Other",
            },
            {
                "name": "SSD",
                "count": 1,
                "hidden": True,
                "examples": ["SSD A"],
                "items": [{"name": "SSD A", "wholesale": "30", "rrc": "36", "no_discount": "45"}],
                "search_text": "SSD A",
            },
        ],
    }


def test_build_supplier_categories_payload_filters_non_structure_categories():
    df = pd.DataFrame([
        {"Поставщик": "Tradex", "Категория": "Drillbits", "Название": "Сверло Bosch"},
        {"Поставщик": "Tradex", "Категория": "ЭЛЕКТРОННАЯ", "Название": "Сырой заголовок"},
        {"Поставщик": "Tradex", "Категория": "Электронные книги", "Название": "Книга"},
    ])
    known = {"Сверла и буры", "Электронные книги"}

    payload = build_supplier_categories_payload(
        df,
        supplier="Tradex",
        visibility_map={},
        canonical_supplier_name=_canonical_supplier,
        normalize_category=lambda value: {"Drillbits": "Сверла и буры"}.get(str(value), str(value or "").strip()),
        is_sorting_review_category=lambda name: False,
        category_sort_key=_sort_key,
        include_category=lambda name: name in known,
    )

    assert payload == {
        "status": "ok",
        "categories": [
            {
                "name": "Сверла и буры",
                "count": 1,
                "hidden": False,
                "examples": ["Сверло Bosch"],
                "items": [{"name": "Сверло Bosch", "wholesale": "", "rrc": "", "no_discount": ""}],
                "search_text": "Сверло Bosch",
            },
            {
                "name": "Электронные книги",
                "count": 1,
                "hidden": False,
                "examples": ["Книга"],
                "items": [{"name": "Книга", "wholesale": "", "rrc": "", "no_discount": ""}],
                "search_text": "Книга",
            },
        ],
    }
