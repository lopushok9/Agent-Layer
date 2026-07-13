"""Configuration for agent wallet backends."""

import hashlib
import os
from pathlib import Path
from typing import Iterator

from pydantic_settings import BaseSettings

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVIDER_GATEWAY_URL = "https://agent-layer-production.up.railway.app"


class Settings(BaseSettings):
    agent_wallet_backend: str = "none"
    agent_wallet_sign_only: bool = False
    agent_wallet_boot_key: str = ""
    agent_wallet_boot_key_file: str = ""
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
    provider_gateway_url: str = DEFAULT_PROVIDER_GATEWAY_URL
    provider_gateway_bearer_token: str = ""
    provider_gateway_rpc_provider: str = "auto"
    solana_swap_provider: str = "auto"
    wdk_btc_service_url: str = "http://127.0.0.1:8080"
    wdk_btc_wallet_id: str = ""
    wdk_btc_account_index: int = 0
    wdk_evm_service_url: str = "http://127.0.0.1:8081"
    wdk_evm_wallet_id: str = ""
    wdk_evm_account_index: int = 0

    jupiter_api_base_url: str = "https://lite-api.jup.ag/swap/v1"
    jupiter_swap_v2_api_base_url: str = "https://api.jup.ag/swap/v2"
    jupiter_ultra_api_base_url: str = "https://lite-api.jup.ag/ultra/v1"
    jupiter_price_api_base_url: str = "https://lite-api.jup.ag/price/v3"
    jupiter_token_search_api_base_url: str = "https://lite-api.jup.ag/tokens/v2"
    jupiter_api_key: str = ""
    lifi_api_base_url: str = "https://li.quest/v1"
    lifi_api_key: str = ""
    lifi_integrator: str = "openclaw"
    lifi_default_deny_bridges: str = "mayan"
    flash_api_base_url: str = ""
    flash_sdk_bridge_command: str = ""
    flash_sdk_bridge_mode: str = "mock"
    flash_sdk_bridge_timeout_seconds: float = 20.0
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


def reload_settings() -> Settings:
    """Reload settings from the current environment without changing object identity."""
    refreshed = Settings()
    for field_name in Settings.model_fields:
        setattr(settings, field_name, getattr(refreshed, field_name))
    clear_secret_caches()
    return settings


def normalize_solana_network(network: str | None) -> str:
    """Canonicalize supported Solana network names and reject test clusters."""
    normalized = str(network or "").strip().lower() or "mainnet"
    aliases = {
        "mainnet-beta": "mainnet",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"devnet", "testnet"}:
        from agent_wallet.wallet_layer.base import WalletBackendError

        raise WalletBackendError(
            "Solana devnet/testnet are no longer supported by agent-wallet. "
            "Use mainnet or remove the Solana network override."
        )
    if normalized != "mainnet":
        from agent_wallet.wallet_layer.base import WalletBackendError

        raise WalletBackendError(
            f"Unsupported Solana network: {normalized}. Only mainnet is supported."
        )
    return "mainnet"


def normalize_evm_network(network: str | None) -> str:
    """Canonicalize supported EVM network names and reject testnets."""
    normalized = str(network or "").strip().lower() or "ethereum"
    aliases = {
        "mainnet": "ethereum",
        "eth": "ethereum",
        "eth-mainnet": "ethereum",
        "base-mainnet": "base",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"sepolia", "base-sepolia", "base_sepolia"}:
        from agent_wallet.wallet_layer.base import WalletBackendError

        raise WalletBackendError(
            "EVM testnets are no longer supported by agent-wallet. Use ethereum, base, or robinhood."
        )
    if normalized not in {"ethereum", "base", "robinhood"}:
        from agent_wallet.wallet_layer.base import WalletBackendError

        raise WalletBackendError(
            f"Unsupported EVM network: {normalized}. Use ethereum, base, or robinhood."
        )
    return normalized


def normalize_btc_network(network: str | None) -> str:
    """Canonicalize supported BTC network names and reject non-mainnet chains."""
    normalized = str(network or "").strip().lower() or "bitcoin"
    aliases = {
        "mainnet": "bitcoin",
        "btc": "bitcoin",
        "bitcoin-mainnet": "bitcoin",
        "bitcoin_mainnet": "bitcoin",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"testnet", "regtest"}:
        from agent_wallet.wallet_layer.base import WalletBackendError

        raise WalletBackendError(
            "Bitcoin testnet/regtest are no longer supported by agent-wallet. Use bitcoin."
        )
    if normalized != "bitcoin":
        from agent_wallet.wallet_layer.base import WalletBackendError

        raise WalletBackendError(
            f"Unsupported Bitcoin network: {normalized}. Only bitcoin is supported."
        )
    return "bitcoin"


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
    normalized_network = normalize_solana_network(network)
    return resolve_openclaw_home() / "wallets" / f"solana-{normalized_network}-agent.json"


