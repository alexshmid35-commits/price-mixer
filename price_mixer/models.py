"""Core domain models (dataclasses)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SupplierFile:
    """Uploaded supplier price file."""
    filepath: str
    display_name: str
    supplier_name: str
    session_id: str | None = None


@dataclass
class ParsedRow:
    """Single row after parsing a supplier file."""
    supplier: str
    name: str
    price: float
    warranty: str = ""
    onliner_id: str | None = None
    onliner_name: str | None = None
    article: str | None = None
    quantity: int | None = None
    status: str | None = None
    supplier_code: str | None = None
    delivery_days: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsolidatedRow:
    """Row in the final consolidated price list."""
    onliner_id: str | None
    name: str
    price: float
    supplier: str
    warranty: str
    delivery_days: int | None = None
    category: str | None = None
    url: str | None = None
    rrc: float | None = None
    no_discount_price: float | None = None
    sources: list[ParsedRow] = field(default_factory=list)


@dataclass
class OnlinerProduct:
    """Cached Onliner catalog product."""
    onliner_id: str
    name: str
    url: str = ""
    source: str = ""
    updated_at: int = 0


@dataclass
class CategoryMarkup:
    """Markup configuration for a category."""
    category: str
    percent: float = 0.0
    threshold: float = 0.0
    min_profit: float = 0.0
    no_discount_percent: float = 0.0


@dataclass
class ManualIdBinding:
    """User-confirmed mapping name_key -> onliner_id."""
    name_key: str
    onliner_id: str
    url: str = ""
    confirmed_at: datetime | None = None
