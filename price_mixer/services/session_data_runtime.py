"""SQL-first session data orchestration with compatibility fallbacks."""

from __future__ import annotations

import time
from pathlib import Path


class SessionDataRuntime:
    """Coordinate canonical SQL rows, JSON snapshots, and deferred XLSX writes."""

    def __init__(
        self,
        *,
        store,
        snapshot_writer,
        xlsx_worker,
        rows_from_dataframe,
        dataframe_from_rows,
        compatibility_json_writer,
        logger=None,
        clock_ns=time.time_ns,
    ):
        self.store = store
        self.snapshot_writer = snapshot_writer
        self.xlsx_worker = xlsx_worker
        self.rows_from_dataframe = rows_from_dataframe
        self.dataframe_from_rows = dataframe_from_rows
        self.compatibility_json_writer = compatibility_json_writer
        self.logger = logger
        self.clock_ns = clock_ns

    def write_json(self, dataframe, json_path, *, on_change=None):
        target = Path(json_path)
        if not self.store.canonical:
            return self.compatibility_json_writer(dataframe, target)

        rows = self.rows_from_dataframe(dataframe)
        sync = self.store.reconcile_rows(
            target.parent,
            rows,
            source_revision=f"mutation:{self.clock_ns()}",
        )
        self.snapshot_writer.schedule(target.parent, rows)
        if on_change is not None:
            on_change()
        return sync

    def read_fast_dataframe(self, session_dir, *, json_reader, xlsx_reader):
        if self.store.canonical:
            rows = self.store.read_rows(session_dir)
            if rows is not None:
                return self.dataframe_from_rows(rows)
        try:
            dataframe = json_reader(session_dir)
            if dataframe is not None:
                return dataframe
        except Exception:
            if self.logger is not None:
                self.logger.exception("compatibility JSON read failed; using XLSX fallback")
        return xlsx_reader(session_dir)

    def read_rows(self, session_dir, json_path, *, compatibility_rows_reader):
        if self.store.canonical:
            rows = self.store.read_rows(session_dir)
            if rows is not None:
                return rows
        target = Path(json_path)
        if not target.exists():
            return None
        return compatibility_rows_reader(target)

    def has_session(self, session_dir):
        if not session_dir:
            return False
        session_path = Path(session_dir)
        sql_meta = self.store.metadata(session_path) if self.store.canonical else None
        if sql_meta and bool(sql_meta.get("complete")):
            return True
        return (session_path / "consolidated.json").exists() or (session_path / "consolidated_price.xlsx").exists()

    def write_dataframe_background(self, session_dir, dataframe, *, label="consolidated"):
        if self.store.canonical:
            return self._deferred_xlsx_payload(label=label)
        try:
            return self.xlsx_worker.enqueue(session_dir, dataframe, label=label)
        except Exception as exc:
            if self.logger is not None:
                self.logger.exception("background XLSX queue failed label=%s", label)
            return {"state": "error", "running": False, "message": str(exc)}

    def xlsx_status(self, session_dir):
        if self.store.canonical:
            return self._deferred_xlsx_payload()
        return self.xlsx_worker.status(session_dir)

    def flush_snapshot(self, session_dir):
        if self.store.canonical:
            self.snapshot_writer.flush(session_dir)

    @staticmethod
    def _deferred_xlsx_payload(*, label=None):
        payload = {
            "state": "deferred",
            "running": False,
            "message": "Рабочие данные актуальны в SQL; XLSX создаётся при экспорте.",
        }
        if label is not None:
            payload["label"] = str(label)
            payload["message"] = "XLSX будет сформирован из актуальной SQL-сессии при экспорте."
        return payload
