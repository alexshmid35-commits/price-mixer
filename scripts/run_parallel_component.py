#!/usr/bin/env python3
"""Run one local parallel component with an exact, stoppable process PID."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import dotenv_values


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=("web", "worker"))
    parser.add_argument("root_dir")
    parser.add_argument("runtime_root")
    parser.add_argument("port", type=int)
    parser.add_argument("env_file")
    parser.add_argument("python")
    args = parser.parse_args(argv)

    root = Path(args.root_dir).resolve()
    runtime = Path(args.runtime_root).resolve()
    directories = {
        "state": runtime / "state",
        "data": runtime / "data",
        "cache": runtime / "cache",
        "uploads": runtime / "uploads",
        "logs": runtime / "logs",
        "backups": runtime / "backups",
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)

    for key, value in dotenv_values(args.env_file).items():
        if value is not None:
            os.environ[str(key)] = str(value)
    os.environ.update({
        "PRICE_MIXER_ENV": "development",
        "PRICE_MIXER_PORT": str(args.port),
        "PRICE_MIXER_STATE_DIR": str(directories["state"]),
        "PRICE_MIXER_DATA_DIR": str(directories["data"]),
        "PRICE_MIXER_CACHE_DIR": str(directories["cache"]),
        "PRICE_MIXER_UPLOAD_DIR": str(directories["uploads"]),
        "PRICE_MIXER_LOG_DIR": str(directories["logs"]),
        "PRICE_MIXER_BACKUP_DIR": str(directories["backups"]),
        "PRICE_MIXER_JOB_MODE": "external",
        "PRICE_MIXER_JOB_DB": str(directories["data"] / "jobs.db"),
        "PYTHONUNBUFFERED": "1",
    })

    pid_file = directories["state"] / f"parallel-{args.component}.pid"
    pid_file.write_text(str(os.getpid()), encoding="ascii")
    log_path = directories["logs"] / f"parallel-{args.component}.log"
    log_fd = os.open(
        log_path,
        os.O_CREAT | os.O_APPEND | os.O_WRONLY,
        0o600,
    )
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    if log_fd > 2:
        os.close(log_fd)

    os.chdir(root)
    python = str(Path(args.python).absolute())
    if args.component == "web":
        command = [python, str(root / "app.py")]
    else:
        command = [
            python,
            "-m",
            "price_mixer.workers.durable_worker",
            "--poll-interval",
            "0.2",
        ]
    os.execve(python, command, os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
