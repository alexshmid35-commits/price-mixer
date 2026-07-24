"""Standalone entry point for bulk OnlinerID verification."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from price_mixer.services.isolated_verify_job import DurableVerifyStatusWriter
from price_mixer.state_store import load_dict, save_json_atomic


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify all Price Mixer Onliner IDs")
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)

    status_path = Path(args.status_file).resolve()
    current = load_dict(status_path)
    if str(current.get("job_id", "")) != str(args.job_id):
        return 2
    current.update({"pid": os.getpid(), "running": True, "state": "running"})
    save_json_atomic(status_path, current)

    import app as app_module

    writer = DurableVerifyStatusWriter(status_path, args.job_id, pid=os.getpid())
    app_module.VERIFY_ALL_IDS_STATUS_WRITER = writer
    with app_module.VERIFY_ALL_IDS_LOCK:
        app_module.verify_all_ids_status.clear()
        app_module.verify_all_ids_status.update(current)
    app_module._verify_all_ids_worker(str(Path(args.session_dir).resolve()))
    with app_module.VERIFY_ALL_IDS_LOCK:
        final_status = dict(app_module.verify_all_ids_status)
        final_status["items"] = list(final_status.get("items", []) or [])
        final_status["report_items"] = list(final_status.get("report_items", []) or [])
    writer(final_status, force=True)
    return 0 if final_status.get("state") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
