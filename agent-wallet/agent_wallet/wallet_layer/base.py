"""Shared primitives for agent wallet backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
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

    async def get_jupiter_portfolio(
        self,
        address: str | None = None,
        platforms: list[str] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter portfolio lookup.")

    async def get_jupiter_portfolio_platforms(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter portfolio platforms.")

    async def get_jupiter_staked_jup(self, address: str | None = None) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter staked JUP lookup.")

    async def get_jupiter_earn_tokens(self) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn token lookup.")

    async def get_jupiter_earn_positions(
        self,
        users: list[str] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn positions.")

    async def get_jupiter_earn_earnings(
        self,
        user: str | None = None,
        positions: list[str] | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn earnings.")

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

    async def preview_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino deposit previews.")

    async def prepare_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino deposit preparation.")

    async def execute_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino deposits.")

    async def preview_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino withdraw previews.")

    async def prepare_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino withdraw preparation.")

    async def execute_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino withdraws.")

    async def preview_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino borrow previews.")

    async def prepare_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino borrow preparation.")

    async def execute_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino borrows.")

    async def preview_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino repay previews.")

    async def prepare_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino repay preparation.")

    async def execute_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Kamino repays.")

    async def preview_jupiter_earn_deposit(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn deposit previews.")

    async def prepare_jupiter_earn_deposit(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn deposit preparation.")

    async def execute_jupiter_earn_deposit(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn deposits.")

    async def preview_jupiter_earn_withdraw(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn withdraw previews.")

    async def prepare_jupiter_earn_withdraw(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(
            f"{self.name} does not support Jupiter Earn withdraw preparation."
        )

    async def execute_jupiter_earn_withdraw(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Jupiter Earn withdrawals.")

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
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support swap previews.")

    async def prepare_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
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
            slippage_bps=int(preview.get("slippage_bps") or 50),
        )

    async def execute_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
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
            slippage_bps=int(preview.get("slippage_bps") or 50),
        )

    async def get_bags_claimable_positions(
        self,
        wallet: str | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Bags claimable positions lookup.")

    async def get_bags_fee_analytics(
        self,
        token_mint: str,
        *,
        include_claim_events: bool = False,
        mode: str = "offset",
        limit: int | None = None,
        offset: int | None = None,
        from_ts: int | None = None,
        to_ts: int | None = None,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Bags fee analytics lookup.")

    async def preview_bags_fee_claim(self, token_mint: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Bags fee claim previews.")

    async def execute_bags_fee_claim(self, token_mint: str) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support Bags fee claims.")

    async def execute_bags_fee_claim_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.execute_bags_fee_claim(str(preview["token_mint"]))

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

    async def request_testnet_airdrop(self, amount_native: float) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support testnet airdrops.")

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
