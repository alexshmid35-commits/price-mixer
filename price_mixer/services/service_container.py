"""Thread-safe lazy dependency container for application services."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any, TypeVar, cast

T = TypeVar("T")


class ServiceContainer:
    """Create process-local services once without module-specific globals."""

    def __init__(self) -> None:
        self._instances: dict[str, Any] = {}
        self._lock = RLock()

    def get_or_create(self, name: str, factory: Callable[[], T]) -> T:
        key = str(name or "").strip()
        if not key:
            raise ValueError("service name is required")
        instance = self._instances.get(key)
        if instance is not None:
            return cast(T, instance)
        with self._lock:
            instance = self._instances.get(key)
            if instance is None:
                instance = factory()
                self._instances[key] = instance
        return cast(T, instance)

    def set(self, name: str, instance: T) -> T:
        key = str(name or "").strip()
        if not key:
            raise ValueError("service name is required")
        with self._lock:
            self._instances[key] = instance
        return instance

    def reset(self, name: str | None = None) -> None:
        with self._lock:
            if name is None:
                self._instances.clear()
            else:
                self._instances.pop(str(name), None)

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._instances))
