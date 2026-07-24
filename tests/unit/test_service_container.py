from concurrent.futures import ThreadPoolExecutor

from price_mixer.services.service_container import ServiceContainer


def test_service_container_creates_single_instance_across_threads():
    container = ServiceContainer()
    calls = []

    def factory():
        calls.append(1)
        return object()

    with ThreadPoolExecutor(max_workers=8) as pool:
        instances = list(
            pool.map(
                lambda _value: container.get_or_create("runtime", factory),
                range(40),
            )
        )

    assert len(calls) == 1
    assert len({id(instance) for instance in instances}) == 1
    assert container.names() == ("runtime",)


def test_service_container_can_replace_and_reset_services():
    container = ServiceContainer()

    assert container.set("runtime", "first") == "first"
    assert container.get_or_create("runtime", lambda: "second") == "first"

    container.reset("runtime")
    assert container.get_or_create("runtime", lambda: "second") == "second"

    container.reset()
    assert container.names() == ()
