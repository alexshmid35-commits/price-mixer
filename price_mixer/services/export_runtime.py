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
        self._artifacts = OrderedDict()
        self._artifact_inflight = {}

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

    def build_artifact(
        self,
        session_dir,
        settings,
        *,
        revision_token,
        artifact_key,
        builder,
    ):
        key = (str(session_dir), revision_token, str(artifact_key))
        while True:
            with self._lock:
                cached = self._artifacts.get(key)
                if cached is not None:
                    self._artifacts.move_to_end(key)
                    return cached
                event = self._artifact_inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._artifact_inflight[key] = event
                    break
            event.wait()

        try:
            dataframe, download_name = self.prepare(
                session_dir,
                settings,
                revision_token=revision_token,
            )
            if dataframe is None:
                return None, download_name
            result = (bytes(builder(dataframe)), download_name)
            with self._lock:
                self._artifacts[key] = result
                self._artifacts.move_to_end(key)
                while len(self._artifacts) > self.max_entries:
                    self._artifacts.popitem(last=False)
            return result
        finally:
            with self._lock:
                completed = self._artifact_inflight.pop(key, None)
                if completed is not None:
                    completed.set()

    def invalidate(self, session_dir=None):
        with self._lock:
            if session_dir is None:
                self._cache.clear()
                self._artifacts.clear()
                return
            target = str(session_dir)
            for key in [key for key in self._cache if key[0] == target]:
                self._cache.pop(key, None)
            for key in [key for key in self._artifacts if key[0] == target]:
                self._artifacts.pop(key, None)
