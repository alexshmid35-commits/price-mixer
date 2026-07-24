import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from price_mixer.services.export_runtime import ExportRuntime


def _runtime(calls):
    def prepare(session_dir, settings, **dependencies):
        calls.append((session_dir, settings, dependencies))
        return pd.DataFrame({"Название": [settings["name"]]}), "price.xlsx"

    return ExportRuntime(
        prepare_export=prepare,
        read_consolidated_df=lambda _path: None,
        apply_visibility_filter=lambda frame, _path: frame,
        apply_keep_lowest_price_per_onliner_id=lambda frame: frame,
        apply_duplicate_id_filter=lambda frame, _suppliers: frame,
        apply_only_pc_filter=lambda frame, _suppliers: frame,
        has_consolidated_data=lambda _path: True,
    )


def test_export_runtime_prepares_once_per_revision_and_returns_copies():
    calls = []
    runtime = _runtime(calls)

    first, name = runtime.prepare("session-a", {"name": "A"}, revision_token=("r", 1))
    first.at[0, "Название"] = "changed"
    second, second_name = runtime.prepare("session-a", {"name": "A"}, revision_token=("r", 1))

    assert name == second_name == "price.xlsx"
    assert second.at[0, "Название"] == "A"
    assert len(calls) == 1

    runtime.prepare("session-a", {"name": "B"}, revision_token=("r", 2))
    assert len(calls) == 2


def test_export_runtime_invalidates_only_requested_session():
    calls = []
    runtime = _runtime(calls)
    runtime.prepare("session-a", {"name": "A"}, revision_token=("r", 1))
    runtime.prepare("session-b", {"name": "B"}, revision_token=("r", 1))

    runtime.invalidate("session-a")
    runtime.prepare("session-a", {"name": "A"}, revision_token=("r", 1))
    runtime.prepare("session-b", {"name": "B"}, revision_token=("r", 1))

    assert len(calls) == 3


def test_export_runtime_coalesces_concurrent_preparation():
    calls = []

    def prepare(session_dir, settings, **_dependencies):
        calls.append((session_dir, settings))
        time.sleep(0.05)
        return pd.DataFrame({"Название": ["A"]}), "price.xlsx"

    runtime = ExportRuntime(
        prepare_export=prepare,
        read_consolidated_df=lambda _path: None,
        apply_visibility_filter=lambda frame, _path: frame,
        apply_keep_lowest_price_per_onliner_id=lambda frame: frame,
        apply_duplicate_id_filter=lambda frame, _suppliers: frame,
        apply_only_pc_filter=lambda frame, _suppliers: frame,
        has_consolidated_data=lambda _path: True,
    )
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda _item: runtime.prepare(
                    "session",
                    {"name": "A"},
                    revision_token=("r", 1),
                ),
                range(6),
            )
        )

    assert len(calls) == 1
    assert [frame.at[0, "Название"] for frame, _name in results] == ["A"] * 6


def test_export_runtime_caches_immutable_artifact():
    calls = []
    render_calls = []
    runtime = _runtime(calls)

    def render(dataframe):
        render_calls.append(True)
        return str(dataframe.at[0, "Название"]).encode()

    first = runtime.build_artifact(
        "session",
        {"name": "A"},
        revision_token=("r", 1),
        artifact_key="xlsx",
        builder=render,
    )
    second = runtime.build_artifact(
        "session",
        {"name": "A"},
        revision_token=("r", 1),
        artifact_key="xlsx",
        builder=render,
    )

    assert first == second == (b"A", "price.xlsx")
    assert len(calls) == 1
    assert len(render_calls) == 1
