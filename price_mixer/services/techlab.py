"""Import Techlab's public XLSX price without guessing price or ID columns."""

import re

import numpy as np
import pandas as pd


PRICE_COLUMNS = ("Vip", "Дил", "Опт")
REQUIRED_COLUMNS = {"Код товара", "Наименование", "Парт-номер", "Внешний ID"}


def read_techlab_header(filepath):
    try:
        preview = pd.read_excel(filepath, header=None, nrows=40)
    except Exception as exc:
        raise ValueError("Techlab: сайт вернул не читаемый Excel-прайс") from exc
    for index, row in preview.iterrows():
        columns = {str(value).strip() for value in row if pd.notna(value)}
        if REQUIRED_COLUMNS.issubset(columns):
            return int(index)
    raise ValueError("Techlab: не найдены колонки прайса; формат файла изменился")


def _numbers(series):
    text = series.fillna("").astype(str).str.replace(r"[\s\u00a0]+", "", regex=True)
    return pd.to_numeric(text.str.replace(",", ".", regex=False), errors="coerce")


def _text(series):
    return series.fillna("").astype(str).str.strip()


def parse_techlab_excel(filepath, supplier_name="Techlab", *, settings=None):
    config = settings or {}
    price_column = config.get("price_column", "Опт")
    if price_column not in PRICE_COLUMNS:
        raise ValueError("Techlab: выбери ценовую колонку Vip, Дил или Опт")
    frame = pd.read_excel(filepath, header=read_techlab_header(filepath), dtype=str)
    frame.columns = frame.columns.astype(str).str.strip()
    if price_column not in frame.columns:
        raise ValueError(f"Techlab: отсутствует выбранная цена «{price_column}»")

    code = _text(frame["Код товара"]).str.replace(r"\.0$", "", regex=True)
    name = _text(frame["Наименование"])
    price = _numbers(frame[price_column])
    products = code.ne("") & name.ne("") & price.gt(0) & np.isfinite(price)
    frame = frame.loc[products].copy()
    result = pd.DataFrame(index=frame.index)
    result["supplier_code"] = code.loc[products]
    result["product_name"] = name.loc[products]
    result["price_byn"] = price.loc[products].round(2)
    result["supplier"] = supplier_name
    result["article"] = _text(frame["Парт-номер"])

    # A missing part number in the name must remain available to ID matching.
    def name_with_article(row):
        product_name, article = row["product_name"], row["article"]
        compact = lambda value: re.sub(r"[\W_]+", "", value.casefold())
        if compact(article) and compact(article) not in compact(product_name):
            return f"{product_name} ({article})"
        return product_name

    if not result.empty:
        result["product_name"] = result.apply(name_with_article, axis=1)
    ids = _text(frame["Внешний ID"]).str.replace(r"\.0$", "", regex=True)
    valid_ids = ids.str.fullmatch(r"[1-9]\d*")
    result["onliner_id"] = ids.where(valid_ids, np.nan)
    if "Внешняя ссылка" in frame:
        links = _text(frame["Внешняя ссылка"])
        result["onliner_url"] = links.where(
            links.str.match(r"^https?://catalog\.onliner\.by/[^\s]+$"), ""
        )
    if "Гар" in frame:
        result["warranty"] = _numbers(frame["Гар"])
    if "РРЦ" in frame:
        rrc = _numbers(frame["РРЦ"])
        result["rrc"] = rrc.where(rrc.gt(0) & np.isfinite(rrc), np.nan)
    if "Количество" in frame:
        result["quantity"] = _text(frame["Количество"])
        # Keep approximate quantities such as >10, but discard explicit zero stock.
        quantity = _numbers(frame["Количество"])
        result = result.loc[quantity.isna() | quantity.gt(0)]
    if "Группа" in frame:
        result["supplier_category"] = _text(frame["Группа"])
    availability = _text(frame["Наличие"]) if "Наличие" in frame else pd.Series("", index=frame.index)
    result["delivery_days"] = np.where(
        availability.loc[result.index].str.casefold().eq("склад"),
        int(config.get("stock_delivery_days", 2)),
        int(config.get("order_delivery_days", 2)),
    )
    return result.reset_index(drop=True)
