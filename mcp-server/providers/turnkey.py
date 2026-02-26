"""Turnkey provider via turnkey CLI (headless-friendly for VPS agents)."""

from __future__ import annotations

import asyncio
import binascii
import json
import os
import shutil
from pathlib import Path

from config import settings
from exceptions import ProviderError


def _resolve_cli_path() -> str:
    """Resolve turnkey CLI path from env/path with sane fallback."""
    configured = settings.turnkey_cli_path.strip()
    if configured:
        if os.path.isabs(configured) and os.path.exists(configured):
            return configured
        resolved = shutil.which(configured)
        if resolved:
            return resolved

    # Dockerfile installs the binary here.
    fallback = "/usr/local/bin/turnkey"
    if os.path.exists(fallback):
        return fallback

    raise ProviderError(
        "turnkey",
        "Turnkey CLI not found. Set TURNKEY_CLI_PATH (e.g. /usr/local/bin/turnkey) "
        "or install tkcli binary.",
    )


def _write_keypair(folder: Path, key_name: str, public_key: str, private_key: str) -> None:
    """Write turnkey keypair files to the given folder."""
    folder.mkdir(parents=True, exist_ok=True)
    pub_path = folder / f"{key_name}.public"
    prv_path = folder / f"{key_name}.private"
    # tkcli expects strict hex content without trailing newline bytes.
    pub_path.write_text(public_key.strip(), encoding="utf-8")
    prv_path.write_text(private_key.strip(), encoding="utf-8")
    os.chmod(pub_path, 0o644)
    os.chmod(prv_path, 0o600)


def _normalize_hex_key(value: str, env_name: str) -> str:
    """Normalize and validate a hex-encoded key for tkcli key files."""
    raw = value.strip()
    if "BEGIN " in raw or "-----" in raw:
        raise ProviderError(
            "turnkey",
            f"{env_name} appears to be PEM-formatted. Turnkey CLI key files require raw hex keys.",
        )
    if raw.startswith("0x") or raw.startswith("0X"):
        raw = raw[2:]
    raw = "".join(raw.split())
    if not raw:
        raise ProviderError("turnkey", f"{env_name} is empty.")
    if len(raw) % 2 != 0:
        raise ProviderError("turnkey", f"{env_name} must contain an even-length hex string.")
    try:
        binascii.unhexlify(raw)
    except (binascii.Error, ValueError) as exc:
        raise ProviderError("turnkey", f"{env_name} is not valid hex: {exc}") from exc
    return raw.lower()


