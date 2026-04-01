"""Client helpers for the local wdk-btc-wallet service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_wallet.config import resolve_openclaw_home
from agent_wallet.wallet_layer.base import WalletBackendError

LOCAL_WDK_BTC_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _normalize_base_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WalletBackendError("WDK BTC service URL is not configured.")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_WDK_BTC_HOSTS:
        raise WalletBackendError("WDK BTC service URL must point to a localhost HTTP endpoint.")
    return text.rstrip("/")


def _resolve_local_token_path() -> Path:
    configured = os.getenv("WDK_BTC_LOCAL_TOKEN_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return resolve_openclaw_home() / "wdk-btc-wallet" / "local-auth-token"


def _load_local_token() -> str:
    direct = os.getenv("WDK_BTC_LOCAL_TOKEN", "").strip()
    if direct:
        return direct
    token_path = _resolve_local_token_path()
    if not token_path.exists():
        raise WalletBackendError(
            f"WDK BTC local auth token file not found: {token_path}. Start the local wdk-btc-wallet service first."
        )
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise WalletBackendError(f"WDK BTC local auth token file is empty: {token_path}")
    return token


def _unwrap_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:  # pragma: no cover - defensive
        raise WalletBackendError(
            f"wdk-btc-wallet returned a non-JSON response ({response.status_code})."
        ) from exc
    if response.status_code >= 400 or payload.get("ok") is False:
        detail = payload.get("error") or f"HTTP {response.status_code}"
        raise WalletBackendError(str(detail))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise WalletBackendError("wdk-btc-wallet returned an invalid response payload.")
    return data


class WdkBtcLocalClient:
    """Small client for the local BTC wallet service."""

    def __init__(self, base_url: str):
        self.base_url = _normalize_base_url(base_url)
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {_load_local_token()}",
        }

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers=self._headers,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload)
        return _unwrap_payload(response)

    async def get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers=self._headers,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(f"{self.base_url}{path}")
        return _unwrap_payload(response)

    def post_sync(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(
            timeout=10.0,
            headers=self._headers,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(f"{self.base_url}{path}", json=payload)
        return _unwrap_payload(response)

    def get_sync(self, path: str) -> dict[str, Any]:
        with httpx.Client(
            timeout=10.0,
            headers=self._headers,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(f"{self.base_url}{path}")
        return _unwrap_payload(response)
