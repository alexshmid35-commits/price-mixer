import threading

import pandas as pd

from price_mixer.services.category_management_runtime import (
    CategoryManagementRuntime,
)


def _runtime(*, session_dir="session", visibility=None):
    calls = {}
    frame = pd.DataFrame(
        {
            "Название": ["Kingston SSD"],
            "Категория": ["SSD"],
            "Цена": [100],
            "OnlinerID": ["123"],
        }
    )

    def update(payload, current, *, category_sort_key):
        calls["payload"] = dict(payload)
        calls["current"] = dict(current)
        calls["sort_key"] = category_sort_key
        if not payload.get("categories"):
            return {"status": "error", "message": "Категории не выбраны"}, current, 400
        return (
            {"status": "ok", "supplier": "__all__"},
            {"__all__": sorted(payload["categories"], key=category_sort_key)},
            200,
        )

    runtime = CategoryManagementRuntime(
        get_active_session_dir=lambda: session_dir,
        canonical_supplier_name=lambda value: {
            "ntech": "N-Tech",
        }.get(str(value or "").casefold(), str(value or "")),
        load_visibility_map=lambda path: calls.update(load_path=path)
        or dict(visibility or {}),
        save_visibility_map=lambda path, value: calls.update(
            save_path=path,
            saved=dict(value),
        ),
        update_category_visibility=update,
        category_sort_key=lambda value: str(value).casefold(),
        visibility_lock=threading.RLock(),
        has_consolidated_session_file=lambda path: calls.update(
            has_path=path
        )
        or True,
        consolidated_json_df=lambda path, **kwargs: calls.update(
            consolidated_path=path,
            consolidated_kwargs=kwargs,
        )
        or frame.copy(),
        read_consolidated_json_fast_df=lambda path: calls.update(
            read_fast_path=path
        )
        or frame.copy(),
        read_consolidated_df=lambda path: calls.update(read_path=path)
        or frame.copy(),
        ensure_category_column=lambda value, *args: calls.update(
            ensured=True,
            ensure_args=args,
        )
        or value,
        apply_visibility_filter=lambda value, path: calls.update(
            visibility_path=path
        )
        or value,
        parse_markup_request=lambda payload: (
            (
                {
                    "categories": list(payload.get("categories", [])),
                    "percent": float(payload.get("percent", 0)),
                },
                "",
            )
            if payload.get("categories")
            else (None, "Категории не выбраны")
        ),
        apply_markup_to_df=lambda value, config, **kwargs: (
            calls.update(markup_config=dict(config), markup_kwargs=kwargs)
            or value.assign(РРЦ=120),
            {"status": "ok", "updated": len(value)},
        ),
        markup_preview_payload=lambda value, payload, **kwargs: calls.update(
            preview_payload=dict(payload),
            preview_kwargs=kwargs,
            preview_rows=len(value),
        )
        or {"items": [{"name": value.iloc[0]["Название"]}]},
        row_category=lambda row: row.get("Категория", ""),
        normalize_onliner_id=lambda value: str(value or "").strip(),
        get_onliner_market_stats_bulk=lambda *_args, **_kwargs: {},
        write_consolidated_json=lambda value, path: calls.update(
            written=value.copy(),
            write_path=path,
        ),
        write_consolidated_df_background=lambda *args, **kwargs: calls.update(
            background_args=args,
            background_kwargs=kwargs,
        ),
        load_category_markups=lambda: {"RAM": {"percent": 10}},
        save_category_markups=lambda value: calls.update(
            saved_markups=dict(value)
        ),
        update_category_markups=lambda current, config: {
            **current,
            **{
                category: {"percent": config["percent"]}
                for category in config["categories"]
            },
        },
        load_category_overrides=lambda: {
            "name:existing": "Старая категория"
        },
        save_category_overrides=lambda value: calls.update(
            saved_overrides=dict(value)
        ),
        load_manual_category_overrides=lambda: {},
        save_manual_category_overrides=lambda value: calls.update(
            saved_manual_overrides=dict(value)
        ),
        category_override_items_payload=lambda value, **kwargs: calls.update(
            override_items_rows=len(value),
            override_items_kwargs=kwargs,
        )
        or {"items": [{"name": value.iloc[0]["Название"]}]},
        apply_category_override_to_df=lambda value, payload, **kwargs: (
            calls.update(
                override_payload=dict(payload),
                override_kwargs=kwargs,
            )
            or (
                {"status": "ok"},
                value.assign(Категория=payload["target_category"])
                if value is not None
                else value,
                {
                    **kwargs["overrides"],
                    "name:kingston": payload["target_category"],
                },
                1 if value is not None else 0,
            )
        ),
        canonical_ui_category_name=lambda value: str(value or "").strip().title(),
        build_item_category_key=lambda row: f"name:{row['Название']}",
        build_item_category_keys=lambda row: [f"name:{row['Название']}"],
        infer_category=lambda name: "SSD",
        write_consolidated_df=lambda path, value: calls.update(
            written_df_path=path,
            written_df=value.copy(),
        ),
        override_lock=threading.RLock(),
        category_preview_items_payload=lambda value, payload, **kwargs: (
            calls.update(
                category_preview_payload=dict(payload),
                category_preview_kwargs=kwargs,
                category_preview_rows=len(value),
            )
            or {
                "items": [{"name": value.iloc[0]["Название"]}],
                "preview_row_count": len(value),
            }
        ),
        load_market_cache=lambda: {"111": {"min": 90}},
        get_market_stats_from_cache_only=lambda oid, **_kwargs: {
            "min": 90
        }
        if oid == "111"
        else {},
    )
    return runtime, calls


