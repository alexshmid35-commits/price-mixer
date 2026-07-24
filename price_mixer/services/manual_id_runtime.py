"""Runtime facade for manual Onliner ID actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from price_mixer.services import manual_id_actions


@dataclass(frozen=True)
class ManualIdRuntime:
    read_consolidated_json_fast_df: Callable
    read_consolidated_df: Callable
    write_consolidated_df: Callable
    write_consolidated_json: Callable
    load_id_cache: Callable
    save_id_cache: Callable
    sanitize_id_cache: Callable
    load_manual_id_bindings: Callable
    save_manual_id_bindings: Callable
    load_review_queue: Callable
    save_review_queue: Callable
    append_id_change_journal: Callable
    load_id_change_journal: Callable
    save_id_change_journal: Callable
    fetch_onliner_product_info: Callable
    normalize_name_key: Callable
    coerce_bool: Callable
    get_id_cache_key_for_name: Callable

    def confirm_batch(self, session_dir, payload):
        return manual_id_actions.confirm_manual_id_batch(
            session_dir,
            payload,
            read_consolidated_df=self.read_consolidated_json_fast_df,
            write_consolidated_df=self.write_consolidated_df,
            write_consolidated_json=self.write_consolidated_json,
            load_id_cache=self.load_id_cache,
            save_id_cache=self.save_id_cache,
            sanitize_id_cache=self.sanitize_id_cache,
            load_manual_id_bindings=self.load_manual_id_bindings,
            save_manual_id_bindings=self.save_manual_id_bindings,
            load_review_queue=self.load_review_queue,
            save_review_queue=self.save_review_queue,
            append_id_change_journal=self.append_id_change_journal,
            fetch_onliner_product_info=self.fetch_onliner_product_info,
            normalize_name_key_func=self.normalize_name_key,
            coerce_bool=self.coerce_bool,
        )

    def clear(self, session_dir, payload):
        return manual_id_actions.clear_manual_id(
            session_dir,
            payload,
            read_consolidated_df=self.read_consolidated_df,
            write_consolidated_df=self.write_consolidated_df,
            write_consolidated_json=self.write_consolidated_json,
            load_id_cache=self.load_id_cache,
            save_id_cache=self.save_id_cache,
            sanitize_id_cache=self.sanitize_id_cache,
            load_manual_id_bindings=self.load_manual_id_bindings,
            save_manual_id_bindings=self.save_manual_id_bindings,
            load_review_queue=self.load_review_queue,
            save_review_queue=self.save_review_queue,
            append_id_change_journal=self.append_id_change_journal,
            normalize_name_key_func=self.normalize_name_key,
            get_id_cache_key_for_name=self.get_id_cache_key_for_name,
        )

    def rollback_last(self, session_dir):
        return manual_id_actions.rollback_last_manual_id_change(
            session_dir,
            load_id_change_journal=self.load_id_change_journal,
            save_id_change_journal=self.save_id_change_journal,
            read_consolidated_df=self.read_consolidated_df,
            write_consolidated_df=self.write_consolidated_df,
            write_consolidated_json=self.write_consolidated_json,
            load_manual_id_bindings=self.load_manual_id_bindings,
            save_manual_id_bindings=self.save_manual_id_bindings,
        )
