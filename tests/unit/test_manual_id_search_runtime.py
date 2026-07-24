from price_mixer.services.manual_id_search_runtime import ManualIdSearchRuntime


class Handler:
    def __init__(self, candidates, *, target=True):
        self.candidates = candidates
        self.target = target

    def is_target(self, *_args):
        return self.target

    def build_row_result(self, *_args):
        return {"queue_item": {"candidates": self.candidates}}


def runtime(**overrides):
    values = {
        "normalize_catalog_category_name": lambda value: str(value),
        "infer_category": lambda name: ("Мышь" if "mouse" in name.casefold() else "Монитор"),
        "normalized_category_from_name": lambda _name: "",
        "is_iven_pc_name": lambda name: name.startswith("IVEN PC"),
        "is_tgpc_pc_name": lambda name: name.startswith("TGPC"),
        "is_iven_laptop_name": lambda name, _category: name.startswith("Ноутбук IVEN"),
        "search_iven_pc_candidates": lambda name, limit: [{"source": "iven", "name": name}][:limit],
        "search_tgpc_pc_candidates": lambda name, limit: [{"source": "tgpc", "name": name}][:limit],
        "supplier_laptop_candidates": (lambda name, **_kwargs: [{"source": "laptop", "name": name}]),
        "is_iven_laptop_candidate": lambda *_args: True,
        "get_review_handler": lambda _mode: Handler(
            [
                {"name": "Monitor one"},
                {"name": "Monitor two"},
            ]
        ),
        "clock": lambda: 10,
    }
    values.update(overrides)
    return ManualIdSearchRuntime(**values)


def test_specialized_pc_and_laptop_paths_are_preserved():
    search = runtime()

    assert search.candidates("IVEN PC One")[0]["source"] == "iven"
    assert search.candidates("TGPC One")[0]["source"] == "tgpc"
    assert search.candidates("Ноутбук IVEN One")[0]["source"] == "laptop"


def test_review_handler_candidates_honor_limit():
    candidates = runtime().candidates("Display", category="Монитор", top_n=1)

    assert candidates == [{"name": "Monitor one"}]


def test_peripheral_candidates_are_filtered_by_exact_category():
    search = runtime(
        get_review_handler=lambda _mode: Handler(
            [
                {"name": "mouse exact"},
                {"name": "Monitor wrong"},
            ]
        ),
    )

    assert search.candidates("Mouse", category="Мышь") == [{"name": "mouse exact"}]


def test_unknown_or_rejected_category_returns_no_candidates():
    assert runtime().candidates("Unknown", category="Unknown") == []
    rejected = runtime(get_review_handler=lambda _mode: Handler([], target=False))
    assert rejected.candidates("Display", category="Монитор") == []