def _resolve_keys_folders() -> tuple[str | None, str | None]:
    """Resolve API/encryption key folders from settings or env-provided key material."""
    keys_folder = settings.turnkey_keys_folder.strip() or None
    enc_keys_folder = settings.turnkey_encryption_keys_folder.strip() or None

    has_api_env = bool(settings.turnkey_api_public_key and settings.turnkey_api_private_key)
    has_enc_env = bool(
        settings.turnkey_encryption_public_key and settings.turnkey_encryption_private_key
    )

    if (settings.turnkey_api_public_key or settings.turnkey_api_private_key) and not has_api_env:
        raise ProviderError(
            "turnkey",
            "Set both TURNKEY_API_PUBLIC_KEY and TURNKEY_API_PRIVATE_KEY, or neither.",
        )
    if (settings.turnkey_encryption_public_key or settings.turnkey_encryption_private_key) and not has_enc_env:
        raise ProviderError(
            "turnkey",
            "Set both TURNKEY_ENCRYPTION_PUBLIC_KEY and TURNKEY_ENCRYPTION_PRIVATE_KEY, or neither.",
        )

    if has_api_env:
        api_pub = _normalize_hex_key(settings.turnkey_api_public_key, "TURNKEY_API_PUBLIC_KEY")
        api_prv = _normalize_hex_key(settings.turnkey_api_private_key, "TURNKEY_API_PRIVATE_KEY")
        api_dir = Path("/tmp/turnkey/keys")
        _write_keypair(
            folder=api_dir,
            key_name=settings.turnkey_key_name,
            public_key=api_pub,
            private_key=api_prv,
        )
        keys_folder = str(api_dir)

    if has_enc_env:
        enc_pub = _normalize_hex_key(
            settings.turnkey_encryption_public_key,
            "TURNKEY_ENCRYPTION_PUBLIC_KEY",
        )
        enc_prv = _normalize_hex_key(
            settings.turnkey_encryption_private_key,
            "TURNKEY_ENCRYPTION_PRIVATE_KEY",
        )
        enc_dir = Path("/tmp/turnkey/encryption-keys")
        _write_keypair(
            folder=enc_dir,
            key_name=settings.turnkey_encryption_key_name,
            public_key=enc_pub,
            private_key=enc_prv,
        )
        enc_keys_folder = str(enc_dir)

    return keys_folder, enc_keys_folder


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
    cli_path = _resolve_cli_path()
    keys_folder, encryption_keys_folder = _resolve_keys_folders()

    args = [
        cli_path,
        "--organization",
        settings.turnkey_organization_id,
        "--key-name",
        settings.turnkey_key_name,
        "--output",
        "json",
    ]
    if keys_folder:
        args.extend(["--keys-folder", keys_folder])
    if encryption_keys_folder:
        args.extend(["--encryption-keys-folder", encryption_keys_folder])
    if settings.turnkey_encryption_key_name:
        args.extend(["--encryption-key-name", settings.turnkey_encryption_key_name])
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
    try:
        cli_path = _resolve_cli_path()
    except ProviderError:
        return {
            "enabled": settings.turnkey_enabled,
            "cli_found": False,
            "cli_path": settings.turnkey_cli_path,
            "organization_id_set": bool(settings.turnkey_organization_id),
            "key_name_set": bool(settings.turnkey_key_name),
            "keys_folder_set": bool(settings.turnkey_keys_folder),
            "encryption_keys_folder_set": bool(settings.turnkey_encryption_keys_folder),
            "api_key_from_env": bool(settings.turnkey_api_public_key and settings.turnkey_api_private_key),
            "encryption_key_from_env": bool(
                settings.turnkey_encryption_public_key and settings.turnkey_encryption_private_key
            ),
        }
    process = await asyncio.create_subprocess_exec(
        cli_path,
        "version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    version = (stdout or b"").decode("utf-8", errors="replace").strip()
    return {
        "enabled": settings.turnkey_enabled,
        "cli_found": True,
        "cli_path": cli_path,
        "organization_id_set": bool(settings.turnkey_organization_id),
        "key_name_set": bool(settings.turnkey_key_name),
        "keys_folder_set": bool(settings.turnkey_keys_folder),
        "encryption_keys_folder_set": bool(settings.turnkey_encryption_keys_folder),
        "api_key_from_env": bool(settings.turnkey_api_public_key and settings.turnkey_api_private_key),
        "encryption_key_from_env": bool(
            settings.turnkey_encryption_public_key and settings.turnkey_encryption_private_key
        ),
        "version": version or None,
    }


def _extract_activity_payload(data: dict) -> dict:
    """Return nested activity object if present, otherwise raw payload."""
    if isinstance(data.get("activity"), dict):
        return data["activity"]
    if isinstance(data.get("result"), dict):
        result = data["result"]
        if isinstance(result.get("activity"), dict):
            return result["activity"]
    return data


def _extract_fingerprint(data: dict) -> str:
    """Extract activity fingerprint from get_activity-like payload."""
    activity = _extract_activity_payload(data)
    fp = activity.get("fingerprint") if isinstance(activity, dict) else None
    if not fp:
        raise ProviderError("turnkey", "Could not extract activity fingerprint from response")
    return str(fp)


async def create_wallet(wallet_name: str) -> dict:
    """Create a wallet in Turnkey."""
    return await _run_cli("wallets", "create", "--name", wallet_name)


async def create_wallet_account(
    wallet_name: str,
    account_name: str,
    path_format: str = "PATH_FORMAT_BIP32",
    path: str = "m/44'/60'/0'/0/0",
    curve: str = "CURVE_SECP256K1",
    address_format: str = "ADDRESS_FORMAT_ETHEREUM",
) -> dict:
    """Create an account inside wallet."""
    base_args = [
        "wallets",
        "accounts",
        "create",
        "--wallet",
        wallet_name,
        "--path-format",
        path_format,
        "--path",
        path,
        "--curve",
        curve,
        "--address-format",
        address_format,
    ]
    # Newer tkcli supports explicit account label via --name.
    # Older versions reject --name; in that case retry without it.
    try:
        return await _run_cli(*base_args[:5], "--name", account_name, *base_args[5:])
    except ProviderError as exc:
        if "unknown flag: --name" not in str(exc):
            raise
        return await _run_cli(*base_args)


async def list_wallet_accounts(wallet_name: str) -> dict:
    """List accounts for wallet."""
    return await _run_cli("wallets", "accounts", "list", "--wallet", wallet_name)


async def sign_transaction(
    sign_with: str,
    unsigned_transaction: str,
    type_: str = "TRANSACTION_TYPE_ETHEREUM",
) -> dict:
    """Sign raw unsigned transaction with Turnkey account."""
    return await _run_cli(
        "request",
        "--path",
        "/public/v1/submit/sign_transaction",
        "--body",
        json.dumps(
            {
                "type": "ACTIVITY_TYPE_SIGN_TRANSACTION_V2",
                "organizationId": settings.turnkey_organization_id,
                "parameters": {
                    "type": type_,
                    "signWith": sign_with,
                    "unsignedTransaction": unsigned_transaction,
                },
            }
        ),
    )


async def list_activities() -> dict:
    """List organization activities."""
    return await _run_cli("activities", "list")


async def get_activity(activity_id: str) -> dict:
    """Get activity details by ID."""
    return await _run_cli("activities", "get", activity_id.strip())


async def approve_activity(activity_id: str | None = None, fingerprint: str | None = None) -> dict:
    """Approve activity by fingerprint or activity ID."""
    fp = (fingerprint or "").strip()
    if not fp:
        if not activity_id or not activity_id.strip():
            raise ProviderError("turnkey", "Provide activity_id or fingerprint")
        activity = await get_activity(activity_id)
        fp = _extract_fingerprint(activity)

    body = {
        "type": "ACTIVITY_TYPE_APPROVE_ACTIVITY",
        "organizationId": settings.turnkey_organization_id,
        "parameters": {"fingerprint": fp},
    }
    return await _run_cli(
        "request",
        "--path",
        "/public/v1/submit/approve_activity",
        "--body",
        json.dumps(body),
    )


async def reject_activity(activity_id: str | None = None, fingerprint: str | None = None) -> dict:
    """Reject activity by fingerprint or activity ID."""
    fp = (fingerprint or "").strip()
    if not fp:
        if not activity_id or not activity_id.strip():
            raise ProviderError("turnkey", "Provide activity_id or fingerprint")
        activity = await get_activity(activity_id)
        fp = _extract_fingerprint(activity)

    body = {
        "type": "ACTIVITY_TYPE_REJECT_ACTIVITY",
        "organizationId": settings.turnkey_organization_id,
        "parameters": {"fingerprint": fp},
    }
    return await _run_cli(
        "request",
        "--path",
        "/public/v1/submit/reject_activity",
        "--body",
        json.dumps(body),
    )
