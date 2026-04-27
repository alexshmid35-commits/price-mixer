"""Shared constants for supplier parsing and Onliner integration."""

import os
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent.resolve()
OUTPUT_FILE = SCRIPT_DIR / "consolidated_price.xlsx"

SUPPLIERS = {
    "BN-1030Z": {
        "file_pattern": "1030ZpriceBN*.xlsx",
        "sheet": 0,
        "header_row": 8,
        "columns": {
            0: "supplier_code",
            1: "product_name",
            3: "price_byn",
            4: "warranty",
            5: "onliner_id",
            6: "onliner_name",
        },
        "description": "BN заказ (полный ассортимент)",
    },
    "BN-1030": {
        "file_pattern": "1030priceBN*.xlsx",
        "sheet": 0,
        "header_row": 8,
        "columns": {
            0: "supplier_code",
            1: "product_name",
            2: "quantity",
            3: "price_byn",
            4: "warranty",
            5: "onliner_id",
            6: "onliner_name",
        },
        "description": "BN наличие",
    },
    "BN-1374": {
        "file_pattern": "1374priceBN*.xlsx",
        "sheet": 0,
        "header_row": 8,
        "columns": {
            0: "supplier_code",
            1: "product_name",
            2: "quantity",
            3: "price_byn",
            4: "warranty",
            5: "onliner_id",
            6: "onliner_name",
        },
        "description": "BN-1374 (ПК и комплектующие)",
    },
    "Tradex": {
        "file_pattern": "Tradex*.xlsx",
        "sheet_pattern": "Склад Минск",
        "header_row": 0,
        "columns": {
            0: "supplier_code",
            1: "product_name",
            2: "price_byn",
            4: "quantity",
            6: "status",
            9: "article",
            10: "warranty",
            13: "onliner_name",
            14: "onliner_id",
        },
        "filter": {"status": "В наличии"},
        "description": "Tradex (дистрибутор)",
    },
    "TGPC": {
        "file_pattern": "price_bn_*.xls*",
        "sheet": 0,
        "header_row": 0,
        "columns": {
            0: "supplier_code",
            2: "product_name",
            3: "warranty",
            6: "price_byn",
        },
        "description": "TGPC (безнал BYN)",
    },
}

CACHE_FILE = SCRIPT_DIR / "onliner_cache.json"
ONLINER_ID_CACHE = SCRIPT_DIR / "onliner_id_cache.json"

QUERY_CACHE = {}
QUERY_CACHE_LOCK = threading.Lock()
API_REQUEST_TIMEOUT = 12
API_REQUEST_RETRIES = 3
API_RETRY_DELAY = 1.2

CATALOG_SPREADSHEET_ID = os.getenv("ONLINER_CATALOG_SPREADSHEET_ID", "11zEGNWLqcOxhlm6SubOlW2xFvjQSrJAJJaUm-ga8iHM")
CATALOG_SHEET_NAME = os.getenv("ONLINER_CATALOG_SHEET_NAME", "All_Catalog")
_default_catalog_key = SCRIPT_DIR / "ai2025-462421-df1d36f12313.json"
_fallback_catalog_key = SCRIPT_DIR.parent / "Parsing_19_Сategories" / "ai2025-462421-df1d36f12313.json"
CATALOG_KEY_FILE = os.getenv(
    "ONLINER_CATALOG_KEY_FILE",
    str(_default_catalog_key if _default_catalog_key.exists() else _fallback_catalog_key),
)

CATALOG_INDEX = None
CATALOG_INDEX_LIGHT = None
CATALOG_INDEX_LOCK = threading.Lock()
ID_CACHE_IO_LOCK = threading.Lock()
