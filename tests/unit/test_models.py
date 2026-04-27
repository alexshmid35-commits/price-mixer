"""Unit tests for price_mixer.models."""

import pytest
from price_mixer.models import SupplierFile, ParsedRow, ConsolidatedRow, CategoryMarkup


def test_supplier_file_creation():
    f = SupplierFile(filepath="/tmp/test.xlsx", display_name="test.xlsx", supplier_name="IVEN")
    assert f.supplier_name == "IVEN"
    assert f.session_id is None


def test_parsed_row_defaults():
    r = ParsedRow(supplier="IVEN", name="Intel Core i5", price=100.0)
    assert r.warranty == ""
    assert r.onliner_id is None
    assert r.article is None


def test_consolidated_row_with_sources():
    row = ConsolidatedRow(
        onliner_id="123",
        name="Intel Core i5",
        price=99.0,
        supplier="IVEN",
        warranty="12 мес",
    )
    assert row.rrc is None
    assert row.sources == []


def test_category_markup_defaults():
    m = CategoryMarkup(category="Процессор")
    assert m.percent == 0.0
    assert m.threshold == 0.0
