"""Canonical field names and wire positions for consolidated products."""

from __future__ import annotations

from enum import IntEnum


class ProductField:
    ONLINER_ID = "OnlinerID"
    NAME = "Название"
    PRICE = "Цена"
    SUPPLIER = "Поставщик"
    WARRANTY = "Гарантия"
    DELIVERY_DAYS = "Дней доставки"
    RRC = "РРЦ"
    NO_DISCOUNT = "Цена без скидки"
    CATEGORY = "Категория"


class ProductWireIndex(IntEnum):
    ONLINER_ID = 0
    NAME = 1
    PRICE = 2
    SUPPLIER = 3
    WARRANTY = 4
    DELIVERY_DAYS = 5
    RRC = 6
    NO_DISCOUNT = 7
    ROW_INDEX = 8
    CATEGORY = 9


CONSOLIDATED_COLUMNS = (
    ProductField.ONLINER_ID,
    ProductField.NAME,
    ProductField.PRICE,
    ProductField.SUPPLIER,
    ProductField.WARRANTY,
    ProductField.DELIVERY_DAYS,
    ProductField.RRC,
    ProductField.NO_DISCOUNT,
    ProductField.CATEGORY,
)

WIRE_FIELD_NAMES = (
    ProductField.ONLINER_ID,
    ProductField.NAME,
    ProductField.PRICE,
    ProductField.SUPPLIER,
    ProductField.WARRANTY,
    ProductField.DELIVERY_DAYS,
    ProductField.RRC,
    ProductField.NO_DISCOUNT,
    None,
    ProductField.CATEGORY,
)
