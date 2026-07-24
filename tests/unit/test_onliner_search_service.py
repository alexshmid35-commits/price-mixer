import threading

from price_mixer.services import onliner_search as svc


class FakeResponse:
    def __init__(self, payload=None, ok=True, status_code=200):
        self._payload = payload or {}
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _search_candidate_kwargs(api_get, query_cache=None, settings=None, rules=None):
    return {
        "load_settings": lambda: settings or {"no_id_search": {}},
        "get_category_rules": lambda app_settings: rules or {},
        "coerce_bool": _coerce_bool,
        "api_get": api_get,
        "b2b_search_candidates": lambda name, category_name="", limit=24: [],
        "extract_article": lambda name: "",
        "name_tokens": lambda name: [token for token in str(name).lower().split() if token],
        "preferred_brand_token": lambda name: str(name).split()[0] if str(name).split() else "",
        "normalize_compact_name": lambda text: "".join(ch for ch in str(text).lower() if ch.isalnum()),
        "priority_model_queries": lambda name: [],
        "tgpc_pc_code_queries": lambda name: [],
        "is_tgpc_pc_name": lambda name: False,
        "extract_tgpc_pc_code": lambda name: "",
        "model_hint_tokens": lambda name: set(),
        "paren_chunks": lambda name: [],
        "article_like_tokens": lambda name: set(),
        "token_family_match": lambda left, right: set(left or set()).intersection(set(right or set())),
        "strict_candidate_allowed": lambda local, candidate: (True, "ok"),
        "calc_name_match": lambda local, candidate: {"score": 0.82, "match": True, "reason": "test"},
        "query_cache": query_cache if query_cache is not None else {},
        "query_cache_lock": threading.RLock(),
        "query_cache_ttl": 3600,
        "query_cache_version": "test",
        "now_fn": lambda: 100,
    }


def test_category_path_hints_returns_known_catalog_paths():
    assert svc.category_path_hints("Процессор") == ["/cpu/"]
    assert svc.category_path_hints("Блок питания") == ["/powersupply/", "/psu/"]
    assert svc.category_path_hints("unknown") == []


def test_search_product_by_name_uses_best_api_match():
    calls = []

    def fake_api_get(url, **kwargs):
        calls.append(url)
        return FakeResponse({
            "products": [
                {"id": "1", "full_name": "weak", "html_url": "https://weak.test"},
                {"id": "2", "full_name": "strong product", "html_url": "https://strong.test"},
            ]
        })

    def calc_match(local, candidate):
        return {"score": 0.5, "match": False} if candidate == "weak" else {"score": 0.9, "match": True}

    result = svc.search_product_by_name(
        "RTX 4070",
        api_get=fake_api_get,
        extract_article=lambda name: "4070",
        name_tokens=lambda name: ["rtx", "4070"],
        calc_name_match=calc_match,
    )

    assert result == {
        "id": "2",
        "name": "strong product",
        "url": "https://strong.test",
        "score": 0.9,
        "source": "search_name",
    }
    assert "query=4070" in calls[0]


def test_search_product_by_name_deep_verifies_candidate_and_saves_api_cache():
    cache = {}
    saved = []

    result = svc.search_product_by_name_deep(
        "Local GPU AX123",
        category_name="Видеокарта",
        search_by_name=lambda name: {"id": "", "name": "", "url": "", "score": 0.2, "source": "not_found"},
        search_candidates=lambda *args, **kwargs: [{"id": "55", "name": "Candidate", "url": "https://candidate.test"}],
        fetch_product_info=lambda cid, **kwargs: {
            "name": "Local GPU AX123",
            "url": "https://verified.test",
            "source": "api",
        },
        load_product_cache=lambda: cache,
        save_product_cache=lambda payload: saved.append(dict(payload)),
        calc_name_match=lambda local, remote: {"score": 0.7, "match": True},
        article_like_tokens=lambda name: {"ax123"} if "AX123" in name else set(),
    )

    assert result == {
        "id": "55",
        "name": "Local GPU AX123",
        "url": "https://verified.test",
        "score": 0.86,
        "source": "search_name_deep",
    }
    assert saved == [cache]


def test_search_candidates_merges_b2b_api_and_caches_result():
    query_cache = {}
    calls = []

    def fake_api_get(url, **kwargs):
        calls.append(url)
        return FakeResponse({
            "products": [
                {"id": "1", "full_name": "API product", "html_url": "https://catalog.onliner.by/ssd/api"},
                {"id": "2", "full_name": "duplicate b2b", "html_url": "https://catalog.onliner.by/ssd/dup"},
            ]
        })

    kwargs = _search_candidate_kwargs(fake_api_get, query_cache=query_cache)
    kwargs["b2b_search_candidates"] = lambda name, category_name="", limit=24: [
        {"id": "2", "name": "duplicate b2b", "url": "https://b2b.test", "score": 0.91, "source": "b2b"}
    ]

    result = svc.search_candidates("API product", category_name="SSD", limit=10, **kwargs)
    cached = svc.search_candidates("API product", category_name="SSD", limit=10, **kwargs)

    assert result == [
        {"id": "2", "name": "duplicate b2b", "url": "https://b2b.test", "score": 0.91, "source": "b2b", "reason": ""},
        {"id": "1", "name": "API product", "url": "https://catalog.onliner.by/ssd/api", "score": 0.82, "source": "api", "reason": "test"},
    ]
    assert cached == result
    assert len(calls) == 1


def test_search_candidates_respects_required_category_hint():
    def fake_api_get(url, **kwargs):
        return FakeResponse({
            "products": [
                {"id": "1", "full_name": "API product", "html_url": "https://catalog.onliner.by/videocard/api"},
            ]
        })

    result = svc.search_candidates(
        "API product",
        category_name="SSD",
        limit=10,
        **_search_candidate_kwargs(
            fake_api_get,
            settings={"no_id_search": {"require_category_hint": True}},
        ),
    )

    assert result == []
