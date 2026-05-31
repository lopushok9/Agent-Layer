"""Client helpers for the local wdk-evm-wallet service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_wallet.config import resolve_evm_wallet_password, resolve_openclaw_home, settings
from agent_wallet.wallet_layer.base import WalletBackendError

LOCAL_WDK_EVM_HOSTS = {"127.0.0.1", "localhost", "::1"}
LONG_RUNNING_SEND_PATHS = {
    "/v1/evm/aave/supply/send",
    "/v1/evm/aave/withdraw/send",
    "/v1/evm/aave/borrow/send",
    "/v1/evm/aave/repay/send",
    "/v1/evm/lido/stake_eth_for_wsteth/send",
    "/v1/evm/lido/wrap_steth/send",
    "/v1/evm/lido/unwrap_wsteth/send",
    "/v1/evm/lido/request_withdrawal_steth/send",
    "/v1/evm/lido/request_withdrawal_wsteth/send",
    "/v1/evm/lido/claim_withdrawal/send",
    "/v1/evm/swap/send",
    "/v1/evm/lifi/send",
    "/v1/evm/transfer/send",
    "/v1/evm/token-transfer/send",
}
LONG_RUNNING_SEND_TIMEOUT_SECONDS = 120.0


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


def _timeout_for_path(path: str) -> float:
    normalized = str(path or "").strip()
    base_timeout = float(settings.http_timeout)
    if normalized in LONG_RUNNING_SEND_PATHS:
        return max(base_timeout, LONG_RUNNING_SEND_TIMEOUT_SECONDS)
    return base_timeout


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


def _unwrap_list_payload(response: httpx.Response) -> list[dict[str, Any]]:
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
    if not isinstance(data, list):
        raise WalletBackendError("wdk-evm-wallet returned an invalid list response payload.")
    wallets: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            wallets.append(dict(item))
    return wallets


class WdkEvmLocalClient:
    """Small client for the local EVM wallet service."""

    def __init__(self, base_url: str):
        self.base_url = _normalize_base_url(base_url)
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {_load_local_token()}",
        }
        self._wallet_password: str | None = None

    def _resolve_wallet_password(self) -> str:
        """Resolve the sealed local EVM vault password once per client instance.

        The decrypt-on-demand vault needs the password on every signing request.
        Resolving (and unsealing) it once per client keeps the Argon2id unseal off
        the per-request path. The agent already holds the boot key, so caching the
        derived password here adds no exposure beyond what the boot key grants.
        """
        if self._wallet_password is None:
            try:
                self._wallet_password = resolve_evm_wallet_password() or ""
            except Exception:
                self._wallet_password = ""
        return self._wallet_password

    def _with_credentials(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach the sealed vault password unless the caller supplied one.

        Read endpoints that resolve via a stored address ignore the field; only
        seed-requiring (signing) endpoints consume it. Injecting it uniformly means
        no signing path can accidentally be missed.
        """
        if not isinstance(payload, dict) or payload.get("password"):
            return payload
        password = self._resolve_wallet_password()
        if not password:
            return payload
        return {**payload, "password": password}

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=_timeout_for_path(path),
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{self.base_url}{path}", json=self._with_credentials(payload)
                )
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
                timeout=_timeout_for_path(path),
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
                timeout=_timeout_for_path(path),
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self.base_url}{path}", json=self._with_credentials(payload)
                )
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
                timeout=_timeout_for_path(path),
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

    def list_wallets_sync(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(
                timeout=float(settings.http_timeout),
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.get(f"{self.base_url}/v1/evm/wallets")
        except httpx.TimeoutException as exc:
            raise WalletBackendError(
                "wdk-evm-wallet request timed out.",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": "/v1/evm/wallets"},
            ) from exc
        except httpx.RequestError as exc:
            raise WalletBackendError(
                f"wdk-evm-wallet request failed: {exc}",
                code="network_unavailable",
                details={"service": "wdk-evm-wallet", "path": "/v1/evm/wallets"},
            ) from exc
        return _unwrap_list_payload(response)
