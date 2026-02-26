"""Turnkey provider via turnkey CLI (headless-friendly for VPS agents)."""

from __future__ import annotations

import asyncio
import json
import shutil

from config import settings
from exceptions import ProviderError


def _base_args() -> list[str]:
    if not settings.turnkey_enabled:
        raise ProviderError(
            "turnkey",
            "Turnkey is disabled. Set TURNKEY_ENABLED=true in .env.",
        )
    if not settings.turnkey_organization_id:
        raise ProviderError(
            "turnkey",
            "TURNKEY_ORGANIZATION_ID is required.",
        )
    if not settings.turnkey_key_name:
        raise ProviderError(
            "turnkey",
            "TURNKEY_KEY_NAME is required.",
        )
    if shutil.which(settings.turnkey_cli_path) is None:
        raise ProviderError(
            "turnkey",
            f"Turnkey CLI not found: '{settings.turnkey_cli_path}'. Install with 'npm i -g @turnkey/sdk-server'.",
        )

    args = [
        settings.turnkey_cli_path,
        "--organization",
        settings.turnkey_organization_id,
        "--key",
        settings.turnkey_key_name,
    ]
    if settings.turnkey_keys_folder:
        args.extend(["--keys-folder", settings.turnkey_keys_folder])
    return args


async def _run_cli(*extra_args: str) -> dict:
    args = [*_base_args(), *extra_args]
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=settings.turnkey_command_timeout,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        raise ProviderError("turnkey", f"CLI timeout after {settings.turnkey_command_timeout}s") from exc

    if process.returncode != 0:
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        message = err or out or f"CLI exited with code {process.returncode}"
        raise ProviderError("turnkey", message)

    raw = (stdout or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_output": raw}


async def get_status() -> dict:
    """Check CLI availability and return version/config summary."""
    if shutil.which(settings.turnkey_cli_path) is None:
        return {
            "enabled": settings.turnkey_enabled,
            "cli_found": False,
            "cli_path": settings.turnkey_cli_path,
            "organization_id_set": bool(settings.turnkey_organization_id),
            "key_name_set": bool(settings.turnkey_key_name),
            "keys_folder_set": bool(settings.turnkey_keys_folder),
        }
    process = await asyncio.create_subprocess_exec(
        settings.turnkey_cli_path,
        "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    version = (stdout or b"").decode("utf-8", errors="replace").strip()
    return {
        "enabled": settings.turnkey_enabled,
        "cli_found": True,
        "cli_path": settings.turnkey_cli_path,
        "organization_id_set": bool(settings.turnkey_organization_id),
        "key_name_set": bool(settings.turnkey_key_name),
        "keys_folder_set": bool(settings.turnkey_keys_folder),
        "version": version or None,
    }


async def create_wallet(wallet_name: str) -> dict:
    """Create a wallet in Turnkey."""
    return await _run_cli("wallets", "create", wallet_name, "--json")


async def create_wallet_account(
    wallet_name: str,
    account_name: str,
    path_format: str = "PATH_FORMAT_BIP32",
    path: str = "m/44'/60'/0'/0/0",
    curve: str = "CURVE_SECP256K1",
    address_format: str = "ADDRESS_FORMAT_ETHEREUM",
) -> dict:
    """Create an account inside wallet."""
    return await _run_cli(
        "wallets",
        "accounts",
        "create",
        wallet_name,
        account_name,
        "--path-format",
        path_format,
        "--path",
        path,
        "--curve",
        curve,
        "--address-format",
        address_format,
        "--json",
    )


async def list_wallet_accounts(wallet_name: str) -> dict:
    """List accounts for wallet."""
    return await _run_cli("wallets", "accounts", "list", wallet_name, "--json")


async def sign_transaction(
    sign_with: str,
    unsigned_transaction: str,
    type_: str = "TRANSACTION_TYPE_ETHEREUM",
) -> dict:
    """Sign raw unsigned transaction with Turnkey account."""
    if not settings.turnkey_allow_signing:
        raise ProviderError(
            "turnkey",
            "Transaction signing is disabled. Set TURNKEY_ALLOW_SIGNING=true to enable.",
        )
    return await _run_cli(
        "request",
        "--path",
        "/public/v1/submit/sign_transaction",
        "--body",
        json.dumps(
            {
                "type": type_,
                "signWith": sign_with,
                "unsignedTransaction": unsigned_transaction,
            }
        ),
        "--json",
    )
