import sqlite3

from price_mixer.services.preflight import check_runtime_readiness


def _runtime_env(tmp_path):
    env = {}
    for key, name in (
        ("PRICE_MIXER_STATE_DIR", "state"),
        ("PRICE_MIXER_DATA_DIR", "data"),
        ("PRICE_MIXER_CACHE_DIR", "cache"),
        ("PRICE_MIXER_UPLOAD_DIR", "uploads"),
        ("PRICE_MIXER_LOG_DIR", "logs"),
    ):
        path = tmp_path / name
        path.mkdir()
        env[key] = str(path)
    env["PRICE_MIXER_JOB_DB"] = str(tmp_path / "data" / "jobs.db")
    return env


def test_runtime_preflight_accepts_writable_directories_and_valid_sqlite(tmp_path):
    env = _runtime_env(tmp_path)
    for name in ("onliner_products.db", "jobs.db"):
        with sqlite3.connect(tmp_path / "data" / name) as connection:
            connection.execute("CREATE TABLE sample (id INTEGER)")

    assert check_runtime_readiness(env) == []
    assert not list(tmp_path.rglob(".price-mixer-preflight-*"))


def test_runtime_preflight_reports_missing_directory_without_path_value(tmp_path):
    env = _runtime_env(tmp_path)
    missing = tmp_path / "missing-secret-location"
    env["PRICE_MIXER_CACHE_DIR"] = str(missing)

    errors = check_runtime_readiness(env)

    assert errors == ["PRICE_MIXER_CACHE_DIR directory does not exist"]
    assert str(missing) not in " ".join(errors)


def test_runtime_preflight_reports_corrupt_database_without_contents(tmp_path):
    env = _runtime_env(tmp_path)
    (tmp_path / "data" / "jobs.db").write_bytes(b"not-a-sqlite-database")

    assert check_runtime_readiness(env) == [
        "jobs.db failed SQLite quick_check"
    ]
