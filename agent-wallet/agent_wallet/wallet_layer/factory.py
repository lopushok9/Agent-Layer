"""Factory helpers for agent wallet backends."""

from __future__ import annotations

from pathlib import Path

from agent_wallet.bootstrap import ensure_solana_wallet_ready
from agent_wallet.encrypted_storage import load_wallet_secret_material
from agent_wallet.config import resolve_solana_rpc_url, settings
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError
from agent_wallet.wallet_layer.solana import SolanaLocalKeypairSigner, SolanaWalletBackend


def _load_keypair_material() -> str | None:
    secret = settings.solana_agent_private_key.strip()
    if secret:
        return secret

    ensured = ensure_solana_wallet_ready()
    keypair_path = settings.solana_agent_keypair_path.strip() or (ensured["path"] if ensured else "")
    if not keypair_path:
        return None

    path = Path(keypair_path).expanduser()
    if not path.exists():
        raise WalletBackendError(
            f"Configured Solana keypair path does not exist: {path}"
        )
    secret_material, _ = load_wallet_secret_material(path)
    return secret_material.strip()


def create_wallet_backend() -> AgentWalletBackend | None:
    """Build the configured wallet backend instance."""
    backend = settings.agent_wallet_backend.strip().lower()
    if not backend or backend == "none":
        return None

    if backend in {"solana", "solana_local", "solana-local"}:
        secret_material = _load_keypair_material()
        signer = (
            SolanaLocalKeypairSigner.from_secret_material(secret_material)
            if secret_material
            else None
        )
        configured_address = settings.solana_agent_public_key.strip() or None
        return SolanaWalletBackend(
            rpc_url=resolve_solana_rpc_url(settings.solana_network, settings.solana_rpc_url),
            commitment=settings.solana_commitment,
            network=settings.solana_network,
            signer=signer,
            address=configured_address,
            sign_only=settings.agent_wallet_sign_only,
        )

    raise WalletBackendError(
        f"Unsupported agent wallet backend: {backend}. "
        "Supported values: none, solana_local."
    )
