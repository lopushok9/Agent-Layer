"""Host-side onboarding helpers for wiring agent-wallet into OpenClaw."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_wallet.approval import issue_approval_token
from agent_wallet.btc_user_wallets import get_user_btc_wallet_binding
from agent_wallet.config import settings
from agent_wallet.models import OpenClawWalletSessionMetadata
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.plugin_bundle import build_openclaw_plugin_bundle
from agent_wallet.providers.wdk_btc_local import WdkBtcLocalClient
from agent_wallet.user_wallets import create_wallet_backend_for_user, ensure_user_solana_wallet, resolve_user_wallet_path
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError
from agent_wallet.wallet_layer.wdk_btc import WdkBtcLocalWalletBackend


@dataclass(slots=True)
class OpenClawWalletRuntimeContext:
    """Runtime-ready wallet context for a single OpenClaw user session."""

    user_id: str
    wallet_info: dict[str, str]
    created_now: bool
    backend: AgentWalletBackend
    adapter: OpenClawWalletAdapter
    plugin_bundle: dict[str, Any]

    def issue_execute_approval(
        self,
        *,
        tool_name: str,
        confirmation_summary: dict[str, Any],
        mainnet_confirmed: bool = False,
        ttl_seconds: int | None = None,
        issued_by: str = "host",
    ) -> str:
        """Issue a host approval token bound to an exact execute operation."""
        return issue_approval_token(
            tool_name=tool_name,
            network=str(getattr(self.backend, "network", "mainnet")),
            summary=confirmation_summary,
            mainnet_confirmed=mainnet_confirmed,
            ttl_seconds=ttl_seconds,
            issued_by=issued_by,
        )

    def session_metadata(self) -> OpenClawWalletSessionMetadata:
        """Return serializable metadata for host runtime/session storage."""
        tool_names = [tool["name"] for tool in self.plugin_bundle["tools"]]
        capabilities = self.backend.get_capabilities()
        return OpenClawWalletSessionMetadata(
            user_id=self.user_id,
            chain=capabilities.chain,
            network=str(getattr(self.backend, "network", "mainnet")),
            backend=self.backend.name,
            address=self.wallet_info["address"],
            wallet_path=self.wallet_info["path"],
            storage_format=self.wallet_info["storage_format"],
            created_now=self.created_now,
            sign_only=bool(getattr(self.backend, "sign_only", True)),
            rpc_provider_mode=getattr(self.backend, "rpc_provider_mode", None),
            rpc_provider=getattr(self.backend, "rpc_provider", None),
            rpc_transport=getattr(self.backend, "rpc_transport", None),
            swap_provider=getattr(self.backend, "swap_provider", None),
            swap_transport=getattr(self.backend, "swap_transport", None),
            tool_names=tool_names,
        )

    def serializable_bundle(self) -> dict[str, Any]:
        """Return the plugin bundle without the invoke callable for JSON/session transport."""
        return {
            "manifest": self.plugin_bundle["manifest"],
            "instructions": self.plugin_bundle["instructions"],
            "tools": self.plugin_bundle["tools"],
            "session": self.session_metadata().model_dump(),
        }


def onboard_openclaw_user_wallet(
    user_id: str,
    *,
    sign_only: bool | None = None,
    network: str | None = None,
    rpc_url: str | None = None,
) -> OpenClawWalletRuntimeContext:
    """Provision and assemble a runtime-ready wallet context for one OpenClaw user."""
    backend_name = settings.agent_wallet_backend.strip().lower()
    if backend_name in {"wdk_btc_local", "wdk-btc-local", "btc_local", "btc-local"}:
        service_url = settings.wdk_btc_service_url.strip()
        requested_network = (network or settings.solana_network).strip().lower() or "bitcoin"
        effective_network = "bitcoin" if requested_network == "mainnet" else requested_network
        binding: dict[str, Any] | None = None
        wallet_id = settings.wdk_btc_wallet_id.strip()
        if not service_url:
            raise WalletBackendError("wdk_btc_service_url is required for backend=wdk_btc_local.")
        if not wallet_id:
            binding = get_user_btc_wallet_binding(user_id, network=effective_network)
            wallet_id = str(binding.get("wallet_id") or "").strip()
        if not wallet_id:
            raise WalletBackendError(
                "wdk_btc_wallet_id is required for backend=wdk_btc_local, or create a bound user BTC wallet first."
            )

        client = WdkBtcLocalClient(service_url)
        wallet_meta = client.post_sync("/v1/btc/wallets/get", {"walletId": wallet_id})
        address_payload = client.post_sync(
            "/v1/btc/address/resolve",
            {
                "walletId": wallet_id,
                "accountIndex": settings.wdk_btc_account_index,
                "network": effective_network,
            },
        )
        backend = WdkBtcLocalWalletBackend(
            service_url=service_url,
            wallet_id=wallet_id,
            network=effective_network,
            account_index=settings.wdk_btc_account_index,
            sign_only=settings.agent_wallet_sign_only if sign_only is None else sign_only,
            address=str(address_payload.get("address") or "").strip() or None,
        )
        wallet_info = {
            "user_id": user_id,
            "address": str(address_payload.get("address") or (binding or {}).get("address") or ""),
            "path": f"{service_url}#walletId={wallet_id}",
            "storage_format": "local_vault",
            "key_scope": "host-managed",
            "wallet_id": wallet_id,
            "label": str(wallet_meta.get("label") or (binding or {}).get("label") or "BTC Wallet"),
        }
        adapter = OpenClawWalletAdapter(backend)
        plugin_bundle = build_openclaw_plugin_bundle(backend)
        return OpenClawWalletRuntimeContext(
            user_id=user_id,
            wallet_info=wallet_info,
            created_now=False,
            backend=backend,
            adapter=adapter,
            plugin_bundle=plugin_bundle,
        )

    wallet_path = resolve_user_wallet_path(user_id, network=network)
    created_now = not wallet_path.exists()
    wallet_info = ensure_user_solana_wallet(user_id, network=network)
    backend = create_wallet_backend_for_user(
        user_id,
        sign_only=sign_only,
        network=network,
        rpc_url=rpc_url,
    )
    adapter = OpenClawWalletAdapter(backend)
    plugin_bundle = build_openclaw_plugin_bundle(backend)
    return OpenClawWalletRuntimeContext(
        user_id=user_id,
        wallet_info=wallet_info,
        created_now=created_now,
        backend=backend,
        adapter=adapter,
        plugin_bundle=plugin_bundle,
    )
