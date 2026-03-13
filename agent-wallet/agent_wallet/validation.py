"""Validation helpers for wallet backends."""

from agent_wallet.wallet_layer.base58 import b58decode


def validate_solana_address(address: str) -> str:
    """Validate a Solana wallet address via base58 decode + 32-byte length."""
    value = address.strip()
    if not value:
        raise ValueError(
            "Solana wallet address is required. "
            "Example: 7vfCXTUXx5W9aSg6YpbbMHDLecxB2S7RMyCV2wAPYpQp"
        )
    try:
        decoded = b58decode(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid Solana address: '{address}'. "
            "Expected a base58-encoded public key."
        ) from exc
    if len(decoded) != 32:
        raise ValueError(
            f"Invalid Solana address: '{address}'. "
            "Expected a 32-byte base58 public key."
        )
    return value


def validate_solana_mint(address: str) -> str:
    """Validate a Solana mint address. Same shape as a public key."""
    return validate_solana_address(address)
