"""Unit tests for price_mixer.cache."""

import json
import time
from pathlib import Path

import pytest

from price_mixer.cache import JsonCache


def test_cache_set_get(tmp_path):
    c = JsonCache(tmp_path / "test_cache.json")
    c.set("key1", {"a": 1})
    assert c.get("key1") == {"a": 1}


def test_cache_get_missing(tmp_path):
    c = JsonCache(tmp_path / "test_cache.json")
    assert c.get("missing", "default") == "default"


def test_cache_ttl_expires(tmp_path):
    c = JsonCache(tmp_path / "test_cache.json", ttl_seconds=1)
    c.set("key", {"val": 1}, with_timestamp=True)
    assert c.get("key") is not None
    time.sleep(1.1)
    assert c.get("key") is None


def test_cache_persistence(tmp_path):
    path = tmp_path / "persist.json"
    c1 = JsonCache(path)
    c1.set("x", 42)
    c2 = JsonCache(path)
    assert c2.get("x") == 42
