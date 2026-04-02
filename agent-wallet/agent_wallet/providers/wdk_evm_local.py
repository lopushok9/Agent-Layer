"""Client helpers for the local wdk-evm-wallet service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_wallet.config import resolve_openclaw_home
from agent_wallet.wallet_layer.base import WalletBackendError

LOCAL_WDK_EVM_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _error_details_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    details = payload.get("error_details")
    return dict(details) if isinstance(details, dict) else None


def _normalize_base_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WalletBackendError("WDK EVM service URL is not configured.")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_WDK_EVM_HOSTS:
        raise WalletBackendError("WDK EVM service URL must point to a localhost HTTP endpoint.")
    return text.rstrip("/")


def _resolve_local_token_path() -> Path:
    configured = os.getenv("WDK_EVM_LOCAL_TOKEN_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return resolve_openclaw_home() / "wdk-evm-wallet" / "local-auth-token"


def _load_local_token() -> str:
    direct = os.getenv("WDK_EVM_LOCAL_TOKEN", "").strip()
    if direct:
        return direct
    token_path = _resolve_local_token_path()
    if not token_path.exists():
        raise WalletBackendError(
            f"WDK EVM local auth token file not found: {token_path}. Start the local wdk-evm-wallet service first."
        )
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise WalletBackendError(f"WDK EVM local auth token file is empty: {token_path}")
    return token


def _unwrap_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:  # pragma: no cover - defensive
        raise WalletBackendError(
            f"wdk-evm-wallet returned a non-JSON response ({response.status_code}).",
            code="network_unavailable",
            details={
                "service": "wdk-evm-wallet",
                "http_status": response.status_code,
            },
        ) from exc
    if response.status_code >= 400 or payload.get("ok") is False:
        detail = payload.get("error") or f"HTTP {response.status_code}"
        raise WalletBackendError(
            str(detail),
            code=str(payload.get("error_code") or "").strip() or None,
            details=_error_details_from_payload(payload),
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise WalletBackendError("wdk-evm-wallet returned an invalid response payload.")
    return data


class WdkEvmLocalClient:
    """Small client for the local EVM wallet service."""

    def __init__(self, base_url: str):
        self.base_url = _normalize_base_url(base_url)
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {_load_local_token()}",
        }

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(f"{self.base_url}{path}", json=payload)
        except httpx.TimeoutException as exc:
            raise WalletBackendError(
                "wdk-evm-wallet request timed out.",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        except httpx.RequestError as exc:
            raise WalletBackendError(
                f"wdk-evm-wallet request failed: {exc}",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        return _unwrap_payload(response)

    async def get(self, path: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(f"{self.base_url}{path}")
        except httpx.TimeoutException as exc:
            raise WalletBackendError(
                "wdk-evm-wallet request timed out.",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        except httpx.RequestError as exc:
            raise WalletBackendError(
                f"wdk-evm-wallet request failed: {exc}",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        return _unwrap_payload(response)

    def post_sync(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=10.0,
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(f"{self.base_url}{path}", json=payload)
        except httpx.TimeoutException as exc:
            raise WalletBackendError(
                "wdk-evm-wallet request timed out.",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        except httpx.RequestError as exc:
            raise WalletBackendError(
                f"wdk-evm-wallet request failed: {exc}",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        return _unwrap_payload(response)

    def get_sync(self, path: str) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=10.0,
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.get(f"{self.base_url}{path}")
        except httpx.TimeoutException as exc:
            raise WalletBackendError(
                "wdk-evm-wallet request timed out.",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        except httpx.RequestError as exc:
            raise WalletBackendError(
                f"wdk-evm-wallet request failed: {exc}",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": path},
            ) from exc
        return _unwrap_payload(response)
