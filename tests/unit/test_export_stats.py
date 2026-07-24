import pandas as pd

from price_mixer.services import export_stats as svc


def _normalize_id(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _normalize_name_key(value):
    return " ".join(str(value or "").strip().lower().split())


def _normalize_supplier_list(value):
    return list(value or [])


def _is_pc_export_row(row):
    return "пэвм" in str(row.get("Название", "")).lower()


def _sort_key(value):
    return str(value).lower()


def test_export_stats_from_json_rows_applies_export_rules():
    rows = [
        ["1", "SSD A", "120", "IVEN", "", "", "", "", 0, "SSD"],
        ["1", "SSD B", "100", "N-Tech", "", "", "", "", 1, "SSD"],
        ["2", "Monitor", "300", "N-Tech", "", "", "", "", 2, "Монитор"],
        ["", "No ID", "10", "N-Tech", "", "", "", "", 3, "Кабели"],
        ["3", "ПЭВМ TGPC Office", "900", "TGPC", "", "", "", "", 4, "Системный блок"],
        ["4", "Клавиатура TGPC", "20", "TGPC", "", "", "", "", 5, "Клавиатура"],
    ]
    settings = {
        "export": {
            "include_without_id": False,
            "keep_lowest_price_per_onliner_id": True,
            "exclude_duplicate_id_suppliers": ["N-Tech"],
            "only_pc_suppliers": ["TGPC"],
        }
    }

    count = svc.export_row_count_from_json_rows(
        rows,
        settings,
        normalize_onliner_id=_normalize_id,
        normalize_name_key=_normalize_name_key,
        normalize_supplier_name_list=_normalize_supplier_list,
        is_pc_export_row=_is_pc_export_row,
    )
    categories = svc.export_category_counts_from_json_rows(
        rows,
        settings,
        normalize_onliner_id=_normalize_id,
        normalize_name_key=_normalize_name_key,
        normalize_supplier_name_list=_normalize_supplier_list,
        is_pc_export_row=_is_pc_export_row,
        category_sort_key=_sort_key,
    )

    assert count == 3
    assert categories == [
        {"category": "SSD", "count": 1},
        {"category": "Монитор", "count": 1},
        {"category": "Системный блок", "count": 1},
    ]


def test_export_stats_excludes_configured_category_prefix():
    rows = [
        ["1", "Ready SSD", "120", "A", "", "", "", "", 0, "SSD"],
        ["2", "Needs sorting", "100", "A", "", "", "", "", 1, "Требует сортировки · родитель: SSD"],
        ["3", "Needs sorting plain", "100", "A", "", "", "", "", 2, "Требует сортировки"],
    ]
    settings = {"export": {"exclude_category_prefixes": ["Требует сортировки"]}}

    assert svc.export_row_count_from_json_rows(
        rows,
        settings,
        normalize_onliner_id=_normalize_id,
        normalize_name_key=_normalize_name_key,
        normalize_supplier_name_list=_normalize_supplier_list,
        is_pc_export_row=_is_pc_export_row,
    ) == 1


def test_export_stats_excludes_configured_name_contains():
    rows = [
        ["1", "USB cable", "120", "A", "", "", "", "", 0, "Кабели и переходники"],
        ["2", "Патрон бесключевой Milwaukee", "100", "A", "", "", "", "", 1, "Кабели и переходники"],
        ["3", "Стойка для дрели P.I.T. P0010001", "100", "A", "", "", "", "", 2, "Кабели и переходники"],
        ["4", "Адаптер Milwaukee 4932367166", "100", "A", "", "", "", "", 3, "Кабели и переходники"],
    ]
    settings = {"export": {"exclude_name_contains": ["патрон", "milwaukee", "p.i.t"]}}

    assert svc.export_row_count_from_json_rows(
        rows,
        settings,
        normalize_onliner_id=_normalize_id,
        normalize_name_key=_normalize_name_key,
        normalize_supplier_name_list=_normalize_supplier_list,
        is_pc_export_row=_is_pc_export_row,
    ) == 1


def test_without_id_category_counts_from_json_and_df():
    rows = [
        ["1", "SSD", "120", "A", "", "", "", "", 0, "SSD"],
        ["", "No ID", "10", "A", "", "", "", "", 1, "Кабели"],
        ["", "No ID 2", "20", "A", "", "", "", "", 2, "Кабели"],
    ]
    df = pd.DataFrame({
        "OnlinerID": ["1", "", ""],
        "Категория": ["SSD", "Кабели", ""],
    })

    assert svc.without_id_category_counts_from_json_rows(
        rows,
        normalize_onliner_id=_normalize_id,
        category_sort_key=_sort_key,
    ) == [{"category": "Кабели", "count": 2}]
    assert svc.without_id_category_counts_from_df(
        df,
        normalize_onliner_id=_normalize_id,
        category_sort_key=_sort_key,
    ) == [
        {"category": "Без категории", "count": 1},
        {"category": "Кабели", "count": 1},
    ]
