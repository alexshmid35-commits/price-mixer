import pandas as pd

from price_mixer.services.review_queue_runtime import ReviewQueueRuntime


def _normalize(value):
    return str(value or "").strip().casefold()


def _runtime(frame, queue, *, manual=None, session_dir="session"):
    saved = {}
    journal = []

    runtime = ReviewQueueRuntime(
        get_active_session_dir=lambda: session_dir,
        load_review_queue=lambda: {
            key: dict(value) for key, value in queue.items()
        },
        save_review_queue=lambda value: saved.update(
            queue={key: dict(item) for key, item in value.items()}
        ),
        read_consolidated_json_fast_df=lambda _path: frame.copy(),
        write_consolidated_json=lambda value, _path: saved.update(
            frame=value.copy()
        ),
        write_consolidated_df_background=lambda *_args, **_kwargs: None,
        load_manual_id_bindings=lambda: dict(manual or {}),
        save_manual_id_bindings=lambda value: saved.update(
            manual={key: dict(item) for key, item in value.items()}
        ),
        append_id_change_journal=journal.append,
        normalize_name_key=_normalize,
        normalize_onliner_id=lambda value: str(value or "").strip(),
        manual_binding_scoped_key=lambda key, supplier: (
            f"supplier:{supplier.casefold()}:{key}"
        ),
        clock=lambda: 123,
    )
    return runtime, saved, journal


def test_runtime_list_removes_resolved_entry_without_crossing_suppliers():
    frame = pd.DataFrame(
        [
            {
                "Поставщик": "Tradex",
                "Название": "Same Product",
                "OnlinerID": "111",
            },
            {
                "Поставщик": "N-Tech",
                "Название": "Same Product",
                "OnlinerID": "",
            },
        ]
    )
    queue = {
        "supplier:tradex:same product": {
            "match_name_key": "same product",
            "supplier": "Tradex",
        },
        "supplier:ntech:same product": {
            "match_name_key": "same product",
            "supplier": "N-Tech",
        },
    }
    runtime, saved, _journal = _runtime(frame, queue)

    payload = runtime.list()

    assert [item["name_key"] for item in payload["items"]] == [
        "supplier:ntech:same product"
    ]
    assert set(saved["queue"]) == {"supplier:ntech:same product"}


def test_runtime_pick_updates_only_queue_entry_supplier_and_persists_binding():
    product_name = "Видеокарта ASUS"
    frame = pd.DataFrame(
        [
            {
                "Поставщик": "Tradex",
                "Название": product_name,
                "OnlinerID": "",
                "Ссылка": "",
            },
            {
                "Поставщик": "N-Tech",
                "Название": product_name,
                "OnlinerID": "",
                "Ссылка": "",
            },
        ]
    )
    queue = {
        "supplier:tradex:видеокарта asus": {
            "name": product_name,
            "match_name_key": "видеокарта asus",
            "supplier": "Tradex",
        }
    }
    runtime, saved, journal = _runtime(frame, queue)

    result = runtime.pick(
        {
            "name_key": "supplier:tradex:видеокарта asus",
            "onliner_id": "4986332",
            "url": "https://catalog.onliner.by/videocard/4986332",
        }
    )

    assert result == {"status": "ok", "remaining": 0}
    assert saved["manual"]["supplier:tradex:видеокарта asus"] == {
        "id": "4986332",
        "url": "https://catalog.onliner.by/videocard/4986332",
        "suppliers": ["Tradex"],
    }
    assert saved["frame"].at[0, "OnlinerID"] == "4986332"
    assert saved["frame"].at[1, "OnlinerID"] == ""
    assert saved["queue"] == {}
    assert journal[0]["ts"] == 123


def test_runtime_pick_conflict_keeps_queue_and_manual_bindings_unchanged():
    frame = pd.DataFrame(
        [
            {
                "Поставщик": "Tradex",
                "Название": "Other Product",
                "OnlinerID": "111",
            }
        ]
    )
    queue = {
        "supplier:tradex:new product": {
            "name": "New Product",
            "match_name_key": "new product",
            "supplier": "Tradex",
        }
    }
    runtime, saved, journal = _runtime(frame, queue)

    payload, status = runtime.pick(
        {
            "name_key": "supplier:tradex:new product",
            "onliner_id": "111",
        }
    )

    assert status == 409
    assert payload["status"] == "error"
    assert saved == {}
    assert journal == []


def test_runtime_clear_replaces_queue_with_empty_mapping():
    runtime, saved, _journal = _runtime(pd.DataFrame(), {"item": {}})

    assert runtime.clear() == {"status": "ok"}
    assert saved["queue"] == {}
