"""Core domain models (dataclasses)."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class SupplierFile:
    """Uploaded supplier price file."""
    filepath: str
    display_name: str
    supplier_name: str
    session_id: Optional[str] = None


@dataclass
class ParsedRow:
    """Single row after parsing a supplier file."""
    supplier: str
    name: str
    price: float
    warranty: str = ""
    onliner_id: Optional[str] = None
    onliner_name: Optional[str] = None
    article: Optional[str] = None
    quantity: Optional[int] = None
    status: Optional[str] = None
    supplier_code: Optional[str] = None
    delivery_days: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsolidatedRow:
    """Row in the final consolidated price list."""
    onliner_id: Optional[str]
    name: str
    price: float
    supplier: str
    warranty: str
    delivery_days: Optional[int] = None
    category: Optional[str] = None
    url: Optional[str] = None
    rrc: Optional[float] = None
    no_discount_price: Optional[float] = None
    sources: List[ParsedRow] = field(default_factory=list)


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
    confirmed_at: Optional[datetime] = None
