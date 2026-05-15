"""Flash Trade provider helpers for perps market and position reads."""

from __future__ import annotations

import os
from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.http_client import get_client

PROVIDER_NAME = "flash-trade"


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _gateway_base_url() -> str:
    return os.getenv("PROVIDER_GATEWAY_URL", settings.provider_gateway_url).strip().rstrip("/")


def _gateway_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    bearer = os.getenv(
        "PROVIDER_GATEWAY_BEARER_TOKEN",
        settings.provider_gateway_bearer_token,
    ).strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def _gateway_enabled() -> bool:
    return bool(_gateway_base_url())


def _direct_base_url() -> str:
    return os.getenv("FLASH_API_BASE_URL", settings.flash_api_base_url).strip().rstrip("/")


def _direct_enabled() -> bool:
    return bool(_direct_base_url())


def _route_missing(status_code: int, payload: Any) -> bool:
    if status_code == 404:
        return True
    if isinstance(payload, dict):
        message = str(payload.get("error") or payload.get("message") or "").lower()
        if "not found" in message or "unknown route" in message:
            return True
    return False


async def _request_json(
    url: str,
    *,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> tuple[int, Any]:
    client = get_client()
    response = await client.get(url, params=params, headers=headers)
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text[:500]


def _unwrap_response(
    status_code: int,
    payload: Any,
    *,
    operation: str,
) -> Any:
    if isinstance(payload, dict) and payload.get("ok") is False:
        message = str(payload.get("error") or payload.get("message") or f"{operation} failed.")
        raise ProviderError(PROVIDER_NAME, f"{operation} failed: {message}")

    if status_code != 200:
        message = payload
        if isinstance(payload, dict):
            message = payload.get("error") or payload.get("message") or payload
        raise ProviderError(PROVIDER_NAME, f"{operation} failed: {message}")

    return payload


async def _get_with_fallback(
    path: str,
    *,
    params: dict[str, Any] | None,
    operation: str,
) -> Any:
    if _gateway_enabled():
        status_code, payload = await _request_json(
            f"{_gateway_base_url()}{path}",
            params=params,
            headers=_gateway_headers(),
        )
        if not _route_missing(status_code, payload):
            return _unwrap_response(status_code, payload, operation=operation)

    if _direct_enabled():
        direct_variants = [path]
        if path == "/v1/flash/perps/markets":
            direct_variants.append("/markets")
        elif path == "/v1/flash/perps/positions":
            direct_variants.append("/positions")
        last_status = 404
        last_payload: Any = {"error": "not found"}
        for direct_path in direct_variants:
            status_code, payload = await _request_json(
                f"{_direct_base_url()}{direct_path}",
                params=params,
                headers=_headers(),
            )
            last_status = status_code
            last_payload = payload
            if _route_missing(status_code, payload) and direct_path != direct_variants[-1]:
                continue
            return _unwrap_response(status_code, payload, operation=operation)
        return _unwrap_response(last_status, last_payload, operation=operation)

    raise ProviderError(
        PROVIDER_NAME,
        (
            f"{operation} is not configured. "
            "Expose Flash routes on PROVIDER_GATEWAY_URL or set FLASH_API_BASE_URL."
        ),
    )


def _normalize_named_list_response(
    data: Any,
    *,
    key: str,
) -> dict[str, Any]:
    if isinstance(data, list):
        return {key: data}
    if isinstance(data, dict):
        items = data.get(key)
        if isinstance(items, list):
            return data
        fallback = data.get("data")
        if isinstance(fallback, list):
            normalized = dict(data)
            normalized[key] = fallback
            return normalized
    raise ProviderError(PROVIDER_NAME, f"Unexpected {key} response from Flash Trade.")


async def fetch_markets(*, pool_name: str | None = None) -> dict[str, Any]:
    params = {"pool_name": pool_name} if pool_name else None
    data = await _get_with_fallback(
        "/v1/flash/perps/markets",
        params=params,
        operation="Flash Trade market lookup",
    )
    return _normalize_named_list_response(data, key="markets")


async def fetch_positions(
    *,
    owner: str,
    pool_name: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"owner": owner}
    if pool_name:
        params["pool_name"] = pool_name
    data = await _get_with_fallback(
        "/v1/flash/perps/positions",
        params=params,
        operation="Flash Trade position lookup",
    )
    return _normalize_named_list_response(data, key="positions")
