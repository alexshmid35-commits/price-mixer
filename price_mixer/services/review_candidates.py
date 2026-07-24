"""Compatibility facade for category-specific review matching plugins."""

from price_mixer.services import review_matching as _matching

__all__ = _matching.__all__
globals().update({name: getattr(_matching, name) for name in __all__})
