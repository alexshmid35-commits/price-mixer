"""Regression checks for the Windows local service launchers."""

import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]


def _load_windows_stack_module():
    path = ROOT / "scripts" / "start_windows_stack.py"
    spec = importlib.util.spec_from_file_location("start_windows_stack", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_windows_start_launcher_uses_shared_runtime_and_all_components():
    script = (ROOT / "start_server.bat").read_text(encoding="utf-8")

    assert "PriceMixer_next_runtime_*" in script
    assert "state\\app_settings.json" in script
    assert "start_windows_stack.py" in script
    assert "PRICE_MIXER_WINDOWS_RUNTIME_ROOT" in script
    assert "127.0.0.1:5055/api/price-mixer/status" in script
    assert "127.0.0.1:5001/api/health" in script


def test_windows_stack_preserves_paths_with_spaces_as_single_arguments(tmp_path):
    module = _load_windows_stack_module()
    root = tmp_path / "Alexey Nikolaevich" / "PriceMixer_next_2026-07-24"
    runtime = tmp_path / "Alexey Nikolaevich" / "PriceMixer_next_runtime_2026-07-24"
    python = root / ".venv-win" / "Scripts" / "python.exe"

    commands = module.build_component_commands(root, runtime, python)

    assert commands["parser"][0] == str(python)
    assert commands["parser"][1] == str(root / "onliner-parser" / "ui_server.py")
    assert commands["worker"] == [
        str(python),
        "-m",
        "price_mixer.workers.durable_worker",
        "--poll-interval",
        "0.2",
    ]
    assert commands["web"][1] == str(root / "app.py")
    assert all(isinstance(argument, str) for command in commands.values() for argument in command)

    environments = module.build_component_environments(root, runtime)
    assert environments["parser"]["ONLINER_PARSER_STATE_DIR"] == str(
        runtime / "state" / "onliner-parser"
    )
    assert environments["worker"]["PRICE_MIXER_STATE_DIR"] == str(runtime / "state")
    assert environments["web"]["PRICE_MIXER_DATA_DIR"] == str(runtime / "data")


def test_windows_stack_spawns_and_logs_from_directory_with_spaces(tmp_path):
    module = _load_windows_stack_module()
    workdir = tmp_path / "Alexey Nikolaevich" / "Price Mixer"
    workdir.mkdir(parents=True)
    log_path = workdir / "component.log"
    pid_file = workdir / "component.pid"

    process = module._spawn(
        [sys.executable, "-c", "print('component started')"],
        workdir,
        log_path,
        os.environ.copy(),
        pid_file,
    )

    assert process.wait(timeout=5) == 0
    assert int(pid_file.read_text(encoding="ascii")) == process.pid
    assert log_path.read_text(encoding="utf-8").strip() == "component started"


def test_windows_stop_launcher_stops_all_components():
    script = (ROOT / "stop_server.bat").read_text(encoding="utf-8")

    assert "run_parser_component" in script
    assert "run_parallel_component" in script
    assert "durable_worker" in script
    assert "parallel-web.pid" in script
    assert "parallel-worker.pid" in script
    assert "parallel-parser.pid" in script
