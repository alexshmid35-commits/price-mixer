import pandas as pd

from price_mixer.services._legacy import consolidate_simple, parse_generic_excel


def test_consolidate_simple_preserves_no_id_rows_with_same_extracted_article():
    source = pd.DataFrame(
        {
            "supplier": ["NTech", "NTech", "NTech"],
            "supplier_code": ["1001", "1002", "1003"],
            "product_name": [
                "MB Alpha B650 (PCI-EX16)",
                "MB Beta X870 (PCI-EX16)",
                "MB Gamma Z790 (PCI-EX16)",
            ],
            "price_byn": [510.0, 620.0, 730.0],
        }
    )

    result = consolidate_simple(source)

    assert len(result) == 3
    assert set(result["Название"]) == set(source["product_name"])


def test_consolidate_simple_collapses_duplicate_no_id_supplier_code_only():
    source = pd.DataFrame(
        {
            "supplier": ["NTech", "NTech", "NTech"],
            "supplier_code": ["1001", "1001", "1002"],
            "product_name": [
                "SSD Alpha 1TB (PCI-EX16)",
                "SSD Alpha 1TB (PCI-EX16)",
                "SSD Beta 1TB (PCI-EX16)",
            ],
            "price_byn": [300.0, 250.0, 400.0],
        }
    )

    result = consolidate_simple(source)

    assert len(result) == 2
    alpha = result[result["Название"] == "SSD Alpha 1TB (PCI-EX16)"].iloc[0]
    assert alpha["Цена"] == 250.0


def test_consolidate_simple_preserves_distinct_codes_with_same_onliner_id():
    source = pd.DataFrame(
        {
            "supplier": ["BN-1374", "BN-1374"],
            "supplier_code": ["202079", "202080"],
            "onliner_id": ["5091687", "5091687"],
            "product_name": [
                "Компьютер IVEN SuperPower White 202079 Core i7/32Gb/RTX 5070",
                "Компьютер IVEN SuperPower White 202080 Core i7/64Gb/RTX 5070",
            ],
            "price_byn": [5984.46, 7711.75],
        }
    )

    result = consolidate_simple(source)

    assert len(result) == 2
    assert set(result["Название"]) == set(source["product_name"])


def test_consolidate_simple_keeps_group_aggregates_from_duplicate_source_rows():
    source = pd.DataFrame(
        {
            "supplier": ["IVEN", "IVEN"],
            "supplier_code": ["A-1", "A-1"],
            "onliner_id": ["123", "123"],
            "product_name": ["Product expensive", "Product cheapest"],
            "price_byn": [120.0, 100.0],
            "warranty": [36, 12],
            "delivery_days": ["5 days", "2 days"],
            "rrc": [150.0, 130.0],
        }
    )

    result = consolidate_simple(source)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["Название"] == "Product cheapest"
    assert row["Цена"] == 100.0
    assert row["Гарантия"] == 36
    assert row["Дней доставки"] == "5"
    assert row["РРЦ"] == 130.0


def test_parse_generic_excel_keeps_letter_only_product_names_with_price(tmp_path):
    path = tmp_path / "price.xlsx"
    source = pd.DataFrame(
        [
            ["Код", "Наименование", "Кол-во", "Цена с НДС", "Гарантия", "OnlinerID", "Onliner"],
            [155250, "Графический планшет Parblo Intangbo M Purple", "*", 312.89, 12, 2832724, ""],
        ]
    )
    source.to_excel(path, index=False, header=False)

    parsed = parse_generic_excel(str(path), "BN-1374")

    assert len(parsed) == 1
    assert parsed.iloc[0]["supplier_code"] == 155250


def test_parse_generic_excel_detects_header_after_preamble(tmp_path):
    path = tmp_path / "price-with-preamble.xlsx"
    source = pd.DataFrame([
        ["Supplier price", None, None],
        ["Generated today", None, None],
        ["Код", "Наименование", "Цена с НДС"],
        ["A-1", "SSD Test", 100.5],
    ])
    source.to_excel(path, index=False, header=False)

    parsed = parse_generic_excel(str(path), "Test")

    assert parsed[["supplier_code", "product_name", "price_byn"]].to_dict("records") == [{
        "supplier_code": "A-1",
        "product_name": "SSD Test",
        "price_byn": 100.5,
    }]


def test_parse_generic_excel_accepts_utf8_csv(tmp_path):
    path = tmp_path / "price.csv"
    source = pd.DataFrame([
        {
            "Код": "CSV-1",
            "Наименование": "SSD E2E Test 1TB",
            "Цена": 100.5,
            "Гарантия": 24,
            "OnlinerID": "123456",
        },
    ])
    source.to_csv(path, index=False, encoding="utf-8-sig")

    parsed = parse_generic_excel(str(path), "E2E")

    assert parsed[
        ["supplier_code", "product_name", "price_byn", "supplier", "onliner_id"]
    ].to_dict("records") == [{
        "supplier_code": "CSV-1",
        "product_name": "SSD E2E Test 1TB",
        "price_byn": 100.5,
        "supplier": "E2E",
        "onliner_id": "123456",
    }]


def test_parse_generic_excel_detects_ntech_dated_product_column(tmp_path):
    path = tmp_path / "ntech.xlsx"
    source = pd.DataFrame([
        [
            "код",
            None,
            "ПРАЙС 22.07.2026",
            "Гарантия",
            "Рекомендуемая\n розничная\n цена",
            "Цена без НДС",
            "Цена с НДС",
        ],
        [None, "Готовые решения TGPC", None, None, None, None, None],
        [None, "ПЭВМ", None, None, None, None, None],
        [
            91596,
            None,
            "ПЭВМ TGPC Action 3 91596",
            24,
            None,
            2112.66,
            2535.19,
        ],
    ])
    source.to_excel(path, index=False, header=False)

    parsed = parse_generic_excel(str(path), "N-Tech")

    assert parsed[["supplier_code", "product_name", "price_byn", "supplier"]].to_dict(
        "records"
    ) == [{
        "supplier_code": 91596,
        "product_name": "ПЭВМ TGPC Action 3 91596",
        "price_byn": 2535.19,
        "supplier": "N-Tech",
    }]
