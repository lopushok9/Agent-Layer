"""Client helpers for the local wdk-btc-wallet service."""

from __future__ import annotations

from typing import Any

import httpx

from agent_wallet.http_client import get_client
from agent_wallet.wallet_layer.base import WalletBackendError


def _normalize_base_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WalletBackendError("WDK BTC service URL is not configured.")
    return text.rstrip("/")


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

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await get_client().post(f"{self.base_url}{path}", json=payload)
        return _unwrap_payload(response)

    async def get(self, path: str) -> dict[str, Any]:
        response = await get_client().get(f"{self.base_url}{path}")
        return _unwrap_payload(response)

    def post_sync(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(
            timeout=10.0,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            response = client.post(f"{self.base_url}{path}", json=payload)
        return _unwrap_payload(response)

    def get_sync(self, path: str) -> dict[str, Any]:
        with httpx.Client(
            timeout=10.0,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            response = client.get(f"{self.base_url}{path}")
        return _unwrap_payload(response)
