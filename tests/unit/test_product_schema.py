from price_mixer.product_schema import (
    CONSOLIDATED_COLUMNS,
    ProductField,
    ProductWireIndex,
)


def test_product_schema_has_one_canonical_mapping():
    assert CONSOLIDATED_COLUMNS[0] == ProductField.ONLINER_ID
    assert CONSOLIDATED_COLUMNS[-1] == ProductField.CATEGORY
    assert ProductWireIndex.ROW_INDEX == 8
    assert ProductWireIndex.CATEGORY == 9
