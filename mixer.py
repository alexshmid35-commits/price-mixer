#!/usr/bin/env python3
"""
Price Mixer — LEGACY PROXY MODULE

This module re-exports all symbols from price_mixer.services for backward
compatibility with app.py and standalone scripts.

New code should import directly from price_mixer.services.
"""

from price_mixer.services._legacy import (
    load_url_cache,
    save_url_cache,
    resolve_onliner_urls,
    parse_generic_excel,
    consolidate_simple,
    find_missing_onliner_ids,
    load_id_cache,
    save_id_cache,
    build_id_fanout_map,
    is_trusted_cached_id,
    prune_negative_id_cache,
    warm_url_cache_from_id_cache,
    extract_article,
    extract_article_candidates,
    lookup_id_from_catalog_sheet,
    lookup_catalog_match_details,
    verify_catalog_id_with_prefix,
    _load_catalog_sheet_index,
    detect_supplier,
    find_file,
    find_sheet,
    parse_supplier_from_file,
    parse_supplier,
    consolidate,
    export_excel,
    get_onliner_link,
    main,
    SUPPLIERS,
    CACHE_FILE,
    ONLINER_ID_CACHE,
    OUTPUT_FILE,
    SCRIPT_DIR,
)

__all__ = [
    "load_url_cache",
    "save_url_cache",
    "resolve_onliner_urls",
    "parse_generic_excel",
    "consolidate_simple",
    "find_missing_onliner_ids",
    "load_id_cache",
    "save_id_cache",
    "build_id_fanout_map",
    "is_trusted_cached_id",
    "prune_negative_id_cache",
    "warm_url_cache_from_id_cache",
    "extract_article",
    "extract_article_candidates",
    "lookup_id_from_catalog_sheet",
    "lookup_catalog_match_details",
    "verify_catalog_id_with_prefix",
    "_load_catalog_sheet_index",
    "detect_supplier",
    "find_file",
    "find_sheet",
    "parse_supplier_from_file",
    "parse_supplier",
    "consolidate",
    "export_excel",
    "get_onliner_link",
    "main",
    "SUPPLIERS",
    "CACHE_FILE",
    "ONLINER_ID_CACHE",
    "OUTPUT_FILE",
    "SCRIPT_DIR",
]
