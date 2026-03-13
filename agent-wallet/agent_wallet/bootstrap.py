"""Bootstrap helpers for provisioning agent wallets on first use."""

from __future__ import annotations

import json
from pathlib import Path

from agent_wallet.wallet_layer.base import WalletBackendError
from agent_wallet.wallet_layer.base58 import b58encode


def _keypair_bytes_for_file(secret_key: bytes, public_key: bytes) -> list[int]:
    return list(secret_key + public_key)


def generate_solana_wallet_material() -> dict[str, str]:
    """Generate new Solana secret material without writing it to disk."""
    try:
        from nacl.signing import SigningKey
    except ImportError as exc:
        raise WalletBackendError(
            "PyNaCl is required to auto-create a local Solana wallet."
        ) from exc

    signing_key = SigningKey.generate()
    secret_key = signing_key.encode()
    public_key = bytes(signing_key.verify_key)
    return {
        "address": b58encode(public_key),
        "secret_material": json.dumps(_keypair_bytes_for_file(secret_key, public_key), indent=2),
    }


def create_solana_wallet_file(path: Path) -> dict[str, str]:
    """Create a new local Solana wallet file in Solana CLI JSON format."""
    material = generate_solana_wallet_material()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(material["secret_material"], encoding="utf-8")
    path.chmod(0o600)
    return {
        "address": material["address"],
        "path": str(path),
    }


def ensure_solana_wallet_ready() -> dict[str, str] | None:
    """Ensure that a Solana wallet exists when auto-create is enabled."""
    from agent_wallet.config import default_solana_wallet_path, settings

    if settings.agent_wallet_backend.strip().lower() not in {"solana", "solana_local", "solana-local"}:
        return None

    if settings.solana_agent_private_key.strip():
        return {"address": "", "path": ""}

    configured_path = settings.solana_agent_keypair_path.strip()
    path = Path(configured_path).expanduser() if configured_path else default_solana_wallet_path(settings.solana_network)

    if path.exists():
        return {"address": "", "path": str(path)}

    if not settings.solana_auto_create_wallet:
        return None

    return create_solana_wallet_file(path)


def describe_bootstrap() -> dict[str, str | bool]:
    """Return the effective bootstrap configuration for installer/runtime usage."""
    from agent_wallet.config import (
        default_solana_wallet_path,
        resolve_solana_rpc_url,
        settings,
    )

    configured_path = settings.solana_agent_keypair_path.strip()
    path = Path(configured_path).expanduser() if configured_path else default_solana_wallet_path(settings.solana_network)
    return {
        "backend": settings.agent_wallet_backend,
        "network": settings.solana_network,
        "rpc_url": resolve_solana_rpc_url(settings.solana_network, settings.solana_rpc_url),
        "auto_create_wallet": settings.solana_auto_create_wallet,
        "keypair_path": str(path),
        "sign_only": settings.agent_wallet_sign_only,
    }
