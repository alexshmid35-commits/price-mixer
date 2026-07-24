from pathlib import Path

from price_mixer.services.sorting_reparse_runtime import (
    SortingReparseRuntime,
)


class Response:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload


class Http:
    def __init__(self):
        self.posts = []

    def get(self, _url, **_kwargs):
        return Response({"ok": True, "is_running": False, "results": []})

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return Response({"ok": True, "is_running": False})


class Logger:
    def warning(self, *_args):
        return None


def runtime(rows, *, known=None, updated=None):
    http = Http()
    updated = updated if updated is not None else []
    service = SortingReparseRuntime(
        base_url="http://parser",
        project_root=Path("/project"),
        get_active_session_dir=lambda: "/session",
        correct_rows=lambda _session, **_kwargs: rows,
        normalize_onliner_id=lambda value: str(value or ""),
        is_sorting_review_category=lambda value: str(value).startswith("sort:"),
        sorting_review_prefix="sort:",
        get_categories_by_ids=lambda _ids: known or {},
        native_catalog_category_for_product=lambda value, _name: value,
        update_categories=lambda results: updated.extend(results) or len(results),
        clear_corrected_rows_cache=lambda: None,
        response_json_payload=lambda response: dict(response.payload),
        parser_error_message=str,
        logger=Logger(),
        http=http,
    )
    service.ensure_service = lambda **_kwargs: None
    service.start_monitor = lambda: None
    return service, http


def test_sorting_items_are_deduplicated_and_use_parent_category():
    rows = [
        ["1", "One", 1, "IVEN", 1, 1, 1, 1, 0, "sort:RAW"],
        ["1", "Duplicate", 1, "IVEN", 1, 1, 1, 1, 1, "sort:RAW"],
        ["2", "Ready", 1, "IVEN", 1, 1, 1, 1, 2, "Монитор"],
    ]
    service, _http = runtime(rows)

    assert service.sorting_items() == [
        {
            "onliner_id": "1",
            "name": "One",
            "parent_category": "RAW",
        }
    ]


def test_run_posts_queue_to_parser():
    rows = [["1", "One", 1, "IVEN", 1, 1, 1, 1, 0, "sort:RAW"]]
    service, http = runtime(rows)

    payload, status = service.run()

    assert status == 200
    assert payload["ok"] is True
    assert http.posts[0][1]["json"]["items"][0]["onliner_id"] == "1"


def test_empty_queue_returns_informative_error():
    service, _http = runtime([])

    payload, status = service.run()

    assert status == 400
    assert "пуста" in payload["error"]
