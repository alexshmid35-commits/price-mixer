import pandas as pd

from price_mixer.services.id_compare_report import build_id_compare_report_df, excel_text


def _normalize_id(value):
    text = str(value or "").strip()
    return text if text.isdigit() else ""


def _name_match_factory(scores):
    def _match(left, right):
        return {"score": scores.get((left, right), 1.0), "reason": "checked"}

    return _match


def test_excel_text_blanks_none_and_nan_values():
    assert excel_text(None) == ""
    assert excel_text(float("nan")) == ""
    assert excel_text("  Монитор  ") == "Монитор"


def test_build_id_compare_report_marks_valid_id():
    df = pd.DataFrame([{
        "OnlinerID": "123",
        "Название": "SSD Samsung 1TB",
        "Категория": "SSD",
        "Поставщик": "N-Tech",
        "Цена": 100,
    }])

    report = build_id_compare_report_df(
        df,
        {"123": {"id": "123", "name": "SSD Samsung 1TB", "url": "https://catalog.onliner.by/123"}},
        normalize_onliner_id=_normalize_id,
        calc_name_match=_name_match_factory({("SSD Samsung 1TB", "SSD Samsung 1TB"): 0.98}),
    )

    assert report.to_dict("records")[0] == {
        "Решение по ID": "ID верный",
        "Схожесть, %": 98.0,
        "ID в прайсе": "123",
        "Название поставщика": "SSD Samsung 1TB",
        "ID в базе": "123",
        "Название в базе": "SSD Samsung 1TB",
        "Категория": "SSD",
        "Поставщик": "N-Tech",
        "Цена": 100,
        "Причина": "checked",
        "Итог проверки": "Совпадает",
        "Комментарий проверки": "ID найден, ID совпадает, название прошло проверку.",
        "Что сделать": "Оставить ID",
        "URL в базе": "https://catalog.onliner.by/123",
    }


def test_build_id_compare_report_marks_mismatched_name():
    df = pd.DataFrame([{"OnlinerID": "456", "Название": "Блок питания", "Категория": "БП"}])

    report = build_id_compare_report_df(
        df,
        {"456": {"id": "456", "name": "Монитор 27"}},
        normalize_onliner_id=_normalize_id,
        calc_name_match=_name_match_factory({("Блок питания", "Монитор 27"): 0.42}),
    )

    row = report.to_dict("records")[0]
    assert row["Решение по ID"] == "Проверить ID"
    assert row["Итог проверки"] == "Название отличается"
    assert row["Что сделать"] == "Проверить / заменить ID"


def test_build_id_compare_report_marks_missing_db_product():
    df = pd.DataFrame([{"OnlinerID": "789", "Название": "Монитор"}])

    report = build_id_compare_report_df(
        df,
        {},
        normalize_onliner_id=_normalize_id,
        calc_name_match=_name_match_factory({}),
    )

    row = report.to_dict("records")[0]
    assert row["Решение по ID"] == "ID не найден"
    assert row["Итог проверки"] == "ID не найден в базе"
    assert row["Что сделать"] == "Проверить ID / найти товар"
