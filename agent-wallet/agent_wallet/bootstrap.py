"""Bootstrap helpers for provisioning agent wallets on first use."""

from __future__ import annotations

import json
from pathlib import Path

from agent_wallet.config import refuse_mainnet_wallet_recreation
from agent_wallet.wallet_layer.base import WalletBackendError
from agent_wallet.wallet_layer.base58 import b58encode

WALLET_ADDRESS_PIN_KIND = "openclaw-agent-wallet-address-pin"
WALLET_ADDRESS_PIN_VERSION = 1


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


def resolve_wallet_pin_path(path: Path) -> Path:
    """Return the sidecar file used to pin an expected wallet address."""
    return path.with_suffix(f"{path.suffix}.pin.json")


def load_wallet_pin(path: Path) -> dict[str, str] | None:
    """Load wallet pin metadata if present and valid."""
    pin_path = resolve_wallet_pin_path(path)
    if not pin_path.exists():
        return None
    try:
        payload = json.loads(pin_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WalletBackendError(f"Wallet pin file is malformed: {pin_path}") from exc
    if not isinstance(payload, dict):
        raise WalletBackendError(f"Wallet pin file is malformed: {pin_path}")
    if payload.get("kind") != WALLET_ADDRESS_PIN_KIND:
        raise WalletBackendError(f"Wallet pin file kind is invalid: {pin_path}")
    if int(payload.get("version") or 0) != WALLET_ADDRESS_PIN_VERSION:
        raise WalletBackendError(f"Wallet pin file version is invalid: {pin_path}")
    address = str(payload.get("address") or "").strip()
    network = str(payload.get("network") or "").strip().lower()
    if not address or not network:
        raise WalletBackendError(f"Wallet pin file is incomplete: {pin_path}")
    return {
        "address": address,
        "network": network,
        "path": str(pin_path),
    }


def write_wallet_pin(path: Path, *, address: str, network: str) -> dict[str, str]:
    """Persist the expected wallet address for later mismatch checks."""
    payload = {
        "kind": WALLET_ADDRESS_PIN_KIND,
        "version": WALLET_ADDRESS_PIN_VERSION,
        "address": address,
        "network": network.strip().lower(),
        "wallet_file": path.name,
    }
    pin_path = resolve_wallet_pin_path(path)
    pin_path.parent.mkdir(parents=True, exist_ok=True)
    pin_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pin_path.chmod(0o600)
    return {
        "address": address,
        "network": payload["network"],
        "path": str(pin_path),
    }


def ensure_wallet_pin(path: Path, *, address: str, network: str) -> dict[str, str]:
    """Ensure the wallet pin exists and matches the expected address."""
    expected_network = network.strip().lower()
    existing = load_wallet_pin(path)
    if existing is None:
        return write_wallet_pin(path, address=address, network=expected_network)
    if existing["network"] != expected_network:
        raise WalletBackendError(
            f"Wallet pin network mismatch for {path}: expected {expected_network}, found {existing['network']}."
        )
    if existing["address"] != address:
        raise WalletBackendError(
            f"Wallet address mismatch for {path}: pinned {existing['address']}, derived {address}."
        )
    return existing


def refuse_recreation_if_pinned(path: Path, *, network: str) -> None:
    """Refuse to recreate a wallet when a mainnet address is already pinned."""
    expected_network = network.strip().lower()
    if expected_network != "mainnet" or not refuse_mainnet_wallet_recreation():
        return
    existing = load_wallet_pin(path)
    if existing is None:
        return
    raise WalletBackendError(
        "Refusing to create a new mainnet wallet because a pinned wallet address already exists "
        f"for {path}. Restore the original wallet file for {existing['address']} instead of creating a new one."
    )


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

    refuse_recreation_if_pinned(path, network=settings.solana_network)
    created = create_solana_wallet_file(path)
    write_wallet_pin(path, address=created["address"], network=settings.solana_network)
    return created


def describe_bootstrap() -> dict[str, str | bool]:
    """Return the effective bootstrap configuration for installer/runtime usage."""
    from agent_wallet.config import (
        default_solana_wallet_path,
        resolve_solana_rpc_url,
        resolve_solana_rpc_urls,
        settings,
    )

    configured_path = settings.solana_agent_keypair_path.strip()
    path = Path(configured_path).expanduser() if configured_path else default_solana_wallet_path(settings.solana_network)
    return {
        "backend": settings.agent_wallet_backend,
        "network": settings.solana_network,
        "rpc_url": resolve_solana_rpc_url(settings.solana_network, settings.solana_rpc_url),
        "rpc_urls": resolve_solana_rpc_urls(
            settings.solana_network,
            settings.solana_rpc_url,
            settings.solana_rpc_urls,
        ),
        "auto_create_wallet": settings.solana_auto_create_wallet,
        "keypair_path": str(path),
        "sign_only": settings.agent_wallet_sign_only,
    }
