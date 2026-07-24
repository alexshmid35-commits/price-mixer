#!/usr/bin/env python3
"""Run the local Onliner parser with candidate runtime state and exact PID."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("parser_dir")
    parser.add_argument("runtime_root")
    parser.add_argument("python")
    args = parser.parse_args(argv)

    parser_dir = Path(args.parser_dir).resolve()
    runtime = Path(args.runtime_root).resolve()
    state_dir = runtime / "state"
    log_dir = runtime / "logs"
    state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    os.environ.update({
        "PRICE_MIXER_ONLINER_API_SETTINGS": str(
            state_dir / "onliner_api_settings.json"
        ),
        "ONLINER_UI_HOST": "127.0.0.1",
        "ONLINER_UI_PORT": "5055",
        "PYTHONUNBUFFERED": "1",
    })
    (state_dir / "parallel-parser.pid").write_text(
        str(os.getpid()),
        encoding="ascii",
    )
    log_fd = os.open(
        log_dir / "parallel-parser.log",
        os.O_CREAT | os.O_APPEND | os.O_WRONLY,
        0o600,
    )
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    if log_fd > 2:
        os.close(log_fd)

    python = str(Path(args.python).absolute())
    os.chdir(parser_dir)
    os.execve(
        python,
        [python, str(parser_dir / "ui_server.py")],
        os.environ,
    )


if __name__ == "__main__":
    raise SystemExit(main())
