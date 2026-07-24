"""Unit tests for export DataFrame filters."""

import pandas as pd

from price_mixer.services import export_filters as svc


def test_normalize_supplier_name_list_accepts_string_and_deduplicates():
    assert svc.normalize_supplier_name_list(" A, B\nA ; C ") == ["A", "B", "C"]


def test_build_duplicate_onliner_id_issues_reports_distinct_names_only():
    df = pd.DataFrame({
        "OnlinerID": ["111", "111", "222", "111"],
        "Название": ["SSD Kingston", "SSD Samsung", "Mouse", "SSD Kingston"],
        "Поставщик": ["A", "B", "C", "D"],
        "Категория": ["SSD", "SSD", "Мышь", "SSD"],
    })

    problem_ids, issues = svc.build_duplicate_onliner_id_issues(
        df,
        load_product_cache=lambda: {"111": {"name": "Cached product", "url": "https://example.test/111"}},
        row_category=lambda row: row.get("Категория", ""),
    )

    assert problem_ids == 1
    assert len(issues) == 3
    assert {item["supplier"] for item in issues} == {"A", "B", "D"}
    assert all(item["onliner_id"] == "111" for item in issues)
    assert all(item["api_name"] == "Cached product" for item in issues)
    assert any("SSD Samsung" in item["reason_label"] for item in issues)


def test_build_duplicate_onliner_id_issues_skips_confirmed_rows_when_all_confirmed():
    df = pd.DataFrame({
        "OnlinerID": ["111", "111"],
        "Название": ["SSD Kingston", "SSD Samsung"],
        "Поставщик": ["A", "B"],
    })

    problem_ids, issues = svc.build_duplicate_onliner_id_issues(
        df,
        is_manually_confirmed_id=lambda name, oid: True,
    )

    assert problem_ids == 0
    assert issues == []


def test_apply_export_duplicate_id_filter_drops_only_configured_suppliers():
    df = pd.DataFrame({
        "OnlinerID": ["111", "111", "222"],
        "Название": ["SSD Kingston", "SSD Samsung", "Mouse"],
        "Поставщик": ["Keep", "Drop", "Drop"],
    })

    result = svc.apply_export_duplicate_id_filter(df, supplier_names=["Drop"])

    assert list(result["Название"]) == ["SSD Kingston", "Mouse"]


def test_apply_export_keep_lowest_price_per_onliner_id_keeps_non_id_rows():
    df = pd.DataFrame({
        "OnlinerID": ["111", "111", "", "222", "222"],
        "Название": ["High", "Low", "No ID", "Bad price", "Good price"],
        "Цена": ["100,00", "90", "1", "bad", "50"],
    })

    result = svc.apply_export_keep_lowest_price_per_onliner_id(df)

    assert list(result["Название"]) == ["Low", "No ID", "Good price"]


def test_is_pc_export_row_detects_name_category_link_and_onliner_name():
    assert svc.is_pc_export_row({"Название": "Компьютер офисный"})
    assert svc.is_pc_export_row({"Категория": "Системный блок"})
    assert svc.is_pc_export_row({"Ссылка": "https://catalog.onliner.by/desktoppc/item"})
    assert svc.is_pc_export_row({"Onliner": "Iven SuperPower X"})
    assert svc.is_pc_export_row({"Название": "TGPC Action 81872 A-X"}, is_tgpc_pc_name=lambda name: True)
    assert not svc.is_pc_export_row({"Название": "Logitech Mouse", "Категория": "Мышь"})


def test_apply_export_only_pc_filter_affects_only_configured_suppliers():
    df = pd.DataFrame({
        "Поставщик": ["A", "A", "B"],
        "Название": ["Компьютер офисный", "Mouse", "Keyboard"],
        "Категория": ["Компьютер", "Мышь", "Клавиатура"],
    })

    result = svc.apply_export_only_pc_filter(df, supplier_names=["A"])

    assert list(result["Название"]) == ["Компьютер офисный", "Keyboard"]
