"""Local bridge contract for Flash SDK-backed preview generation."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError

PROVIDER_NAME = "flash-sdk-bridge"


def _bridge_command() -> list[str]:
    raw = os.getenv("FLASH_SDK_BRIDGE_COMMAND", settings.flash_sdk_bridge_command).strip()
    if not raw:
        raise ProviderError(
            PROVIDER_NAME,
            "FLASH_SDK_BRIDGE_COMMAND is not configured.",
        )
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise ProviderError(PROVIDER_NAME, f"Invalid FLASH_SDK_BRIDGE_COMMAND: {exc}") from exc
    if not command:
        raise ProviderError(PROVIDER_NAME, "FLASH_SDK_BRIDGE_COMMAND is empty.")
    return command


def _bridge_timeout_seconds() -> float:
    raw = os.getenv(
        "FLASH_SDK_BRIDGE_TIMEOUT_SECONDS",
        str(settings.flash_sdk_bridge_timeout_seconds),
    ).strip()
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ProviderError(
            PROVIDER_NAME,
            "FLASH_SDK_BRIDGE_TIMEOUT_SECONDS must be numeric.",
        ) from exc
    return max(timeout, 1.0)


def _unwrap_bridge_payload(payload: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProviderError(PROVIDER_NAME, f"{operation} returned a non-object response.")
    if payload.get("ok") is False:
        message = str(payload.get("error") or f"{operation} failed.")
        raise ProviderError(PROVIDER_NAME, message)
    data = payload.get("preview")
    if isinstance(data, dict):
        return data
    data = payload.get("prepared")
    if isinstance(data, dict):
        return data
    if isinstance(payload.get("data"), dict):
        return dict(payload["data"])
    return dict(payload)


async def _call_bridge(payload: dict[str, Any]) -> dict[str, Any]:
    command = _bridge_command()
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ProviderError(PROVIDER_NAME, f"Could not start Flash SDK bridge: {exc}") from exc

    stdin_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timeout = _bridge_timeout_seconds()
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin_bytes),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ProviderError(
            PROVIDER_NAME,
            f"Flash SDK bridge timed out after {timeout:.1f}s.",
        ) from exc

    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip() or stdout.decode(
            "utf-8",
            errors="replace",
        ).strip()
        raise ProviderError(
            PROVIDER_NAME,
            f"Flash SDK bridge failed with exit code {process.returncode}: {message[:500]}",
        )

    try:
        decoded = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError(
            PROVIDER_NAME,
            "Flash SDK bridge returned invalid JSON.",
        ) from exc
    return decoded


async def preview_open_position_same_collateral(
    *,
    owner: str,
    pool_name: str,
    market_symbol: str,
    collateral_symbol: str,
    collateral_amount_raw: str,
    leverage: str,
    side: str,
    network: str,
) -> dict[str, Any]:
    payload = {
        "action": "preview_open_position_same_collateral",
        "owner": owner,
        "pool_name": pool_name,
        "market_symbol": market_symbol,
        "collateral_symbol": collateral_symbol,
        "collateral_amount_raw": collateral_amount_raw,
        "leverage": leverage,
        "side": side,
        "network": network,
    }
    response = await _call_bridge(payload)
    return _unwrap_bridge_payload(response, operation="Flash open-position preview")


async def get_markets(
    *,
    pool_name: str | None,
    network: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "get_markets",
        "network": network,
    }
    if pool_name:
        payload["pool_name"] = pool_name
    response = await _call_bridge(payload)
    return _unwrap_bridge_payload(response, operation="Flash market lookup")


async def get_positions(
    *,
    owner: str,
    pool_name: str | None,
    network: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "get_positions",
        "owner": owner,
        "network": network,
    }
    if pool_name:
        payload["pool_name"] = pool_name
    response = await _call_bridge(payload)
    return _unwrap_bridge_payload(response, operation="Flash position lookup")


async def preview_close_position_same_collateral(
    *,
    owner: str,
    pool_name: str,
    market_symbol: str,
    side: str,
    network: str,
) -> dict[str, Any]:
    payload = {
        "action": "preview_close_position_same_collateral",
        "owner": owner,
        "pool_name": pool_name,
        "market_symbol": market_symbol,
        "side": side,
        "network": network,
    }
    response = await _call_bridge(payload)
    return _unwrap_bridge_payload(response, operation="Flash close-position preview")


async def prepare_open_position_same_collateral(
    *,
    owner: str,
    pool_name: str,
    market_symbol: str,
    collateral_symbol: str,
    collateral_amount_raw: str,
    leverage: str,
    side: str,
    network: str,
) -> dict[str, Any]:
    payload = {
        "action": "prepare_open_position_same_collateral",
        "owner": owner,
        "pool_name": pool_name,
        "market_symbol": market_symbol,
        "collateral_symbol": collateral_symbol,
        "collateral_amount_raw": collateral_amount_raw,
        "leverage": leverage,
        "side": side,
        "network": network,
    }
    response = await _call_bridge(payload)
    return _unwrap_bridge_payload(response, operation="Flash open-position prepare")


async def prepare_close_position_same_collateral(
    *,
    owner: str,
    pool_name: str,
    market_symbol: str,
    side: str,
    network: str,
) -> dict[str, Any]:
    payload = {
        "action": "prepare_close_position_same_collateral",
        "owner": owner,
        "pool_name": pool_name,
        "market_symbol": market_symbol,
        "side": side,
        "network": network,
    }
    response = await _call_bridge(payload)
    return _unwrap_bridge_payload(response, operation="Flash close-position prepare")
