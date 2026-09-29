#!/usr/bin/env python3
"""Start the local Windows stack without shell-splitting paths with spaces."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values


PARSER_URL = "http://127.0.0.1:5055/api/price-mixer/status"
WEB_URL = "http://127.0.0.1:5001/api/health"


def build_component_commands(root: Path, runtime: Path, python: Path):
    """Return argv lists so Windows never reparses paths through cmd.exe."""
    return {
        "parser": [
            str(python),
            str(root / "onliner-parser" / "ui_server.py"),
        ],
        "worker": [
            str(python),
            "-m",
            "price_mixer.workers.durable_worker",
            "--poll-interval",
            "0.2",
        ],
        "web": [
            str(python),
            str(root / "app.py"),
        ],
    }


def build_component_environments(root: Path, runtime: Path):
    """Build the same environments as the Unix runners, directly in the parent."""
    base = os.environ.copy()
    for key, value in dotenv_values(root / ".env").items():
        if value is not None:
            base[str(key)] = str(value)

    state_dir = runtime / "state"
    parser_dir = root / "onliner-parser"
    parser_env = base | {
        "PRICE_MIXER_ONLINER_API_SETTINGS": str(state_dir / "onliner_api_settings.json"),
        "ONLINER_PARSER_STATE_DIR": str(state_dir / "onliner-parser"),
        "ONLINER_SHEETS_KEY_FILE": str(
            base.get("ONLINER_SHEETS_KEY_FILE")
            or root / "ai2025-462421-df1d36f12313.json"
        ),
        "ONLINER_UI_HOST": "127.0.0.1",
        "ONLINER_UI_PORT": "5055",
        "PYTHONUNBUFFERED": "1",
    }
    app_env = base | {
        "PRICE_MIXER_ENV": "development",
        "PRICE_MIXER_PORT": "5001",
        "PRICE_MIXER_STATE_DIR": str(state_dir),
        "PRICE_MIXER_DATA_DIR": str(runtime / "data"),
        "PRICE_MIXER_CACHE_DIR": str(runtime / "cache"),
        "PRICE_MIXER_UPLOAD_DIR": str(runtime / "uploads"),
        "PRICE_MIXER_LOG_DIR": str(runtime / "logs"),
        "PRICE_MIXER_BACKUP_DIR": str(runtime / "backups"),
        "PRICE_MIXER_JOB_MODE": "external",
        "PRICE_MIXER_JOB_DB": str(runtime / "data" / "jobs.db"),
        "PRICE_MIXER_SESSION_STORE_MODE": "canonical",
        "PYTHONUNBUFFERED": "1",
    }
    return {"parser": parser_env, "worker": app_env, "web": app_env}


def _http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _wait_http(url: str, timeout: float, process=None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _http_ready(url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.7)
    return False


def _wait_worker(process, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        time.sleep(0.25)
    return process.poll() is None


def _spawn(command, cwd: Path, log_path: Path, env, pid_file: Path):
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            close_fds=True,
            creationflags=creationflags,
        )
    pid_file.write_text(str(process.pid), encoding="ascii")
    return process


def _stop(processes) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    runtime_value = os.getenv("PRICE_MIXER_WINDOWS_RUNTIME_ROOT", "").strip()
    if not runtime_value:
        print("ERROR: PRICE_MIXER_WINDOWS_RUNTIME_ROOT is not set.")
        return 1

    runtime = Path(runtime_value).resolve()
    python = Path(sys.executable).resolve()
    log_dir = runtime / "logs"
    state_dir = runtime / "state"
    log_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "onliner-parser").mkdir(parents=True, exist_ok=True)
    for directory in ("data", "cache", "uploads", "backups"):
        (runtime / directory).mkdir(parents=True, exist_ok=True)
    commands = build_component_commands(root, runtime, python)
    environments = build_component_environments(root, runtime)
    started = []

    print("[5/8] Start Onliner parser on port 5055...")
    if not _http_ready(PARSER_URL):
        parser = _spawn(
            commands["parser"],
            root / "onliner-parser",
            log_dir / "parallel-parser.log",
            environments["parser"],
            state_dir / "parallel-parser.pid",
        )
        started.append(parser)
        if not _wait_http(PARSER_URL, 90, parser):
            print(f"ERROR: parser did not respond. Check {log_dir / 'parallel-parser.log'}")
            _stop(started)
            return 1
    else:
        print("Onliner parser is already running.")

    print("[6/8] Start background worker...")
    worker = _spawn(
        commands["worker"],
        root,
        log_dir / "parallel-worker.log",
        environments["worker"],
        state_dir / "parallel-worker.pid",
    )
    started.append(worker)
    if not _wait_worker(worker):
        print(f"ERROR: background worker did not start. Check {log_dir / 'parallel-worker.log'}")
        _stop(started)
        return 1

    print("[7/8] Start Price Mixer web server on port 5001...")
    web = _spawn(
        commands["web"],
        root,
        log_dir / "parallel-web.log",
        environments["web"],
        state_dir / "parallel-web.pid",
    )
    started.append(web)
    if not _wait_http(WEB_URL, 90, web):
        print(f"ERROR: web server did not respond. Check {log_dir / 'parallel-web.log'}")
        _stop(started)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
