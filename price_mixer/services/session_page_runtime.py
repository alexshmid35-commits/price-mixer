"""SQL-first consolidated-table paging with a verified compatibility fallback."""

from __future__ import annotations


class SessionPageRuntime:
    def __init__(self, *, store, compatibility_cache, logger=None):
        self.store = store
        self.compatibility_cache = compatibility_cache
        self.logger = logger

    def build_page(
        self,
        session_dir,
        rows,
        *,
        source_revision,
        page_arguments,
        badge_counts_builder,
        export_indexes=None,
        snapshot_names=None,
    ):
        payload = None
        filter_mode = str(
            (page_arguments or {}).get("filter_mode", "all") or "all"
        ).strip().casefold()
        if self.store.canonical and filter_mode in {"all", "no_id", "duplicate"}:
            try:
                sync_result = self.store.replace_rows(
                    session_dir,
                    rows,
                    source_revision=source_revision,
                    badge_counts=lambda: badge_counts_builder(rows),
                )
                if sync_result.get("changed"):
                    parity = self.store.parity(session_dir, rows)
                    if parity.get("status") != "ok":
                        raise RuntimeError("session_products parity check failed")
                payload = self.store.query_page(
                    session_dir,
                    **page_arguments,
                )
                if payload is not None:
                    payload.setdefault("meta", {})["revision"] = sync_result.get(
                        "revision",
                        0,
                    )
            except Exception:
                if self.logger is not None:
                    self.logger.exception(
                        "session_products SQL page failed; using compatibility path"
                    )
                payload = None
        if payload is None:
            payload = self.compatibility_cache.build_page(
                source_revision,
                rows,
                **page_arguments,
                export_indexes=export_indexes,
                snapshot_names=snapshot_names,
                badge_counts_builder=badge_counts_builder,
            )
            payload.setdefault("meta", {})["storage"] = "compatibility"
        return payload