def test_visibility_rejects_missing_session_without_loading_state():
    runtime, calls = _runtime(session_dir=None)

    result = runtime.visibility(
        {"supplier": "ntech", "categories": ["SSD"], "hidden": True}
    )

    assert result == (
        {"status": "error", "message": "Нет активной сессии"},
        400,
    )
    assert calls == {}


def test_visibility_canonicalizes_supplier_and_saves_successful_update():
    runtime, calls = _runtime(visibility={"__all__": ["RAM"]})

    result = runtime.visibility(
        {
            "supplier": "ntech",
            "categories": ["SSD", "Мышь"],
            "hidden": True,
        }
    )

    assert result == ({"status": "ok", "supplier": "__all__"}, 200)
    assert calls["payload"]["supplier"] == "N-Tech"
    assert calls["current"] == {"__all__": ["RAM"]}
    assert calls["load_path"] == "session"
    assert calls["save_path"] == "session"
    assert calls["saved"] == {"__all__": ["SSD", "Мышь"]}


def test_visibility_does_not_save_invalid_update():
    runtime, calls = _runtime(visibility={"__all__": ["RAM"]})

    result = runtime.visibility({"supplier": "ntech", "categories": []})

    assert result[1] == 400
    assert result[0]["status"] == "error"
    assert "saved" not in calls


def test_apply_markup_validates_updates_and_persists_result():
    runtime, calls = _runtime()

    result = runtime.apply_markup(
        {"categories": ["SSD"], "percent": "20"}
    )

    assert result == {"status": "ok", "updated": 1}
    assert calls["read_fast_path"] == "session"
    assert calls["markup_config"] == {
        "categories": ["SSD"],
        "percent": 20.0,
    }
    assert list(calls["written"]["РРЦ"]) == [120]
    assert calls["write_path"].name == "consolidated.json"
    assert calls["saved_markups"]["SSD"] == {"percent": 20.0}
    assert calls["background_args"][0] == "session"
    assert calls["background_kwargs"] == {"label": "apply-markup"}


def test_apply_markup_stops_before_dataframe_read_on_invalid_payload():
    runtime, calls = _runtime()

    result = runtime.apply_markup({"categories": []})

    assert result == {
        "status": "error",
        "message": "Категории не выбраны",
    }
    assert "read_fast_path" not in calls
    assert "saved_markups" not in calls


