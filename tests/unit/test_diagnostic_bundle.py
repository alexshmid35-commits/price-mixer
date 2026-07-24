import json
import sqlite3
import zipfile

import pytest

from price_mixer.services.diagnostic_bundle import (
    build_diagnostic_snapshot,
    create_diagnostic_bundle,
)


def _create_database(path):
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, secret TEXT)")
        connection.execute(
            "INSERT INTO products (secret) VALUES (?)",
            ("database-secret-value",),
        )
        connection.commit()
    finally:
        connection.close()


def test_diagnostic_bundle_excludes_secret_state_log_and_database_contents(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env").write_text("API_KEY=environment-secret", encoding="utf-8")
    (root / "manual_id_bindings.json").write_text(
        '{"private-product": "state-secret"}',
        encoding="utf-8",
    )
    (root / "logs").mkdir()
    (root / "logs" / "server.log").write_text(
        "Authorization: Bearer log-secret",
        encoding="utf-8",
    )
    (root / "uploads" / "private-session").mkdir(parents=True)
    (root / "uploads" / "private-session" / "customer.xlsx").write_bytes(b"private")
    _create_database(root / "onliner_products.db")
    destination = tmp_path / "diagnostics.zip"

    snapshot = create_diagnostic_bundle(
        root,
        destination,
        environ={
            "PRICE_MIXER_ENV": "production",
            "PRICE_MIXER_LOG_FORMAT": "json",
            "PRICE_MIXER_LOG_LEVEL": "info",
            "OPENAI_API_KEY": "environment-secret",
        },
    )

    assert snapshot["database"]["status"] == "ok"
    assert snapshot["database"]["quick_check"] == "ok"
    assert snapshot["database"]["table_count"] == 1
    assert snapshot["configuration"]["profile"] == "production"
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {"diagnostics.json", "README.txt"}
        rendered = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
    for forbidden in (
        "environment-secret",
        "state-secret",
        "log-secret",
        "database-secret-value",
        "private-product",
        "private-session",
        "customer.xlsx",
        ".env",
        "manual_id_bindings.json",
        "server.log",
    ):
        assert forbidden not in rendered


def test_diagnostic_bundle_refuses_to_overwrite_destination(tmp_path):
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"keep")

    with pytest.raises(FileExistsError):
        create_diagnostic_bundle(tmp_path, destination, environ={})

    assert destination.read_bytes() == b"keep"


def test_snapshot_allows_only_known_configuration_values(tmp_path):
    snapshot = build_diagnostic_snapshot(
        tmp_path,
        environ={
            "PRICE_MIXER_ENV": "production;password=secret",
            "PRICE_MIXER_LOG_LEVEL": "verbose-token",
            "PRICE_MIXER_WORKERS": "999999",
            "PRICE_MIXER_THREADS": "4",
            "PRICE_MIXER_TRUST_PROXY": "1",
        },
    )

    assert snapshot["configuration"] == {
        "profile": "unset-or-invalid",
        "log_level": "unset-or-invalid",
        "log_format": "unset-or-invalid",
        "workers": "unset-or-invalid",
        "threads": 4,
        "trust_proxy": "1",
    }
    assert "secret" not in json.dumps(snapshot)
