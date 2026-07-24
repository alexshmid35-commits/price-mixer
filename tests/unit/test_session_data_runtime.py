"""Contract tests for SQL-first session data orchestration."""

from price_mixer.services.session_data_runtime import SessionDataRuntime
from price_mixer.services.session_products import SessionProductStore

ROWS = [
    ["1", "Monitor A", 100, "IVEN", "12", "2", 120, 130, 4, "Монитор"],
    ["", "Mouse B", 20, "Tradex", "6", "2", 25, 30, 5, "Мышь"],
]


class SnapshotSpy:
    def __init__(self):
        self.scheduled = []
        self.flushed = []

    def schedule(self, session_dir, rows):
        self.scheduled.append((session_dir, rows))
        return {"state": "queued"}

    def flush(self, session_dir):
        self.flushed.append(session_dir)


class XlsxWorkerSpy:
    def __init__(self, *, error=None):
        self.error = error
        self.enqueued = []
        self.status_calls = []

    def enqueue(self, session_dir, dataframe, *, label):
        if self.error is not None:
            raise self.error
        self.enqueued.append((session_dir, dataframe, label))
        return {"state": "queued", "label": label}

    def status(self, session_dir):
        self.status_calls.append(session_dir)
        return {"state": "done"}


def _runtime(tmp_path, *, mode="canonical", xlsx_worker=None, json_writer=None):
    return SessionDataRuntime(
        store=SessionProductStore(tmp_path / "sessions.db", mode=mode),
        snapshot_writer=SnapshotSpy(),
        xlsx_worker=xlsx_worker or XlsxWorkerSpy(),
        rows_from_dataframe=lambda frame: [list(row) for row in frame],
        dataframe_from_rows=lambda rows: ("sql", rows),
        compatibility_json_writer=json_writer or (lambda frame, path: ("json", frame, path)),
        clock_ns=lambda: 42,
    )


def test_canonical_write_updates_sql_and_schedules_snapshot(tmp_path):
    runtime = _runtime(tmp_path)
    changed = []
    session = tmp_path / "abc"

    result = runtime.write_json(ROWS, session / "consolidated.json", on_change=lambda: changed.append(True))

    assert result["status"] == "ok"
    assert result["row_count"] == 2
    assert runtime.store.metadata(session)["source_revision"] == "mutation:42"
    assert runtime.store.read_rows(session) == ROWS
    assert runtime.snapshot_writer.scheduled == [(session, ROWS)]
    assert changed == [True]


def test_legacy_write_uses_compatibility_writer(tmp_path):
    calls = []
    runtime = _runtime(
        tmp_path,
        mode="off",
        json_writer=lambda frame, path: calls.append((frame, path)) or {"status": "legacy"},
    )
    target = tmp_path / "abc" / "consolidated.json"

    result = runtime.write_json(ROWS, target)

    assert result == {"status": "legacy"}
    assert calls == [(ROWS, target)]
    assert runtime.snapshot_writer.scheduled == []


def test_fast_read_prefers_complete_sql_rows(tmp_path):
    runtime = _runtime(tmp_path)
    session = tmp_path / "abc"
    runtime.store.replace_rows(session, ROWS, source_revision="seed")

    result = runtime.read_fast_dataframe(
        session,
        json_reader=lambda _path: (_ for _ in ()).throw(AssertionError("JSON should not be read")),
        xlsx_reader=lambda _path: (_ for _ in ()).throw(AssertionError("XLSX should not be read")),
    )

    assert result == ("sql", ROWS)


def test_fast_read_ignores_incomplete_sql_and_uses_fallbacks(tmp_path):
    runtime = _runtime(tmp_path)
    session = tmp_path / "abc"
    runtime.store.replace_rows(session, ROWS, source_revision="partial", complete=False)

    assert runtime.read_fast_dataframe(
        session,
        json_reader=lambda _path: "json-frame",
        xlsx_reader=lambda _path: "xlsx-frame",
    ) == "json-frame"
    assert runtime.read_fast_dataframe(
        session,
        json_reader=lambda _path: None,
        xlsx_reader=lambda _path: "xlsx-frame",
    ) == "xlsx-frame"


def test_row_read_prefers_complete_sql_and_falls_back_for_partial_store(tmp_path):
    runtime = _runtime(tmp_path)
    complete = tmp_path / "complete"
    partial = tmp_path / "partial"
    complete.mkdir()
    partial.mkdir()
    partial_json = partial / "consolidated.json"
    partial_json.write_text("{}", encoding="utf-8")
    runtime.store.replace_rows(complete, ROWS, source_revision="complete")
    runtime.store.replace_rows(partial, ROWS, source_revision="partial", complete=False)

    assert runtime.read_rows(
        complete,
        complete / "consolidated.json",
        compatibility_rows_reader=lambda _path: [["legacy"]],
    ) == ROWS
    assert runtime.read_rows(
        partial,
        partial_json,
        compatibility_rows_reader=lambda _path: [["legacy"]],
    ) == [["legacy"]]
    assert runtime.read_rows(
        tmp_path / "missing",
        tmp_path / "missing" / "consolidated.json",
        compatibility_rows_reader=lambda _path: [["legacy"]],
    ) is None


def test_has_session_requires_complete_sql_or_compatibility_file(tmp_path):
    runtime = _runtime(tmp_path)
    complete = tmp_path / "complete"
    partial = tmp_path / "partial"
    runtime.store.replace_rows(complete, ROWS, source_revision="complete")
    runtime.store.replace_rows(partial, ROWS, source_revision="partial", complete=False)

    assert runtime.has_session(complete)
    assert not runtime.has_session(partial)
    partial.mkdir()
    (partial / "consolidated.json").write_text("{}", encoding="utf-8")
    assert runtime.has_session(partial)
    assert not runtime.has_session(None)


def test_canonical_xlsx_is_deferred_and_snapshot_can_be_flushed(tmp_path):
    worker = XlsxWorkerSpy()
    runtime = _runtime(tmp_path, xlsx_worker=worker)
    session = tmp_path / "abc"

    queued = runtime.write_dataframe_background(session, ROWS, label="mutation")
    status = runtime.xlsx_status(session)
    runtime.flush_snapshot(session)

    assert queued["state"] == "deferred"
    assert queued["label"] == "mutation"
    assert status["state"] == "deferred"
    assert worker.enqueued == []
    assert worker.status_calls == []
    assert runtime.snapshot_writer.flushed == [session]


def test_legacy_xlsx_uses_worker_and_reports_enqueue_errors(tmp_path):
    worker = XlsxWorkerSpy()
    runtime = _runtime(tmp_path, mode="off", xlsx_worker=worker)
    session = tmp_path / "abc"

    assert runtime.write_dataframe_background(session, ROWS, label="legacy")["state"] == "queued"
    assert runtime.xlsx_status(session) == {"state": "done"}
    assert worker.enqueued == [(session, ROWS, "legacy")]

    failed = _runtime(
        tmp_path,
        mode="off",
        xlsx_worker=XlsxWorkerSpy(error=RuntimeError("queue unavailable")),
    )
    payload = failed.write_dataframe_background(session, ROWS)
    assert payload == {
        "state": "error",
        "running": False,
        "message": "queue unavailable",
    }
