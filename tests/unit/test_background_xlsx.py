"""Tests for isolated and coalesced consolidated XLSX generation."""

import subprocess
import threading

import pandas as pd

from price_mixer.services.background_xlsx import BackgroundXlsxWorker
from price_mixer.workers.xlsx_writer import write_snapshot


def _sample_df(name):
    return pd.DataFrame({
        "OnlinerID": ["123"],
        "Название": [name],
        "Цена": [10.5],
        "Ссылка": ["https://catalog.onliner.by/test/123"],
    })


def _output_path(command):
    return command[command.index("--output") + 1]


def _input_path(command):
    return command[command.index("--input") + 1]


def test_worker_generates_xlsx_in_real_subprocess(tmp_path):
    worker = BackgroundXlsxWorker(process_timeout=30)

    queued = worker.enqueue(tmp_path, _sample_df("first"), label="unit-real")

    assert queued["state"] in {"queued", "running"}
    assert worker.wait_until_idle(30)
    status = worker.status(tmp_path)
    assert status["state"] == "done"
    assert status["attempts"] == 1
    result = pd.read_excel(tmp_path / "consolidated_price.xlsx")
    assert str(result.at[0, "OnlinerID"]) == "123"
    assert result.at[0, "Название"] == "first"
    assert result.at[0, "Цена"] == 10.5
    assert result.at[0, "Ссылка"] == "https://catalog.onliner.by/test/123"


def test_worker_retries_once_after_process_failure(tmp_path):
    calls = []

    def fake_runner(command, **_kwargs):
        calls.append(list(command))
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="temporary failure")
        write_snapshot(_input_path(command), _output_path(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    worker = BackgroundXlsxWorker(process_runner=fake_runner, max_attempts=2)
    worker.enqueue(tmp_path, _sample_df("retried"), label="unit-retry")

    assert worker.wait_until_idle(10)
    status = worker.status(tmp_path)
    assert status["state"] == "done"
    assert status["attempts"] == 2
    assert len(calls) == 2
    assert pd.read_excel(tmp_path / "consolidated_price.xlsx").at[0, "Название"] == "retried"


def test_worker_skips_queued_generations_older_than_latest(tmp_path):
    first_started = threading.Event()
    release_first = threading.Event()
    calls = []

    def blocking_runner(command, **_kwargs):
        calls.append(list(command))
        if len(calls) == 1:
            first_started.set()
            assert release_first.wait(5)
        write_snapshot(_input_path(command), _output_path(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    worker = BackgroundXlsxWorker(process_runner=blocking_runner)
    worker.enqueue(tmp_path, _sample_df("old"), label="generation-1")
    assert first_started.wait(5)
    worker.enqueue(tmp_path, _sample_df("intermediate"), label="generation-2")
    worker.enqueue(tmp_path, _sample_df("latest"), label="generation-3")
    release_first.set()

    assert worker.wait_until_idle(10)
    assert len(calls) == 2
    assert worker.status(tmp_path)["generation"] == 3
    assert pd.read_excel(tmp_path / "consolidated_price.xlsx").at[0, "Название"] == "latest"
    assert list(tmp_path.glob(".xlsx-job-*")) == []
    assert list(tmp_path.glob(".xlsx-result-*")) == []
