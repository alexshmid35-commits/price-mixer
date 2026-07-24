"""Unit tests for safe JSON state storage."""

import json
from concurrent.futures import ThreadPoolExecutor

from price_mixer.state_store import append_list_item, load_dict, load_json, load_list, save_dict, save_list


def test_load_json_returns_default_for_missing_or_corrupt_file(tmp_path):
    missing = tmp_path / "missing.json"
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not-json", encoding="utf-8")

    assert load_json(missing, default={"ok": True}, expected_type=dict) == {"ok": True}
    assert load_json(corrupt, default=[], expected_type=list) == []


def test_load_json_rejects_unexpected_type(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    assert load_dict(path) == {}
    assert load_list(path) == [1, 2, 3]


def test_save_dict_writes_atomically_and_removes_tmp(tmp_path):
    path = tmp_path / "nested" / "state.json"

    save_dict(path, {"hello": "мир"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"hello": "мир"}
    assert not list(path.parent.glob(path.name + ".*.tmp"))


def test_save_dict_supports_parallel_atomic_writes(tmp_path):
    path = tmp_path / "state.json"
    payloads = [{"value": index} for index in range(40)]

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(lambda payload: save_dict(path, payload), payloads))

    assert json.loads(path.read_text(encoding="utf-8")) in payloads
    assert not list(tmp_path.glob(path.name + ".*.tmp"))


def test_save_list_applies_limit_from_tail(tmp_path):
    path = tmp_path / "history.json"

    save_list(path, [1, 2, 3, 4], limit=2)

    assert json.loads(path.read_text(encoding="utf-8")) == [3, 4]


def test_append_list_item_sorts_and_limits(tmp_path):
    path = tmp_path / "history.json"
    save_list(path, [{"ts": 1}, {"ts": 3}])

    rows = append_list_item(path, {"ts": 2}, limit=2, sort_key=lambda item: item["ts"], reverse=True)

    assert rows == [{"ts": 3}, {"ts": 2}, {"ts": 1}]
    assert load_list(path) == [{"ts": 2}, {"ts": 1}]


def test_append_list_item_parallel_preserves_all_items(tmp_path):
    path = tmp_path / "journal.json"

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(lambda value: append_list_item(path, value), range(80)))

    assert sorted(load_list(path)) == list(range(80))
