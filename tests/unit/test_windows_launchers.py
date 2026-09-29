"""Static regression checks for the Windows local service launchers."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_windows_start_launcher_uses_shared_runtime_and_all_components():
    script = (ROOT / "start_server.bat").read_text(encoding="utf-8")

    assert "PriceMixer_next_runtime_*" in script
    assert "state\\app_settings.json" in script
    assert "run_parser_component.py" in script
    assert "run_parallel_component.py\" worker" in script
    assert "run_parallel_component.py\" web" in script
    assert "127.0.0.1:5055/api/price-mixer/status" in script
    assert "127.0.0.1:5001/api/health" in script


def test_windows_stop_launcher_stops_all_components():
    script = (ROOT / "stop_server.bat").read_text(encoding="utf-8")

    assert "run_parser_component" in script
    assert "run_parallel_component" in script
    assert "durable_worker" in script
    assert "parallel-web.pid" in script
    assert "parallel-worker.pid" in script
    assert "parallel-parser.pid" in script
