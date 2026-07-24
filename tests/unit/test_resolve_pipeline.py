import pandas as pd

from price_mixer.services.resolve_pipeline import (
    make_resolve_status,
    resolve_status_snapshot,
    start_resolve_payload,
)


def test_start_resolve_returns_already_running():
    status = {"running": True}

    assert start_resolve_payload(
        status,
        session_dir="/tmp/session",
        has_consolidated_session_file=lambda path: True,
        read_consolidated_json_fast_df=lambda path: pd.DataFrame(),
        load_url_cache=lambda: {},
        resolve_onliner_urls=lambda *args, **kwargs: None,
        read_consolidated_df=lambda path: pd.DataFrame(),
        write_consolidated_df=lambda path, df: None,
        write_consolidated_json=lambda df, path: None,
        thread_factory=lambda target: target(),
    ) == {"status": "already_running"}


def test_start_resolve_requires_session():
    status = make_resolve_status()

    assert start_resolve_payload(
        status,
        session_dir="",
        has_consolidated_session_file=lambda path: True,
        read_consolidated_json_fast_df=lambda path: pd.DataFrame(),
        load_url_cache=lambda: {},
        resolve_onliner_urls=lambda *args, **kwargs: None,
        read_consolidated_df=lambda path: pd.DataFrame(),
        write_consolidated_df=lambda path, df: None,
        write_consolidated_json=lambda df, path: None,
        thread_factory=lambda target: target(),
    ) == {"status": "error", "message": "No session"}


def test_start_resolve_updates_cache_and_writes_urls(tmp_path):
    status = make_resolve_status()
    source_df = pd.DataFrame([
        {"OnlinerID": "1", "Название": "One"},
        {"OnlinerID": "2", "Название": "Two"},
    ])
    written = {}
    cache = {"1": "https://catalog.onliner.by/one"}

    def resolve_onliner_urls(ids, *, cache, progress_callback, **kwargs):
        assert ids == ["2"]
        cache["2"] = "https://catalog.onliner.by/two"
        progress_callback(1, 1)

    result = start_resolve_payload(
        status,
        session_dir=tmp_path,
        has_consolidated_session_file=lambda path: True,
        read_consolidated_json_fast_df=lambda path: source_df,
        load_url_cache=lambda: cache,
        resolve_onliner_urls=resolve_onliner_urls,
        read_consolidated_df=lambda path: source_df.copy(),
        write_consolidated_df=lambda path, df: written.setdefault("df", df.copy()),
        write_consolidated_json=lambda df, path: written.setdefault("json_path", path),
        thread_factory=lambda target: target(),
    )

    assert result == {"status": "started", "total": 1}
    assert resolve_status_snapshot(status) == {"running": False, "resolved": 1, "total": 1, "cached": 2}
    assert written["df"]["Ссылка"].tolist() == [
        "https://catalog.onliner.by/one",
        "https://catalog.onliner.by/two",
    ]
    assert written["json_path"] == tmp_path / "consolidated.json"
