"""Onliner Catalog search client (public API, no auth required)."""

import time
from typing import Any, Dict, List, Optional

import requests


class OnlinerCatalogClient:
    """Searches Onliner catalog by product name / article."""

    SEARCH_URL = "https://catalog.api.onliner.by/search/products"
    TIMEOUT = 8
    RETRY_STATUSES = {403, 408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}

    def search(self, query: str, retries: int = 3, backoff: float = 0.6) -> List[Dict[str, Any]]:
        """Return list of product dicts from catalog API."""
        params = {"query": query}
        for attempt in range(retries):
            try:
                resp = requests.get(self.SEARCH_URL, params=params, timeout=self.TIMEOUT)
                if resp.status_code in self.RETRY_STATUSES and attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data.get("products", []) or data.get("items", []) or []
            except requests.RequestException:
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise
        return []

    @staticmethod
    def score_match(product: Dict[str, Any], product_name: str, article_candidates: List[str]) -> float:
        """Simple scoring heuristic for catalog results."""
        name = str(product.get("name") or product.get("full_name") or "").lower()
        pname = product_name.lower()

        # Exact name match is best
        if name == pname:
            return 1.0

        # Article overlap
        score = 0.0
        if article_candidates:
            pname_clean = pname.replace("-", " ").replace("_", " ")
            for art in article_candidates:
                if art.lower() in name or art.lower() in pname_clean:
                    score += 0.4

        # Name containment
        if pname in name or name in pname:
            score += 0.3

        # Word overlap
        pname_words = set(pname.split())
        name_words = set(name.split())
        if pname_words and name_words:
            overlap = len(pname_words & name_words) / max(len(pname_words), len(name_words))
            score += overlap * 0.3

        return min(score, 1.0)
