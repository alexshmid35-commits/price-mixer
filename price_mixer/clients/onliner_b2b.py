"""Onliner B2B API client (OAuth2 + price/catalog endpoints)."""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from price_mixer.config import Config


class OnlinerB2BClient:
    """Clean B2B client with its own token cache and session state."""

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        cfg = Config()
        s = settings or {}
        self.base_url = s.get("base_url", cfg.onliner_b2b_base_url)
        self.price_api_base_url = s.get("price_api_base_url", cfg.onliner_b2b_price_api_base_url)
        self.token_url = s.get("token_url", cfg.onliner_b2b_token_url)
        self.client_id = s.get("client_id", cfg.onliner_b2b_client_id)
        self.client_secret = s.get("client_secret", cfg.onliner_b2b_client_secret)
        self.verify_ssl = s.get("verify_ssl", True)
        self.timeout = s.get("timeout_sec", 20)

        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _is_token_valid(self) -> bool:
        with self._lock:
            return self._token is not None and time.time() < self._token_expires_at - 60

    def get_token(self, force_refresh: bool = False) -> Optional[str]:
        if not force_refresh and self._is_token_valid():
            with self._lock:
                return self._token

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            resp = requests.post(
                self.token_url,
                data=payload,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            with self._lock:
                self._token = access_token
                self._token_expires_at = time.time() + expires_in
            return access_token
        except Exception:
            return None

    def invalidate_token(self) -> None:
        with self._lock:
            self._token = None
            self._token_expires_at = 0.0

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        force_token_refresh: bool = False,
        use_price_api: bool = False,
    ) -> requests.Response:
        token = self.get_token(force_refresh=force_token_refresh)
        if not token:
            raise RuntimeError("Unable to obtain Onliner B2B token")

        base = self.price_api_base_url if use_price_api else self.base_url
        url = f"{base}{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        resp = requests.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

        if resp.status_code == 401 and not force_token_refresh:
            self.invalidate_token()
            return self.request(method, path, params, json_body, force_token_refresh=True, use_price_api=use_price_api)

        resp.raise_for_status()
        return resp

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def get_sections(self) -> List[Dict[str, Any]]:
        r = self.request("GET", "/sections")
        return r.json().get("sections", [])

    def get_manufacturers(self, section_id: int) -> List[Dict[str, Any]]:
        r = self.request("GET", f"/sections/{section_id}/manufacturers")
        return r.json().get("manufacturers", [])

    def get_products(self, section_id: int, manufacturer_id: int, title: str = "") -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"page": 1, "per_page": 100}
        if title:
            params["title"] = title
        r = self.request("GET", f"/sections/{section_id}/manufacturers/{manufacturer_id}/products", params=params)
        return r.json().get("products", [])

    def get_articles(self, section_id: int, manufacturer_id: int, product_id: int) -> List[Dict[str, Any]]:
        r = self.request("GET", f"/sections/{section_id}/manufacturers/{manufacturer_id}/products/{product_id}/articles")
        return r.json().get("articles", [])
