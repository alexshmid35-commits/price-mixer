"""Price Mixer business services.

Legacy mixer symbols are exported lazily so importing lightweight service
modules does not eagerly load pandas/numpy-heavy legacy code.
"""

_LEGACY_EXPORTS = {
    "CACHE_FILE",
    "ONLINER_ID_CACHE",
    "OUTPUT_FILE",
    "SUPPLIERS",
    "_load_catalog_sheet_index",
    "build_id_fanout_map",
    "consolidate",
    "consolidate_simple",
    "detect_supplier",
    "export_excel",
    "extract_article",
    "extract_article_candidates",
    "find_file",
    "find_missing_onliner_ids",
    "find_sheet",
    "get_onliner_link",
    "is_trusted_cached_id",
    "load_id_cache",
    "load_url_cache",
    "lookup_catalog_match_details",
    "lookup_id_from_catalog_sheet",
    "parse_generic_excel",
    "parse_supplier",
    "parse_supplier_from_file",
    "prune_negative_id_cache",
    "resolve_onliner_urls",
    "save_id_cache",
    "save_url_cache",
    "verify_catalog_id_with_prefix",
    "warm_url_cache_from_id_cache",
}

__all__ = sorted(_LEGACY_EXPORTS)


def __getattr__(name):
    if name in _LEGACY_EXPORTS:
        from price_mixer.services import _legacy

        value = getattr(_legacy, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