def resolve_solana_rpc_url(network: str, configured: str) -> str:
    """Resolve the effective Solana RPC URL from network + optional override."""
    normalized_network = normalize_solana_network(network)
    if configured.strip():
        return configured.strip()

    mapping = {
        "mainnet": "https://api.mainnet-beta.solana.com",
    }
    return mapping.get(normalized_network, mapping["mainnet"])


def resolve_solana_rpc_urls(
    network: str,
    configured: str,
    configured_list: str = "",
) -> list[str]:
    """Resolve the ordered list of Solana RPC URLs to try."""
    normalized_network = normalize_solana_network(network)
    candidates: list[str] = []
    for raw in (configured_list or "").split(","):
        value = raw.strip()
        if value and value not in candidates:
            candidates.append(value)

    primary = resolve_solana_rpc_url(normalized_network, configured)
    if primary and primary not in candidates:
        candidates.insert(0, primary)

    official = resolve_solana_rpc_url(normalized_network, "")
    if official and official not in candidates:
        candidates.append(official)

    return candidates


def _build_provider_gateway_rpc_url(base_url: str, provider: str, network: str) -> str:
    normalized_network = normalize_solana_network(network)
    return f"gateway::{provider}::{normalized_network}::{base_url.rstrip('/')}/v1/rpc"


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
    normalized_network = normalize_solana_network(network)
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
            "rpc_urls": resolve_solana_rpc_urls(normalized_network, env_primary, env_list),
        }
    if env_list:
        official = resolve_solana_rpc_url(normalized_network, "")
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
        }
        alchemy_base = alchemy_base_by_network.get(normalized_network)
        if alchemy_base:
            return {
                "mode": "user_direct",
                "provider": "alchemy",
                "transport": "direct",
                "rpc_urls": resolve_solana_rpc_urls(
                    normalized_network,
                    f"{alchemy_base}/{alchemy_key}",
                    "",
                ),
            }

    helius_key = os.getenv("HELIUS_API_KEY", settings.helius_api_key).strip()
    if helius_key:
        helius_base_by_network = {
            "mainnet": "https://mainnet.helius-rpc.com/",
        }
        helius_base = helius_base_by_network.get(normalized_network)
        if helius_base:
            return {
                "mode": "user_direct",
                "provider": "helius",
                "transport": "direct",
                "rpc_urls": resolve_solana_rpc_urls(
                    normalized_network,
                    f"{helius_base}?api-key={helius_key}",
                    "",
                ),
            }

    if normalized_network == "mainnet" and (mode == "shared_proxy" or (mode == "auto" and gateway_url)):
        if gateway_url:
            return {
                "mode": "shared_proxy",
                "provider": gateway_provider,
                "transport": "proxy",
                "rpc_urls": [
                    _build_provider_gateway_rpc_url(
                        gateway_url,
                        gateway_provider,
                        normalized_network,
                    )
                ],
            }

    return {
        "mode": "public_fallback",
        "provider": "official",
        "transport": "direct",
        "rpc_urls": resolve_solana_rpc_urls(normalized_network, configured, configured_list),
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
    normalize_solana_network(network)

    if requested == "jupiter":
        return {"provider": "jupiter", "transport": "direct"}

    return {"provider": "jupiter", "transport": "direct"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def envelope_kdf_migration_enabled() -> bool:
    """Whether an explicit read may migrate argon2id envelopes with backups.

    Disabled by default so normal reads never change storage or break rollback
    to a pre-HKDF runtime. Opt in with AGENT_WALLET_ENVELOPE_KDF_MIGRATION=1.
    """
    return _env_bool("AGENT_WALLET_ENVELOPE_KDF_MIGRATION", False)


_boot_key_keystore_cache: dict[tuple[str, str, str], str] = {}
_boot_key_validation_cache: dict[tuple[str, str, int, int], bool] = {}


def clear_secret_caches() -> None:
    """Reset all process-local secret-resolution caches.

    Covers the memoized keystore backend, the boot key read from the OS
    keystore, unsealed secrets, and derived envelope keys. Wired into
    ``reload_settings`` so config reloads always observe fresh state; call it
    directly in tests that rotate keystore contents in-process.
    """
    _boot_key_keystore_cache.clear()
    _boot_key_validation_cache.clear()
    from agent_wallet.keystore import clear_keystore_cache

    clear_keystore_cache()
    from agent_wallet.sealed_keys import clear_unseal_cache

    clear_unseal_cache()
    from agent_wallet.encrypted_storage import clear_derived_key_cache

    clear_derived_key_cache()


def read_boot_key_from_keystore() -> str:
    """Read the boot key from the OS keystore. Never raises; '' on any failure.

    Successful (non-empty) reads are memoized per keystore service for the
    process lifetime — every uncached read costs a subprocess call.
    """
    try:
        from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore

        cache_key = (
            os.getenv("AGENT_WALLET_KEYSTORE_BACKEND", "auto").strip().lower(),
            os.getenv("AGENT_WALLET_KEYSTORE_SERVICE", "").strip(),
            str(resolve_openclaw_home().resolve()),
        )
        cached = _boot_key_keystore_cache.get(cache_key)
        if cached:
            return cached
        value = resolve_keystore().get(BOOT_KEY_ITEM)
        text = value.strip() if isinstance(value, str) else ""
        if text:
            _boot_key_keystore_cache[cache_key] = text
        return text
    except Exception:
        return ""


def _read_boot_key_file(path_value: str) -> str:
    if not path_value.strip():
        return ""
    try:
        return Path(path_value).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _boot_key_candidates() -> Iterator[tuple[str, str]]:
    seen: set[str] = set()

    def candidate(source: str, value: str) -> tuple[str, str] | None:
        if not value or value in seen:
            return None
        seen.add(value)
        return source, value

    for item in (
        candidate("environment", os.getenv("AGENT_WALLET_BOOT_KEY", "").strip()),
        candidate("runtime_env", settings.agent_wallet_boot_key.strip()),
    ):
        if item:
            yield item

    keystore_item = candidate("keystore", read_boot_key_from_keystore())
    if keystore_item:
        yield keystore_item

    configured_file = os.getenv(
        "AGENT_WALLET_BOOT_KEY_FILE", settings.agent_wallet_boot_key_file
    ).strip()
    configured_item = candidate("configured_file", _read_boot_key_file(configured_file))
    if configured_item:
        yield configured_item

    default_file = resolve_openclaw_home() / "agent-wallet-runtime" / "boot-key"
    if not configured_file or Path(configured_file).expanduser() != default_file:
        default_item = candidate("default_file", _read_boot_key_file(str(default_file)))
        if default_item:
            yield default_item


def _boot_key_unlocks_sealed_file(boot_key: str) -> bool | None:
    sealed_path = resolve_openclaw_home() / "sealed_keys.json"
    try:
        stat = sealed_path.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return False

    cache_key = (boot_key, str(sealed_path), stat.st_mtime_ns, stat.st_size)
    cached = _boot_key_validation_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from agent_wallet.sealed_keys import unseal_keys

        unseal_keys(boot_key)
        valid = True
    except Exception:
        valid = False
    if len(_boot_key_validation_cache) >= 8:
        _boot_key_validation_cache.clear()
    _boot_key_validation_cache[cache_key] = valid
    return valid


def _resolve_boot_key_candidate() -> tuple[str, str, bool, list[str], bool]:
    rejected: list[str] = []
    for source, value in _boot_key_candidates():
        verified = _boot_key_unlocks_sealed_file(value)
        if verified is not False:
            return value, source, verified is True, rejected, bool(rejected)
        rejected.append(source)
    return "", "none", False, rejected, len(rejected) > 1


def resolve_boot_key() -> str:
    """Resolve a boot key, verifying candidates against sealed secrets when present.

    Precedence remains compatible with legacy installs:
      1. AGENT_WALLET_BOOT_KEY env / settings override
      2. OS keystore (the hardened path)
      3. AGENT_WALLET_BOOT_KEY_FILE / boot-key file (legacy)

    A stale higher-priority candidate cannot mask a lower-priority key that
    actually unlocks ``sealed_keys.json``.
    """
    return _resolve_boot_key_candidate()[0]


def resolve_boot_key_for_installer() -> str:
    """Stable installer bridge; older runtimes lack this symbol and use JS fallback."""
    return resolve_boot_key()


def boot_key_resolution_status() -> dict[str, object]:
    """Return non-secret diagnostics for doctor/install reporting."""
    from agent_wallet.keystore import keystore_backend_status

    value, source, verified, rejected, conflict = _resolve_boot_key_candidate()
    fingerprint = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else None
    return {
        "available": bool(value),
        "source": source,
        "sealed_keys_verified": verified,
        "conflict_detected": conflict,
        "rejected_sources": rejected,
        "fingerprint": fingerprint,
        "keystore": keystore_backend_status(),
    }


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


def resolve_evm_wallet_password() -> str:
    """Resolve the local EVM vault password from env or the sealed secret store."""
    direct = os.getenv("WDK_EVM_WALLET_PASSWORD", "").strip()
    if direct:
        return direct
    return _resolve_sealed_secret(
        "wdk_evm_wallet_password",
        "evm_wallet_password",
    )


def resolve_btc_wallet_password() -> str:
    """Resolve the local BTC vault password from env or the sealed secret store."""
    direct = os.getenv("WDK_BTC_WALLET_PASSWORD", "").strip()
    if direct:
        return direct
    return _resolve_sealed_secret(
        "wdk_btc_wallet_password",
        "btc_wallet_password",
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
