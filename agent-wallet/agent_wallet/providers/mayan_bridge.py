"""Local Node bridge for Mayan SDK-backed Solana-origin swaps."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError


def _bridge_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "mayan-bridge"


def _bridge_cli_path() -> Path:
    return _bridge_dir() / "cli.mjs"


async def swap_from_solana(
    *,
    quote: dict[str, Any],
    swapper_wallet_address: str,
    destination_address: str,
    rpc_url: str,
    extra_rpc_urls: list[str] | None,
    solana_keypair_bytes: bytes,
) -> dict[str, Any]:
    bridge_dir = _bridge_dir()
    cli_path = _bridge_cli_path()
    if not cli_path.exists():
        raise ProviderError(
            "mayan",
            "Local Mayan bridge is not installed. Expected agent-wallet/mayan-bridge/cli.mjs.",
        )

    payload = {
        "quote": quote,
        "swapperWalletAddress": swapper_wallet_address,
        "destinationAddress": destination_address,
        "rpcUrl": rpc_url,
        "extraRpcUrls": [item for item in (extra_rpc_urls or []) if isinstance(item, str) and item.strip()],
        "solanaKeypairBase64": base64.b64encode(solana_keypair_bytes).decode("ascii"),
        "apiKey": settings.mayan_api_key.strip() or None,
    }

    try:
        process = await asyncio.create_subprocess_exec(
            "node",
            str(cli_path),
            "execute-solana-swap",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(bridge_dir),
        )
    except FileNotFoundError as exc:
        raise ProviderError(
            "mayan",
            "Node.js is required for Mayan Solana swap execution but was not found on PATH.",
        ) from exc

    stdout, stderr = await process.communicate(json.dumps(payload).encode("utf-8"))
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()

    if process.returncode != 0:
        message = stderr_text or stdout_text or "Mayan bridge execution failed."
        try:
            parsed_error = json.loads(stdout_text) if stdout_text else None
        except json.JSONDecodeError:
            parsed_error = None
        if isinstance(parsed_error, dict):
            message = str(parsed_error.get("error") or parsed_error.get("message") or message)
        raise ProviderError("mayan", message)

    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        raise ProviderError("mayan", "Mayan bridge returned invalid JSON.") from exc

    if not isinstance(payload, dict) or payload.get("ok") is not True or not isinstance(payload.get("data"), dict):
        raise ProviderError("mayan", "Mayan bridge returned an unexpected response.")
    return payload["data"]
