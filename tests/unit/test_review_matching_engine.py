from price_mixer.services.review_matching import (
    DEFAULT_REVIEW_MATCHING_ENGINE,
    ReviewMatchingEngine,
    ReviewMatchingPlugin,
)


def test_default_engine_resolves_russian_category_aliases():
    assert DEFAULT_REVIEW_MATCHING_ENGINE.resolve("Материнская плата").key == "board"
    assert DEFAULT_REVIEW_MATCHING_ENGINE.resolve("КУЛЕР").key == "cooler"
    assert DEFAULT_REVIEW_MATCHING_ENGINE.resolve("unknown") is None
    assert len(DEFAULT_REVIEW_MATCHING_ENGINE.keys()) == 12


def test_engine_delegates_to_plugin_with_dependencies():
    calls = []

    def finder(name, top_n=5, **dependencies):
        calls.append((name, top_n, dependencies))
        return [{"id": "10"}]

    engine = ReviewMatchingEngine((ReviewMatchingPlugin("demo", ("демо",), finder),))

    assert engine.find("ДЕМО", "Product", top_n=3, database="db") == [{"id": "10"}]
    assert calls == [("Product", 3, {"database": "db"})]
