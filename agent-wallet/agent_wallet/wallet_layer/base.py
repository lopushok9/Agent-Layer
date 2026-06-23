"""Shared primitives for agent wallet backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
import time
from dataclasses import asdict, dataclass, field
from typing import Any


class WalletBackendError(Exception):
    """Wallet backend or signer error."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code).strip() if isinstance(code, str) and code.strip() else None
        self.details = dict(details) if isinstance(details, dict) else None


@dataclass(slots=True)
class WalletCapabilities:
    """Capability summary exposed by wallet backends."""

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
    external_dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentWalletBackend(ABC):
    """Abstract interface for chain-specific agent wallets."""

    name: str

    @abstractmethod
    async def get_address(self) -> str | None:
        """Return the wallet address if one is configured."""

    @abstractmethod
    async def get_balance(self, address: str | None = None) -> dict[str, Any]:
        """Return the wallet balance for the configured or provided address."""

    def with_network(self, network: str) -> "AgentWalletBackend":
        raise WalletBackendError(f"{self.name} does not support network overrides.")

    async def get_btc_transfer_history(
        self,
        *,
        direction: str = "all",
        limit: int = 10,
        skip: int = 0,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support BTC transfer history lookup.")

    async def get_btc_fee_rates(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support BTC fee-rate lookup.")

    async def get_btc_max_spendable(
        self,
        *,
        fee_rate: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support BTC max spendable lookup.")

    async def get_evm_token_balance(self, token_address: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM token balance lookup.")

    async def get_evm_network_info(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM network inspection.")

    async def get_evm_token_metadata(self, token_address: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM token metadata lookup.")

    async def get_evm_fee_rates(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM fee-rate lookup.")

    async def get_evm_transaction_receipt(self, tx_hash: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM transaction receipt lookup.")

    async def get_evm_swap_quote(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM swap quote lookup.")

    async def get_evm_aave_account(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Aave account lookup.")

    async def get_evm_aave_reserves(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Aave reserve lookup.")

    async def get_evm_aave_positions(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Aave positions lookup.")

    async def get_evm_lido_overview(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Lido overview lookup.")

    async def get_evm_lido_positions(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Lido positions lookup.")

    async def get_evm_lido_withdrawal_requests(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Lido withdrawal lookup.")

    async def get_evm_morpho_vaults(
        self,
        *,
        vault_address: str | None = None,
        limit: int | None = None,
        listed_only: bool = True,
        asset_address: str | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Morpho vault lookup.")

    async def get_evm_morpho_markets(
        self,
        *,
        market_id: str | None = None,
        limit: int | None = None,
        listed_only: bool = True,
        search: str | None = None,
        collateral_asset_address: str | None = None,
        loan_asset_address: str | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Morpho market lookup.")

    async def get_evm_morpho_positions(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Morpho positions lookup.")

    async def preview_evm_aave_operation(
        self,
        *,
        operation: str,
        token_address: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Aave previews.")

    async def send_evm_aave_operation(
        self,
        *,
        operation: str,
        token_address: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Aave operations.")

    async def preview_evm_lido_operation(
        self,
        *,
        operation: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Lido previews.")

    async def send_evm_lido_operation(
        self,
        *,
        operation: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Lido operations.")

    async def preview_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Lido withdrawal previews.")

    async def send_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Lido withdrawals.")

    async def preview_evm_morpho_vault_operation(
        self,
        *,
        operation: str,
        token_address: str,
        vault_address: str | None = None,
        vault_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Morpho vault previews.")

    async def send_evm_morpho_vault_operation(
        self,
        *,
        operation: str,
        token_address: str,
        vault_address: str | None = None,
        vault_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Morpho vault operations.")

    async def preview_evm_morpho_market_operation(
        self,
        *,
        operation: str,
        token_address: str,
        market_id: str | None = None,
        market_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Morpho market previews.")

    async def send_evm_morpho_market_operation(
        self,
        *,
        operation: str,
        token_address: str,
        market_id: str | None = None,
        market_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM Morpho market operations.")

    async def preview_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM swap previews.")

    async def send_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        expected_quote_fingerprint: str | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM swaps.")

    async def preview_evm_lifi_cross_chain_swap(
        self,
        *,
        token_in: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM LI.FI cross-chain swap previews.")

    async def send_evm_lifi_cross_chain_swap(
        self,
        *,
        token_in: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM LI.FI cross-chain swaps.")

    async def get_uniswap_swap_quote(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Uniswap swap quotes.")

    async def preview_uniswap_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Uniswap swap previews.")

    async def send_uniswap_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
        expected_quote_fingerprint: str | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Uniswap swaps.")

    async def preview_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM native transfer previews.")

    async def send_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM native transfers.")

    async def preview_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM token transfer previews.")

    async def send_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support EVM token transfers.")

    async def preview_btc_transfer(
        self,
        *,
        recipient: str,
        amount_sats: int,
        fee_rate: int | None = None,
        confirmation_target: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support BTC transfer previews.")

    async def send_btc_transfer(
        self,
        *,
        recipient: str,
        amount_sats: int,
        fee_rate: int | None = None,
        confirmation_target: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support BTC transfers.")

    async def get_portfolio(self, address: str | None = None) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support portfolio lookup.")

    async def get_lifi_supported_chains(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support LI.FI chain lookup.")

    async def get_lifi_quote(
        self,
        *,
        from_chain: str,
        to_chain: str,
        from_token: str,
        to_token: str,
        amount_in_raw: str,
        from_address: str | None = None,
        to_address: str | None = None,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support LI.FI quotes.")

    async def get_lifi_transfer_status(
        self,
        *,
        tx_hash: str,
        bridge: str | None = None,
        from_chain: str | None = None,
        to_chain: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support LI.FI transfer status lookup.")

    async def preview_solana_lifi_cross_chain_swap(
        self,
        *,
        input_token: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Solana-origin LI.FI swap previews.")

    async def execute_solana_lifi_cross_chain_swap(
        self,
        *,
        input_token: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Solana-origin LI.FI swaps.")

    async def get_token_prices(self, mints: list[str]) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support token price lookup.")

    async def get_staking_validators(
        self,
        limit: int = 20,
        include_delinquent: bool = False,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support staking validator lookup.")

    async def get_stake_account(self, stake_account: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support stake account lookup.")

    async def get_flash_trade_markets(
        self,
        pool_name: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade market lookup.")

    async def get_flash_trade_positions(
        self,
        owner: str | None = None,
        pool_name: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade position lookup.")

    async def preview_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade position-open previews.")

    async def preview_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade position-close previews.")

    async def prepare_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade position-open prepare.")

    async def prepare_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade position-close prepare.")

    async def execute_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade position-open execute.")

    async def execute_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Flash Trade position-close execute.")

    async def get_kamino_lend_markets(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino market lookup.")

    async def get_kamino_lend_market_reserves(self, market: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino reserve lookup.")

    async def get_kamino_lend_user_obligations(
        self,
        market: str,
        user: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino obligations lookup.")

    async def get_kamino_lend_user_rewards(self, user: str | None = None) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino rewards lookup.")

    async def get_kamino_open_positions(self, user: str | None = None) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino open position lookup.")

    async def preview_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino deposit previews.")

    async def prepare_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino deposit preparation.")

    async def execute_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino deposits.")

    async def preview_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino withdraw previews.")

    def _build_kamino_lend_intent_preview(
        self,
        base_preview: dict[str, Any],
        *,
        valid_for_seconds: int,
    ) -> dict[str, Any]:
        """Wrap a base Kamino lend preview into an intent approval preview.

        The intent binds approval to stable semantic parameters (owner, market,
        reserve, amount, obligation) instead of an ephemeral preview digest, so
        execute can re-derive the transaction server-side without the host having
        to round-trip the full preview payload back as _approved_preview.
        """
        if valid_for_seconds <= 0 or valid_for_seconds > 300:
            raise WalletBackendError("valid_for_seconds must be between 1 and 300.")
        try:
            can_send = bool(self.get_capabilities().can_send_transaction)
        except Exception:
            can_send = bool(base_preview.get("can_send"))
        return {
            "chain": "solana",
            "network": getattr(self, "network", "mainnet"),
            "mode": "intent_preview",
            "asset_type": "kamino-lend-intent",
            "kamino_operation": base_preview["asset_type"],
            "owner": base_preview["owner"],
            "market": base_preview["market"],
            "reserve": base_preview["reserve"],
            "amount_ui": base_preview["amount_ui"],
            "obligation_address": base_preview.get("obligation_address"),
            "obligation_options": base_preview.get("obligation_options", []),
            "requires_obligation_address": bool(base_preview.get("requires_obligation_address")),
            "reserve_info": base_preview.get("reserve_info"),
            "recipient_policy": "owner-only",
            "spend_policy": "exact-amount",
            "valid_for_seconds": valid_for_seconds,
            "valid_until_epoch_seconds": int(time.time()) + valid_for_seconds,
            "intent_note": (
                "This is an intent approval preview. Execute re-derives the Kamino "
                "transaction and only signs/sends if it remains within these approved parameters."
            ),
            "can_send": can_send,
            "sign_only": bool(getattr(self, "sign_only", False)),
            "source": "kamino-intent",
        }

    async def preview_kamino_lend_deposit_intent(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        valid_for_seconds: int = 120,
    ) -> dict[str, Any]:
        base = await self.preview_kamino_lend_deposit(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
        )
        return self._build_kamino_lend_intent_preview(base, valid_for_seconds=valid_for_seconds)

    async def preview_kamino_lend_withdraw_intent(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        valid_for_seconds: int = 120,
    ) -> dict[str, Any]:
        base = await self.preview_kamino_lend_withdraw(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
        )
        return self._build_kamino_lend_intent_preview(base, valid_for_seconds=valid_for_seconds)

    async def preview_kamino_lend_borrow_intent(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        valid_for_seconds: int = 120,
    ) -> dict[str, Any]:
        base = await self.preview_kamino_lend_borrow(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
        )
        return self._build_kamino_lend_intent_preview(base, valid_for_seconds=valid_for_seconds)

    async def preview_kamino_lend_repay_intent(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        valid_for_seconds: int = 120,
    ) -> dict[str, Any]:
        base = await self.preview_kamino_lend_repay(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
        )
        return self._build_kamino_lend_intent_preview(base, valid_for_seconds=valid_for_seconds)

    async def prepare_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino withdraw preparation.")

    async def execute_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino withdraws.")

    async def preview_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino borrow previews.")

    async def prepare_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino borrow preparation.")

    async def execute_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino borrows.")

    async def preview_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino repay previews.")

    async def prepare_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino repay preparation.")

    async def execute_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino repays.")

    async def preview_close_empty_token_accounts(
        self,
        limit: int = 8,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support empty token account previews.")

    async def close_empty_token_accounts(
        self,
        limit: int = 8,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support closing token accounts.")

    @abstractmethod
    def get_capabilities(self) -> WalletCapabilities:
        """Describe backend capabilities for the agent runtime."""

    async def sign_message(self, message: bytes | str) -> str:
        raise WalletBackendError(f"{self.name} does not support message signing.")

    async def preview_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support native transfer previews.")

    async def prepare_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support native transfer preparation.")

    async def send_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support sending native transfers.")

    async def preview_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support SPL transfer previews.")

    async def prepare_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support SPL transfer preparation.")

    async def send_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support SPL transfers.")

    async def preview_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 300,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support swap previews.")

    async def preview_swap_intent(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 300,
        minimum_output_amount_raw: int | None = None,
        max_fee_lamports: int | None = None,
        valid_for_seconds: int = 30,
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        preview = await self.preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        fee_summary = preview.get("fee_summary") if isinstance(preview.get("fee_summary"), dict) else {}
        network_fee_lamports = fee_summary.get("network_fee_lamports")
        if max_fee_lamports is None and isinstance(network_fee_lamports, int):
            max_fee_lamports = max(network_fee_lamports * 3, network_fee_lamports + 100_000)
        resolved_min_raw = minimum_output_amount_raw
        if resolved_min_raw is None and isinstance(preview.get("minimum_output_amount_raw"), int):
            resolved_min_raw = int(preview["minimum_output_amount_raw"])
        output_decimals = preview.get("output_decimals")
        minimum_output_amount_ui = preview.get("minimum_output_amount_ui")
        if resolved_min_raw is not None and isinstance(output_decimals, int):
            minimum_output_amount_ui = int(resolved_min_raw) / (10**output_decimals)
        return {
            "chain": preview.get("chain", "solana"),
            "network": preview.get("network", getattr(self, "network", "unknown")),
            "mode": "intent_preview",
            "asset_type": "solana-swap-intent",
            "owner": preview.get("owner"),
            "input_mint": preview.get("input_mint", input_mint),
            "output_mint": preview.get("output_mint", output_mint),
            "input_amount_ui": preview.get("input_amount_ui", amount_ui),
            "input_amount_raw": preview.get("input_amount_raw"),
            "minimum_output_amount_raw": resolved_min_raw,
            "minimum_output_amount_ui": minimum_output_amount_ui,
            "indicative_output_amount_ui": preview.get("estimated_output_amount_ui"),
            "indicative_output_amount_raw": preview.get("estimated_output_amount_raw"),
            "max_slippage_bps": slippage_bps,
            "slippage_bps": slippage_bps,
            "max_fee_lamports": max_fee_lamports,
            "valid_for_seconds": valid_for_seconds,
            "valid_until_epoch_seconds": int(time.time()) + valid_for_seconds,
            "max_attempts": max_attempts,
            "allowed_providers": ["jupiter-ultra", "jupiter-metis"],
            "recipient_policy": "owner-only",
            "spend_policy": "exact-input",
            "indicative_swap_provider": preview.get("swap_provider"),
            "indicative_fee_summary": fee_summary,
            "can_send": preview.get("can_send"),
            "sign_only": preview.get("sign_only"),
            "source": "swap-intent",
        }

    async def prepare_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 300,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support swap preparation.")

    async def prepare_swap_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.prepare_swap(
            input_mint=str(preview["input_mint"]),
            output_mint=str(preview["output_mint"]),
            amount_ui=float(preview["input_amount_ui"]),
            slippage_bps=int(preview.get("slippage_bps") or 300),
        )

    async def execute_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 300,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support swaps.")

    async def execute_swap_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.execute_swap(
            input_mint=str(preview["input_mint"]),
            output_mint=str(preview["output_mint"]),
            amount_ui=float(preview["input_amount_ui"]),
            slippage_bps=int(preview.get("slippage_bps") or 300),
        )

    async def execute_swap_intent(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 300,
        minimum_output_amount_raw: int | None = None,
        max_fee_lamports: int | None = None,
        valid_until_epoch_seconds: int | None = None,
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        if valid_until_epoch_seconds is not None and int(time.time()) > int(valid_until_epoch_seconds):
            raise WalletBackendError("Approved swap intent has expired. Create a fresh intent preview.")
        preview = await self.preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        output_raw = preview.get("estimated_output_amount_raw")
        if (
            minimum_output_amount_raw is not None
            and isinstance(output_raw, int)
            and output_raw < int(minimum_output_amount_raw)
        ):
            raise WalletBackendError(
                "Fresh swap quote is below the approved minimum output. Funds were not moved."
            )
        fee_summary = preview.get("fee_summary") if isinstance(preview.get("fee_summary"), dict) else {}
        network_fee_lamports = fee_summary.get("network_fee_lamports")
        if (
            max_fee_lamports is not None
            and isinstance(network_fee_lamports, int)
            and network_fee_lamports > int(max_fee_lamports)
        ):
            raise WalletBackendError("Fresh swap fee exceeds the approved fee limit. Funds were not moved.")
        result = await self.execute_swap_from_preview(preview)
        result["intent_execution"] = {
            "approved_minimum_output_amount_raw": minimum_output_amount_raw,
            "approved_max_fee_lamports": max_fee_lamports,
            "fresh_quote_used": True,
            "attempt_count": 1,
            "max_attempts": max_attempts,
        }
        return result

    async def preview_bags_token_launch(
        self,
        *,
        name: str,
        symbol: str,
        description: str,
        base_mint: str,
        claimers: list[str],
        basis_points: list[int],
        initial_buy_sol: float,
        image_url: str | None = None,
        website: str | None = None,
        twitter: str | None = None,
        telegram: str | None = None,
        discord: str | None = None,
        bags_config_type: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Bags token launch previews.")

    async def execute_bags_token_launch(
        self,
        *,
        name: str,
        symbol: str,
        description: str,
        base_mint: str,
        claimers: list[str],
        basis_points: list[int],
        initial_buy_sol: float,
        image_url: str | None = None,
        website: str | None = None,
        twitter: str | None = None,
        telegram: str | None = None,
        discord: str | None = None,
        bags_config_type: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Bags token launches.")

    async def execute_bags_token_launch_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.execute_bags_token_launch(
            name=str(preview["token_name"]),
            symbol=str(preview["token_symbol"]),
            description=str(preview["description"]),
            base_mint=str(preview["base_mint"]),
            claimers=list(preview["claimers"]),
            basis_points=[int(value) for value in preview["basis_points"]],
            initial_buy_sol=float(preview["initial_buy_sol"]),
            image_url=preview.get("image_url"),
            website=preview.get("website"),
            twitter=preview.get("twitter"),
            telegram=preview.get("telegram"),
            discord=preview.get("discord"),
            bags_config_type=(
                int(preview["bags_config_type"])
                if preview.get("bags_config_type") is not None
                else None
            ),
        )

    async def preview_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support native staking previews.")

    async def prepare_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support native staking preparation.")

    async def execute_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support native staking.")

    async def preview_deactivate_stake(self, stake_account: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support stake deactivation previews.")

    async def prepare_deactivate_stake(self, stake_account: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support stake deactivation preparation.")

    async def execute_deactivate_stake(self, stake_account: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support stake deactivation.")

    async def preview_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support stake withdraw previews.")

    async def prepare_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support stake withdraw preparation.")

    async def execute_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support stake withdraw.")
