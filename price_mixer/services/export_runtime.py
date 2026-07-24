"""Revision-aware preparation cache shared by XLSX and Google exports."""

from __future__ import annotations

import threading
from collections import OrderedDict


class ExportRuntime:
    """Prepare an export DataFrame once for each complete session revision."""

    def __init__(
        self,
        *,
        prepare_export,
        read_consolidated_df,
        apply_visibility_filter,
        apply_keep_lowest_price_per_onliner_id,
        apply_duplicate_id_filter,
        apply_only_pc_filter,
        has_consolidated_data,
        max_entries=4,
    ):
        self.prepare_export = prepare_export
        self.read_consolidated_df = read_consolidated_df
        self.apply_visibility_filter = apply_visibility_filter
        self.apply_keep_lowest_price_per_onliner_id = apply_keep_lowest_price_per_onliner_id
        self.apply_duplicate_id_filter = apply_duplicate_id_filter
        self.apply_only_pc_filter = apply_only_pc_filter
        self.has_consolidated_data = has_consolidated_data
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._inflight = {}

    def prepare(self, session_dir, settings, *, revision_token):
        key = (str(session_dir), revision_token)
        while True:
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    dataframe, download_name = cached
                    return dataframe.copy() if dataframe is not None else None, download_name
                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    break
            event.wait()

        try:
            dataframe, download_name = self.prepare_export(
                session_dir,
                settings,
                read_consolidated_df=self.read_consolidated_df,
                apply_visibility_filter=self.apply_visibility_filter,
                apply_keep_lowest_price_per_onliner_id=self.apply_keep_lowest_price_per_onliner_id,
                apply_duplicate_id_filter=self.apply_duplicate_id_filter,
                apply_only_pc_filter=self.apply_only_pc_filter,
                has_consolidated_data=self.has_consolidated_data,
            )
            stored = dataframe.copy() if dataframe is not None else None
            with self._lock:
                self._cache[key] = (stored, download_name)
                self._cache.move_to_end(key)
                while len(self._cache) > self.max_entries:
                    self._cache.popitem(last=False)
            return dataframe.copy() if dataframe is not None else None, download_name
        finally:
            with self._lock:
                completed = self._inflight.pop(key, None)
                if completed is not None:
                    completed.set()

    def invalidate(self, session_dir=None):
        with self._lock:
            if session_dir is None:
                self._cache.clear()
                return
            target = str(session_dir)
            for key in [key for key in self._cache if key[0] == target]:
                self._cache.pop(key, None)
