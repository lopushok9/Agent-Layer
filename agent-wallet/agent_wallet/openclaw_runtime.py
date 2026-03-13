"""Host-side onboarding helpers for wiring agent-wallet into OpenClaw."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_wallet.models import OpenClawWalletSessionMetadata
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.plugin_bundle import build_openclaw_plugin_bundle
from agent_wallet.user_wallets import create_wallet_backend_for_user, ensure_user_solana_wallet, resolve_user_wallet_path
from agent_wallet.wallet_layer.base import AgentWalletBackend


@dataclass(slots=True)
class OpenClawWalletRuntimeContext:
    """Runtime-ready wallet context for a single OpenClaw user session."""

    user_id: str
    wallet_info: dict[str, str]
    created_now: bool
    backend: AgentWalletBackend
    adapter: OpenClawWalletAdapter
    plugin_bundle: dict[str, Any]

    def session_metadata(self) -> OpenClawWalletSessionMetadata:
        """Return serializable metadata for host runtime/session storage."""
        tool_names = [tool["name"] for tool in self.plugin_bundle["tools"]]
        return OpenClawWalletSessionMetadata(
            user_id=self.user_id,
            network=str(getattr(self.backend, "network", "mainnet")),
            backend=self.backend.name,
            address=self.wallet_info["address"],
            wallet_path=self.wallet_info["path"],
            storage_format=self.wallet_info["storage_format"],
            created_now=self.created_now,
            sign_only=bool(getattr(self.backend, "sign_only", True)),
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
