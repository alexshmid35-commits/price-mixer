from pathlib import Path

from price_mixer.services.runtime_hygiene import (
    ARTIFACT_POLICIES,
    CACHE_FILENAMES,
    STATE_FILENAMES,
    classify_project_artifact,
    collect_project_hygiene,
    get_artifact_policy,
)


ROOT = Path(__file__).resolve().parents[2]


def test_classify_project_artifact_groups_known_runtime_state_and_secrets(tmp_path):
    paths = {
        "secret": tmp_path / ".env",
        "service_account": tmp_path / "ai2025-demo.json",
        "state": tmp_path / "manual_id_bindings.json",
        "cache": tmp_path / "onliner_cache.json",
        "runtime": tmp_path / "server.pid",
        "data": tmp_path / "onliner_products.db",
        "backup": tmp_path / "manual_id_bindings.before_fix.json",
        "code": tmp_path / "app.py",
    }
    for path in paths.values():
        path.write_text("x", encoding="utf-8")

    assert classify_project_artifact(paths["secret"], tmp_path) == "secrets"
    assert classify_project_artifact(paths["service_account"], tmp_path) == "secrets"
    assert classify_project_artifact(paths["state"], tmp_path) == "state"
    assert classify_project_artifact(paths["cache"], tmp_path) == "cache"
    assert classify_project_artifact(paths["runtime"], tmp_path) == "runtime"
    assert classify_project_artifact(paths["data"], tmp_path) == "data"
    assert classify_project_artifact(paths["backup"], tmp_path) == "backup"
    assert classify_project_artifact(paths["code"], tmp_path) is None


def test_collect_project_hygiene_is_non_destructive_and_limited(tmp_path):
    (tmp_path / ".env").write_text("secret", encoding="utf-8")
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "session.xlsx").write_text("data", encoding="utf-8")
    (tmp_path / "onliner_cache.json").write_text("{}", encoding="utf-8")
    (tmp_path / "server.log").write_text("log", encoding="utf-8")

    result = collect_project_hygiene(tmp_path, max_items_per_group=10)

    assert result["secrets"] == [".env"]
    runtime_items = set(result["runtime"])
    assert "uploads" in runtime_items
    assert "uploads/session.xlsx" in runtime_items
    assert "server.log" in runtime_items
    assert result["cache"] == ["onliner_cache.json"]
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "uploads" / "session.xlsx").exists()


def test_runtime_directory_wins_over_nested_state_or_data_names(tmp_path):
    session_dir = tmp_path / "uploads" / "session"
    session_dir.mkdir(parents=True)
    nested_state = session_dir / "manual_id_bindings.json"
    nested_data = session_dir / "consolidated_price.xlsx"
    nested_state.write_text("{}", encoding="utf-8")
    nested_data.write_text("x", encoding="utf-8")

    assert classify_project_artifact(nested_state, tmp_path) == "runtime"
    assert classify_project_artifact(nested_data, tmp_path) == "runtime"


def test_declared_layout_separates_durable_state_from_rebuildable_cache():
    assert "app_settings.json" in STATE_FILENAMES
    assert "manual_id_bindings.json" in STATE_FILENAMES
    assert "id_review_queue.json" in STATE_FILENAMES
    assert "onliner_cache.json" not in STATE_FILENAMES
    assert CACHE_FILENAMES == {
        "onliner_cache.json",
        "onliner_id_cache.json",
        "onliner_market_cache.json",
        "onliner_product_cache.json",
    }
    assert all(
        ARTIFACT_POLICIES[name].backup_required
        for name in STATE_FILENAMES
    )
    assert all(
        not ARTIFACT_POLICIES[name].backup_required
        for name in CACHE_FILENAMES
    )


def test_sensitive_policy_marks_secrets_and_proxy_settings(tmp_path):
    env_policy = get_artifact_policy(tmp_path / ".env.production", tmp_path)
    api_policy = get_artifact_policy(
        tmp_path / "onliner_api_settings.json",
        tmp_path,
    )

    assert env_policy.category == "secrets"
    assert env_policy.sensitive is True
    assert api_policy.category == "state"
    assert api_policy.backup_required is True
    assert api_policy.sensitive is True


def test_runtime_layout_document_covers_every_declared_artifact():
    document = (ROOT / "RUNTIME_LAYOUT.md").read_text(encoding="utf-8")

    missing = [
        name for name in ARTIFACT_POLICIES
        if f"`{name}`" not in document
    ]
    assert missing == []
