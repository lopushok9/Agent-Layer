"""Shared primitives for agent wallet backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


class WalletBackendError(Exception):
    """Wallet backend or signer error."""


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

    async def execute_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        raise WalletBackendError(f"{self.name} does not support swaps.")

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
