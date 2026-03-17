"""Configuration for agent wallet backends."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    agent_wallet_backend: str = "none"
    agent_wallet_sign_only: bool = False
    agent_wallet_master_key: str = ""
    agent_wallet_approval_secret: str = ""
    agent_wallet_approval_ttl_seconds: int = 600
    agent_wallet_per_user_key_derivation: bool = False
    agent_wallet_encrypt_user_wallets: bool = True
    agent_wallet_migrate_plaintext_user_wallets: bool = True
    agent_wallet_refuse_mainnet_wallet_recreation: bool = True
    agent_wallet_require_encrypted_mainnet: bool = True
    agent_wallet_max_per_tx_sol: float = 0
    agent_wallet_max_hourly_sol: float = 0
    agent_wallet_max_daily_sol: float = 0
    agent_wallet_max_txs_per_minute: int = 0

    solana_network: str = "mainnet"
    solana_rpc_url: str = ""
    solana_rpc_urls: str = ""
    solana_commitment: str = "confirmed"
    solana_auto_create_wallet: bool = False
    solana_agent_public_key: str = ""
    solana_agent_private_key: str = ""
    solana_agent_keypair_path: str = ""

    jupiter_api_base_url: str = "https://lite-api.jup.ag/swap/v1"
    jupiter_ultra_api_base_url: str = "https://lite-api.jup.ag/ultra/v1"
    jupiter_price_api_base_url: str = "https://lite-api.jup.ag/price/v3"
    jupiter_portfolio_api_base_url: str = "https://api.jup.ag/portfolio/v1"
    jupiter_lend_api_base_url: str = "https://api.jup.ag/lend/v1"
    jupiter_api_key: str = ""

    http_timeout: float = 10.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()


def resolve_openclaw_home() -> Path:
    """Resolve the default OpenClaw home directory for plugin state."""
    raw = os.getenv("OPENCLAW_HOME", "~/.openclaw")
    return Path(raw).expanduser()


def default_solana_wallet_path(network: str) -> Path:
    """Return the default keypair path for a Solana wallet."""
    return resolve_openclaw_home() / "wallets" / f"solana-{network}-agent.json"


def resolve_solana_rpc_url(network: str, configured: str) -> str:
    """Resolve the effective Solana RPC URL from network + optional override."""
    if configured.strip():
        return configured.strip()

    mapping = {
        "mainnet": "https://api.mainnet-beta.solana.com",
        "devnet": "https://api.devnet.solana.com",
        "testnet": "https://api.testnet.solana.com",
    }
    return mapping.get(network.strip().lower(), mapping["mainnet"])


def resolve_solana_rpc_urls(
    network: str,
    configured: str,
    configured_list: str = "",
) -> list[str]:
    """Resolve the ordered list of Solana RPC URLs to try."""
    candidates: list[str] = []
    for raw in (configured_list or "").split(","):
        value = raw.strip()
        if value and value not in candidates:
            candidates.append(value)

    primary = resolve_solana_rpc_url(network, configured)
    if primary and primary not in candidates:
        candidates.insert(0, primary)

    official = resolve_solana_rpc_url(network, "")
    if official and official not in candidates:
        candidates.append(official)

    return candidates


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_wallet_master_key() -> str:
    """Resolve the master key used for encrypting per-user wallet files."""
    return os.getenv("AGENT_WALLET_MASTER_KEY", settings.agent_wallet_master_key).strip()


def resolve_approval_secret() -> str:
    """Resolve the secret used for host-issued approval tokens."""
    return os.getenv("AGENT_WALLET_APPROVAL_SECRET", settings.agent_wallet_approval_secret).strip()


def use_encrypted_user_wallets() -> bool:
    """Return whether newly created per-user wallet files should be encrypted."""
    return _env_bool(
        "AGENT_WALLET_ENCRYPT_USER_WALLETS",
        settings.agent_wallet_encrypt_user_wallets,
    )


def allow_plaintext_user_wallet_migration() -> bool:
    """Return whether legacy plaintext per-user wallets may be migrated in place."""
    return _env_bool(
        "AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS",
        settings.agent_wallet_migrate_plaintext_user_wallets,
    )


def use_per_user_key_derivation() -> bool:
    """Return whether per-user wallet encryption keys are derived from the master key."""
    return _env_bool(
        "AGENT_WALLET_PER_USER_KEY_DERIVATION",
        settings.agent_wallet_per_user_key_derivation,
    )


def refuse_mainnet_wallet_recreation() -> bool:
    """Return whether mainnet wallets may be recreated when a pinned address exists."""
    return _env_bool(
        "AGENT_WALLET_REFUSE_MAINNET_WALLET_RECREATION",
        settings.agent_wallet_refuse_mainnet_wallet_recreation,
    )


def require_encrypted_mainnet() -> bool:
    """Return whether plaintext wallet creation is forbidden on mainnet."""
    return _env_bool(
        "AGENT_WALLET_REQUIRE_ENCRYPTED_MAINNET",
        settings.agent_wallet_require_encrypted_mainnet,
    )
