"""Runtime facade wiring Onliner market, B2B fallback, DB hints, and refresh jobs."""

from __future__ import annotations

from dataclasses import dataclass

from price_mixer.services import market_refresh as refresh_service
from price_mixer.services import onliner_market as market_service


@dataclass(frozen=True)
class OnlinerMarketRuntime:
    api_get: object
    get_product_by_id: object
    infer_category: object
    get_b2b_settings: object
    fetch_b2b_stats: object
    read_consolidated_df: object
    ensure_category_column: object
    row_category: object
    load_id_cache: object
    load_auto_refresh_settings: object
    save_auto_refresh_settings: object
    get_last_session_dir: object

    def fetch_product_payload(self, onliner_id):
        return market_service.fetch_onliner_product_payload(onliner_id, api_get=self.api_get)

    def fetch_catalog_market_stats(self, onliner_id):
        return market_service.fetch_onliner_market_stats_catalog_api(onliner_id, api_get=self.api_get)

    def fetch_market_stats(self, onliner_id, product_name="", category_name=""):
        return market_service.fetch_onliner_market_stats(
            onliner_id,
            product_name=product_name,
            category_name=category_name,
            api_get=self.api_get,
            get_b2b_settings=self.get_b2b_settings,
            fetch_b2b_stats=self.fetch_b2b_stats,
        )

    def get_market_stats_cached(self, onliner_id, cache=None):
        return market_service.get_onliner_market_stats_cached(
            onliner_id,
            cache=cache,
            get_product_by_id=self.get_product_by_id,
            infer_category_fn=self.infer_category,
            fetch_market_stats=self.fetch_market_stats,
        )

    def get_market_stats_bulk(self, onliner_ids, max_workers=22, id_hints=None):
        return market_service.get_onliner_market_stats_bulk(
            onliner_ids,
            max_workers=max_workers,
            id_hints=id_hints,
            fetch_market_stats=self.fetch_market_stats,
        )

    def fetch_product_info(self, onliner_id, cache=None, force_refresh=False, use_cache_on_error=True, product_name_hint=None):
        return market_service.fetch_onliner_product_info(
            onliner_id,
            cache=cache,
            force_refresh=force_refresh,
            use_cache_on_error=use_cache_on_error,
            product_name_hint=product_name_hint,
            api_get=self.api_get,
            get_product_by_id=self.get_product_by_id,
        )

    def market_refresh_worker(self, session_dir, categories):
        return refresh_service.market_refresh_worker(
            session_dir,
            categories,
            read_consolidated_df=self.read_consolidated_df,
            ensure_category_column=self.ensure_category_column,
            row_category=self.row_category,
            fetch_market_stats=self.fetch_market_stats,
            status=refresh_service.market_refresh_status,
            lock=refresh_service.MARKET_REFRESH_LOCK,
            max_workers=refresh_service.MARKET_REFRESH_POOL_WORKERS,
        )

    def collect_known_onliner_ids(self, max_ids, session_dir=None):
        return refresh_service.collect_known_onliner_ids(
            max_ids,
            session_dir=session_dir,
            read_consolidated_df=self.read_consolidated_df,
            load_market_cache=market_service.load_onliner_market_cache,
            load_id_cache=self.load_id_cache,
        )

    def market_id_hints_from_session(self, session_dir):
        return refresh_service.market_id_hints_from_session(
            session_dir,
            read_consolidated_df=self.read_consolidated_df,
            ensure_category_column=self.ensure_category_column,
            row_category=self.row_category,
        )

    def auto_market_refresh_loop(self):
        return refresh_service.auto_market_refresh_loop(
            load_settings=self.load_auto_refresh_settings,
            save_settings=self.save_auto_refresh_settings,
            collect_known_ids=self.collect_known_onliner_ids,
            get_last_session_dir=self.get_last_session_dir,
            get_id_hints=self.market_id_hints_from_session,
            fetch_market_stats=self.fetch_market_stats,
            load_cache=market_service.load_onliner_market_cache,
            save_cache=market_service.save_onliner_market_cache,
            status=refresh_service.market_refresh_status,
            lock=refresh_service.MARKET_REFRESH_LOCK,
            allowed_hours=refresh_service.AUTO_REFRESH_ALLOWED_HOURS,
            max_workers=refresh_service.MARKET_REFRESH_POOL_WORKERS,
            poll_sec=refresh_service.AUTO_REFRESH_POLL_SEC,
        )
