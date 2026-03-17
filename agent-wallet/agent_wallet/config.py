"""Configuration for agent wallet backends."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    agent_wallet_backend: str = "none"
    agent_wallet_sign_only: bool = False
    agent_wallet_boot_key: str = ""
    agent_wallet_approval_ttl_seconds: int = 600
    agent_wallet_per_user_key_derivation: bool = True
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
    solana_agent_keypair_path: str = ""

    jupiter_api_base_url: str = "https://lite-api.jup.ag/swap/v1"
    jupiter_ultra_api_base_url: str = "https://lite-api.jup.ag/ultra/v1"
    jupiter_price_api_base_url: str = "https://lite-api.jup.ag/price/v3"
    jupiter_portfolio_api_base_url: str = "https://api.jup.ag/portfolio/v1"
    jupiter_lend_api_base_url: str = "https://api.jup.ag/lend/v1"
    jupiter_api_key: str = ""
    alchemy_api_key: str = ""
    helius_api_key: str = ""

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


def resolve_runtime_solana_rpc_urls(
    network: str,
    configured: str,
    configured_list: str = "",
) -> list[str]:
    """Resolve Solana RPC URLs with deployment env taking precedence over plugin config."""
    env_primary = os.getenv("SOLANA_RPC_URL", "").strip()
    env_list = os.getenv("SOLANA_RPC_URLS", "").strip()
    if env_primary:
        return resolve_solana_rpc_urls(
            network,
            env_primary,
            env_list,
        )
    if env_list:
        official = resolve_solana_rpc_url(network, "")
        candidates = [item.strip() for item in env_list.split(",") if item.strip()]
        if official and official not in candidates:
            candidates.append(official)
        return candidates
    alchemy_key = os.getenv("ALCHEMY_API_KEY", settings.alchemy_api_key).strip()
    if alchemy_key:
        alchemy_base_by_network = {
            "mainnet": "https://solana-mainnet.g.alchemy.com/v2",
            "devnet": "https://solana-devnet.g.alchemy.com/v2",
        }
        alchemy_base = alchemy_base_by_network.get(network.strip().lower())
        if alchemy_base:
            return resolve_solana_rpc_urls(
                network,
                f"{alchemy_base}/{alchemy_key}",
                "",
            )
    helius_key = os.getenv("HELIUS_API_KEY", settings.helius_api_key).strip()
    if helius_key:
        helius_base_by_network = {
            "mainnet": "https://mainnet.helius-rpc.com/",
            "devnet": "https://devnet.helius-rpc.com/",
        }
        helius_base = helius_base_by_network.get(network.strip().lower())
        if helius_base:
            return resolve_solana_rpc_urls(
                network,
                f"{helius_base}?api-key={helius_key}",
                "",
            )
    return resolve_solana_rpc_urls(network, configured, configured_list)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_boot_key() -> str:
    """Resolve the boot key used to unlock sealed secrets from disk."""
    return os.getenv("AGENT_WALLET_BOOT_KEY", settings.agent_wallet_boot_key).strip()


def _reject_legacy_runtime_secret_env(var_name: str) -> None:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return
    from agent_wallet.wallet_layer.base import WalletBackendError

    raise WalletBackendError(
        f"{var_name} is no longer supported for runtime secret loading. "
        "Store runtime secrets in ~/.openclaw/sealed_keys.json and provide AGENT_WALLET_BOOT_KEY instead."
    )


def _resolve_sealed_secret(*names: str) -> str:
    boot_key = resolve_boot_key()
    if not boot_key:
        return ""
    from agent_wallet.sealed_keys import unseal_keys

    secrets = unseal_keys(boot_key)
    for name in names:
        value = secrets.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resolve_wallet_master_key() -> str:
    """Resolve the master key used for encrypting per-user wallet files."""
    _reject_legacy_runtime_secret_env("AGENT_WALLET_MASTER_KEY")
    return _resolve_sealed_secret("master_key", "masterKey")


def resolve_approval_secret() -> str:
    """Resolve the secret used for host-issued approval tokens."""
    _reject_legacy_runtime_secret_env("AGENT_WALLET_APPROVAL_SECRET")
    return _resolve_sealed_secret("approval_secret", "approvalSecret")


def resolve_solana_private_key() -> str:
    """Resolve the Solana signing key from env/config or the sealed secret store."""
    _reject_legacy_runtime_secret_env("SOLANA_AGENT_PRIVATE_KEY")
    return _resolve_sealed_secret(
        "solana_agent_private_key",
        "private_key",
        "privateKey",
    )


def use_encrypted_user_wallets() -> bool:
    """Per-user wallet files are always encrypted in the hardened runtime."""
    return True


def allow_plaintext_user_wallet_migration() -> bool:
    """Return whether legacy plaintext per-user wallets may be migrated in place."""
    return _env_bool(
        "AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS",
        settings.agent_wallet_migrate_plaintext_user_wallets,
    )


def use_per_user_key_derivation() -> bool:
    """Per-user wallet encryption keys are always derived from the master key."""
    return True


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
