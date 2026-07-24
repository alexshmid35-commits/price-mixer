from price_mixer.services.static_assets import StaticAssetRegistry


def test_static_asset_version_changes_with_content(tmp_path):
    asset = tmp_path / "js" / "app.js"
    asset.parent.mkdir()
    asset.write_text("one", encoding="utf-8")
    registry = StaticAssetRegistry(tmp_path)

    first = registry.version("js/app.js")
    asset.write_text("two", encoding="utf-8")
    second = registry.version("js/app.js")

    assert len(first) == 12
    assert first != second
    assert registry.is_current("js/app.js", second)
    assert not registry.is_current("js/app.js", first)


def test_static_asset_registry_rejects_path_traversal(tmp_path):
    registry = StaticAssetRegistry(tmp_path)

    try:
        registry.version("../secret")
    except ValueError as exc:
        assert "invalid static asset path" in str(exc)
    else:
        raise AssertionError("path traversal must be rejected")
