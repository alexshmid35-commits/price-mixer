"""Registry for independently testable category matching plugins."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewMatchingPlugin:
    key: str
    aliases: tuple[str, ...]
    finder: Callable
    key_builder: Callable | None = None
    detector: Callable | None = None


class ReviewMatchingEngine:
    def __init__(self, plugins=()):
        self._plugins = {}
        for plugin in plugins:
            self.register(plugin)

    def register(self, plugin):
        if not isinstance(plugin, ReviewMatchingPlugin):
            raise TypeError("plugin must be ReviewMatchingPlugin")
        for alias in (plugin.key, *plugin.aliases):
            normalized = self._normalize_category(alias)
            if normalized:
                self._plugins[normalized] = plugin
        return plugin

    def resolve(self, category):
        return self._plugins.get(self._normalize_category(category))

    def find(self, category, product_name, *, top_n=5, **dependencies):
        plugin = self.resolve(category)
        if plugin is None:
            return []
        return plugin.finder(product_name, top_n=top_n, **dependencies)

    def keys(self):
        return tuple(sorted({plugin.key for plugin in self._plugins.values()}))

    @staticmethod
    def _normalize_category(value):
        return " ".join(str(value or "").strip().casefold().replace("ё", "е").split())
