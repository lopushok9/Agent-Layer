"""Pydantic models for wallet backend state."""

from typing import Any

from pydantic import BaseModel


class AgentWalletCapabilities(BaseModel):
    backend: str
    chain: str
    custody_model: str
    sign_only: bool
    has_signer: bool
    can_get_address: bool = True
    can_get_balance: bool = True
    can_sign_message: bool = False
    can_sign_transaction: bool = False
    can_send_transaction: bool = False
    external_dependencies: list[str] = []


class SolanaWalletState(BaseModel):
    chain: str = "solana"
    backend: str
    address: str | None = None
    balance_native: float | None = None
    sign_only: bool = True
    has_signer: bool = False
    source: str = "solana-rpc"


class AgentToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True
    requires_explicit_user_intent: bool = False
    risk_level: str = "low"


class AgentToolResult(BaseModel):
    tool: str
    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class OpenClawWalletSessionMetadata(BaseModel):
    user_id: str
    chain: str = "solana"
    network: str
    backend: str
    address: str
    wallet_path: str
    storage_format: str
    created_now: bool
    sign_only: bool
    tool_names: list[str]