def test_markup_preview_uses_prepared_visible_dataframe():
    runtime, calls = _runtime()

    result = runtime.markup_preview({"categories": ["SSD"]})

    assert result == {"items": [{"name": "Kingston SSD"}]}
    assert calls["consolidated_path"] == "session"
    assert calls["consolidated_kwargs"] == {"apply_visibility": True}
    assert calls["preview_payload"] == {"categories": ["SSD"]}
    assert "read_path" not in calls


def test_markup_preview_falls_back_to_read_ensure_and_visibility():
    runtime, calls = _runtime()
    object.__setattr__(
        runtime,
        "consolidated_json_df",
        lambda _path, **_kwargs: None,
    )

    result = runtime.markup_preview({"categories": ["SSD"]})

    assert result["items"][0]["name"] == "Kingston SSD"
    assert calls["read_path"] == "session"
    assert calls["ensured"] is True
    assert calls["visibility_path"] == "session"


def test_category_override_items_builds_payload_from_unfiltered_frame():
    runtime, calls = _runtime()

    result = runtime.category_override_items(query="king", limit="25")

    assert result == {"items": [{"name": "Kingston SSD"}]}
    assert calls["consolidated_kwargs"] == {"apply_visibility": False}
    kwargs = calls["override_items_kwargs"]
    assert kwargs["query"] == "king"
    assert kwargs["limit"] == "25"
    assert kwargs["overrides"] == {
        "name:existing": "Старая категория"
    }
    assert kwargs["infer_category"]("Kingston SSD") == "SSD"


def test_category_override_set_normalizes_writes_and_saves_both_states():
    runtime, calls = _runtime()

    result = runtime.category_override_set(
        {
            "item_key": "name:kingston",
            "target_category": "  накопители  ",
        }
    )

    assert result == {"status": "ok"}
    assert calls["override_payload"]["target_category"] == "Накопители"
    assert calls["ensure_args"] == (
        {"name:existing": "Старая категория"},
    )
    assert list(calls["written_df"]["Категория"]) == ["Накопители"]
    assert calls["written_df_path"] == "session"
    assert calls["write_path"].name == "consolidated.json"
    assert calls["saved_overrides"]["name:kingston"] == "Накопители"
    assert calls["saved_manual_overrides"] == {}


def test_category_override_set_does_not_save_failed_result():
    runtime, calls = _runtime()
    object.__setattr__(
        runtime,
        "apply_category_override_to_df",
        lambda value, payload, **kwargs: (
            {"status": "error", "message": "Товар не выбран"},
            value,
            kwargs["overrides"],
            0,
        ),
    )

    result = runtime.category_override_set(
        {"target_category": "SSD"}
    )

    assert result == {
        "status": "error",
        "message": "Товар не выбран",
    }
    assert "saved_overrides" not in calls
    assert "saved_manual_overrides" not in calls


def test_category_preview_items_uses_visible_frame_and_market_dependencies():
    runtime, calls = _runtime()

    result = runtime.category_preview_items(
        {"categories": ["SSD"], "with_market": True}
    )

    assert result == {
        "items": [{"name": "Kingston SSD"}],
        "preview_row_count": 1,
    }
    assert calls["consolidated_kwargs"] == {"apply_visibility": True}
    assert calls["category_preview_payload"] == {
        "categories": ["SSD"],
        "with_market": True,
    }
    kwargs = calls["category_preview_kwargs"]
    assert kwargs["overrides"] == {
        "name:existing": "Старая категория"
    }
    assert kwargs["load_market_cache"]() == {
        "111": {"min": 90}
    }
    assert kwargs["get_market_stats_from_cache_only"]("111") == {
        "min": 90
    }


def test_category_preview_items_returns_empty_without_session():
    runtime, calls = _runtime(session_dir=None)

    assert runtime.category_preview_items(
        {"categories": ["SSD"]}
    ) == {"items": []}
    assert "consolidated_kwargs" not in calls
    assert "category_preview_payload" not in calls
