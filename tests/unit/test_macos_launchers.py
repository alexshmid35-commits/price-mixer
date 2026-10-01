"""Regression checks for the single-entry macOS launcher."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def test_macos_launchers_have_valid_zsh_syntax():
    for relative_path in (
        "start_server.sh",
        "start_price_mixer.sh",
        "start_primary_local.command",
        "server_watchdog.sh",
    ):
        result = subprocess.run(
            ["zsh", "-n", str(ROOT / relative_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_main_macos_launcher_starts_the_complete_stack():
    script = (ROOT / "start_server.sh").read_text(encoding="utf-8")

    assert "start_primary_local.sh" in script
    assert "127.0.0.1:5001/api/health" in script
    assert "127.0.0.1:5055/api/price-mixer/status" in script
    assert "price_mixer.workers.durable_worker" in script
    assert "PriceMixer_next_runtime_2026-07-24" in script


def test_legacy_macos_entrypoints_delegate_to_main_launcher():
    for relative_path in (
        "start_price_mixer.sh",
        "start_primary_local.command",
        "server_watchdog.sh",
    ):
        script = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "start_server.sh" in script


def test_macos_stop_launchers_verify_pid_ownership():
    parallel = (ROOT / "scripts" / "stop_parallel_local.sh").read_text(
        encoding="utf-8"
    )
    primary = (ROOT / "scripts" / "stop_primary_local.sh").read_text(
        encoding="utf-8"
    )

    assert 'ps -p "$pid" -o command=' in parallel
    assert "price_mixer.workers.durable_worker" in parallel
    assert 'ps -p "$pid" -o command=' in primary
    assert "onliner-parser/ui_server.py" in primary
