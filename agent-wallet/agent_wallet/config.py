"""Configuration for agent wallet backends."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


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
    solana_rpc_provider_mode: str = "auto"
    solana_commitment: str = "confirmed"
    solana_auto_create_wallet: bool = False
    solana_agent_public_key: str = ""
    solana_agent_keypair_path: str = ""
    provider_gateway_url: str = ""
    provider_gateway_bearer_token: str = ""
    provider_gateway_rpc_provider: str = "auto"
    solana_swap_provider: str = "auto"

    jupiter_api_base_url: str = "https://lite-api.jup.ag/swap/v1"
    jupiter_ultra_api_base_url: str = "https://lite-api.jup.ag/ultra/v1"
    jupiter_price_api_base_url: str = "https://lite-api.jup.ag/price/v3"
    jupiter_portfolio_api_base_url: str = "https://api.jup.ag/portfolio/v1"
    jupiter_lend_api_base_url: str = "https://api.jup.ag/lend/v1"
    jupiter_api_key: str = ""
    kamino_api_base_url: str = "https://api.kamino.finance"
    kamino_program_id: str = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
    alchemy_api_key: str = ""
    helius_api_key: str = ""

    http_timeout: float = 10.0

    model_config = {
        "env_file": str(PACKAGE_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()


def _normalize_provider_mode(value: str | None) -> str:
    mode = (value or "").strip().lower()
    if not mode:
        return "auto"
    aliases = {
        "direct": "user_direct",
        "proxy": "shared_proxy",
        "shared": "shared_proxy",
    }
    mode = aliases.get(mode, mode)
    if mode not in {"auto", "user_direct", "shared_proxy"}:
        return "auto"
    return mode


def _normalize_rpc_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    if not provider:
        return "auto"
    if provider not in {"auto", "shared", "helius", "alchemy"}:
        return "auto"
    return provider


def _normalize_swap_provider(value: str | None) -> str:
    provider = (value or "").strip().lower()
    if not provider:
        return "auto"
    aliases = {
        "proxy": "jupiter",
        "shared": "jupiter",
        "bags": "jupiter",
    }
    provider = aliases.get(provider, provider)
    if provider not in {"auto", "jupiter"}:
        return "auto"
    return provider


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


def _build_provider_gateway_rpc_url(base_url: str, provider: str, network: str) -> str:
    return f"gateway::{provider}::{network.strip().lower()}::{base_url.rstrip('/')}/v1/rpc"


def resolve_runtime_solana_rpc_config(
    network: str,
    configured: str,
    configured_list: str = "",
) -> dict[str, object]:
    """Resolve Solana RPC transport config for one runtime invocation.

    Preference order:
    1. explicit direct RPC env/config
    2. user-provided provider API keys
    3. shared proxy gateway
    4. public official fallback
    """
    mode = _normalize_provider_mode(
        os.getenv("SOLANA_RPC_PROVIDER_MODE", settings.solana_rpc_provider_mode)
    )
    gateway_url = os.getenv("PROVIDER_GATEWAY_URL", settings.provider_gateway_url).strip()
    gateway_provider = _normalize_rpc_provider(
        os.getenv("PROVIDER_GATEWAY_RPC_PROVIDER", settings.provider_gateway_rpc_provider)
    )

    env_primary = os.getenv("SOLANA_RPC_URL", "").strip()
    env_list = os.getenv("SOLANA_RPC_URLS", "").strip()
    if env_primary:
        return {
            "mode": "user_direct",
            "provider": "custom",
            "transport": "direct",
            "rpc_urls": resolve_solana_rpc_urls(network, env_primary, env_list),
        }
    if env_list:
        official = resolve_solana_rpc_url(network, "")
        candidates = [item.strip() for item in env_list.split(",") if item.strip()]
        if official and official not in candidates:
            candidates.append(official)
        return {
            "mode": "user_direct",
            "provider": "custom",
            "transport": "direct",
            "rpc_urls": candidates,
        }

    alchemy_key = os.getenv("ALCHEMY_API_KEY", settings.alchemy_api_key).strip()
    if alchemy_key:
        alchemy_base_by_network = {
            "mainnet": "https://solana-mainnet.g.alchemy.com/v2",
            "devnet": "https://solana-devnet.g.alchemy.com/v2",
        }
        alchemy_base = alchemy_base_by_network.get(network.strip().lower())
        if alchemy_base:
            return {
                "mode": "user_direct",
                "provider": "alchemy",
                "transport": "direct",
                "rpc_urls": resolve_solana_rpc_urls(
                    network,
                    f"{alchemy_base}/{alchemy_key}",
                    "",
                ),
            }

    helius_key = os.getenv("HELIUS_API_KEY", settings.helius_api_key).strip()
    if helius_key:
        helius_base_by_network = {
            "mainnet": "https://mainnet.helius-rpc.com/",
            "devnet": "https://devnet.helius-rpc.com/",
        }
        helius_base = helius_base_by_network.get(network.strip().lower())
        if helius_base:
            return {
                "mode": "user_direct",
                "provider": "helius",
                "transport": "direct",
                "rpc_urls": resolve_solana_rpc_urls(
                    network,
                    f"{helius_base}?api-key={helius_key}",
                    "",
                ),
            }

    if network.strip().lower() == "mainnet" and (mode == "shared_proxy" or (mode == "auto" and gateway_url)):
        if gateway_url:
            return {
                "mode": "shared_proxy",
                "provider": gateway_provider,
                "transport": "proxy",
                "rpc_urls": [_build_provider_gateway_rpc_url(gateway_url, gateway_provider, network)],
            }

    return {
        "mode": "public_fallback",
        "provider": "official",
        "transport": "direct",
        "rpc_urls": resolve_solana_rpc_urls(network, configured, configured_list),
    }


def resolve_runtime_solana_rpc_urls(
    network: str,
    configured: str,
    configured_list: str = "",
) -> list[str]:
    """Resolve Solana RPC URLs with deployment env taking precedence over plugin config."""
    payload = resolve_runtime_solana_rpc_config(network, configured, configured_list)
    return list(payload["rpc_urls"])


def resolve_runtime_solana_swap_config(network: str) -> dict[str, str]:
    """Resolve the effective Solana swap provider for one runtime invocation.

    Preference order:
    1. explicit swap provider override
    2. direct Jupiter
    """
    requested = _normalize_swap_provider(
        os.getenv("SOLANA_SWAP_PROVIDER", settings.solana_swap_provider)
    )
    normalized_network = network.strip().lower()

    if normalized_network != "mainnet":
        return {"provider": "jupiter", "transport": "direct"}

    if requested == "jupiter":
        return {"provider": "jupiter", "transport": "direct"}

    return {"provider": "jupiter", "transport": "direct"}


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
