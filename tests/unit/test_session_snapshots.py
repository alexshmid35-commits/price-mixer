import json
import time

from price_mixer.services.consolidated_io import write_consolidated_json_rows
from price_mixer.services.session_snapshots import CompatibilitySnapshotWriter


def test_snapshot_writer_coalesces_updates_and_flushes_latest_rows(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    writer = CompatibilitySnapshotWriter(
        write_consolidated_json_rows,
        delay_seconds=0.05,
    )

    writer.schedule(session, [["old"]])
    writer.schedule(session, [["new"]])
    time.sleep(0.12)

    payload = json.loads((session / "consolidated.json").read_text(encoding="utf-8"))
    assert payload == {"data": [["new"]]}


def test_snapshot_writer_can_be_flushed_synchronously(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    writer = CompatibilitySnapshotWriter(
        write_consolidated_json_rows,
        delay_seconds=60,
    )

    writer.schedule(session, [["now"]])
    writer.flush(session)

    payload = json.loads((session / "consolidated.json").read_text(encoding="utf-8"))
    assert payload == {"data": [["now"]]}
