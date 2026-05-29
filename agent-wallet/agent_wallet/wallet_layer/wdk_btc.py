"""Local BTC backend backed by the wdk-btc-wallet service."""

from __future__ import annotations

from typing import Any

from agent_wallet.config import normalize_btc_network
from agent_wallet.providers.wdk_btc_local import WdkBtcLocalClient
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError, WalletCapabilities


def _sats_to_btc(value: Any) -> float:
    return int(value) / 100_000_000


def _normalize_btc_network(value: str | None) -> str:
    return normalize_btc_network(value)


class WdkBtcLocalWalletBackend(AgentWalletBackend):
    """Bitcoin backend that delegates signing and execution to a local WDK service."""

    name = "wdk_btc_local"

    def __init__(
        self,
        *,
        service_url: str,
        wallet_id: str,
        network: str,
        account_index: int = 0,
        sign_only: bool = False,
        address: str | None = None,
    ):
        self.client = WdkBtcLocalClient(service_url)
        self.wallet_id = str(wallet_id or "").strip()
        if not self.wallet_id:
            raise WalletBackendError("WDK BTC wallet id is not configured.")
        self.network = _normalize_btc_network(network)
        self.account_index = int(account_index)
        self.sign_only = bool(sign_only)
        self.address = address.strip() if isinstance(address, str) and address.strip() else None
        self.chain = "bitcoin"
        self.custody_model = "local_service_vault"

    async def get_address(self) -> str | None:
        if self.address:
            return self.address
        data = await self.client.post(
            "/v1/btc/address/resolve",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        address = str(data.get("address") or "").strip()
        if not address:
            raise WalletBackendError("wdk-btc-wallet did not return an address.")
        self.address = address
        return address

    async def get_balance(self, address: str | None = None) -> dict[str, Any]:
        resolved_address = await self.get_address()
        if address is not None and address.strip() and address.strip() != resolved_address:
            raise WalletBackendError(
                "wdk_btc_local only supports the configured default BTC account address."
            )
        data = await self.client.post(
            "/v1/btc/balance/get",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
            },
        )
        balance_sats = int(data.get("balance") or 0)
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or resolved_address or ""),
            "balance_sats": balance_sats,
            "balance_native": _sats_to_btc(balance_sats),
            "asset": "BTC",
            "source": "wdk-btc-wallet",
        }

    async def get_btc_transfer_history(
        self,
        *,
        direction: str = "all",
        limit: int = 10,
        skip: int = 0,
    ) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/btc/transfers/get",
            {
                "walletId": self.wallet_id,
                "accountIndex": self.account_index,
                "network": self.network,
                "direction": direction,
                "limit": limit,
                "skip": skip,
            },
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or await self.get_address() or ""),
            "direction": direction,
            "limit": limit,
            "skip": skip,
            "transfers": list(data.get("transfers") or []),
            "source": "wdk-btc-wallet",
        }

    async def get_btc_fee_rates(self) -> dict[str, Any]:
        data = await self.client.post(
            "/v1/btc/fee-rates/get",
            {"network": self.network},
        )
        return {
            "chain": self.chain,
            "network": self.network,
            "fee_rates": data.get("feeRates") or {},
            "source": "wdk-btc-wallet",
        }

    async def get_btc_max_spendable(
        self,
        *,
        fee_rate: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "accountIndex": self.account_index,
            "network": self.network,
        }
        if fee_rate is not None:
            payload["feeRate"] = int(fee_rate)
        data = await self.client.post("/v1/btc/max-spendable/get", payload)
        max_spendable = dict(data.get("maxSpendable") or {})
        amount_sats = int(max_spendable.get("amount") or 0)
        fee_sats = int(max_spendable.get("fee") or 0)
        change_sats = int(max_spendable.get("changeValue") or 0)
        return {
            "chain": self.chain,
            "network": self.network,
            "address": str(data.get("address") or await self.get_address() or ""),
            "fee_rate": fee_rate,
            "amount_sats": amount_sats,
            "amount_btc": _sats_to_btc(amount_sats),
            "estimated_fee_sats": fee_sats,
            "estimated_fee_btc": _sats_to_btc(fee_sats),
            "change_sats": change_sats,
            "change_btc": _sats_to_btc(change_sats),
            "raw": max_spendable,
            "source": "wdk-btc-wallet",
        }

    async def preview_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict[str, Any]:
        raise WalletBackendError(
            "wdk_btc_local expects transfer_btc with amount_sats, not preview_native_transfer."
        )

    async def preview_btc_transfer(
        self,
        *,
        recipient: str,
        amount_sats: int,
        fee_rate: int | None = None,
        confirmation_target: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "accountIndex": self.account_index,
            "network": self.network,
            "to": recipient,
            "value": int(amount_sats),
        }
        if fee_rate is not None:
            payload["feeRate"] = int(fee_rate)
        if confirmation_target is not None:
            payload["confirmationTarget"] = int(confirmation_target)
        data = await self.client.post("/v1/btc/transfer/quote", payload)
        quote = dict(data.get("quote") or {})
        fee_sats = int(quote.get("fee") or 0)
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "btc-transfer",
            "asset": "BTC",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "recipient": recipient,
            "amount_sats": int(amount_sats),
            "amount_btc": _sats_to_btc(amount_sats),
            "fee_rate": fee_rate,
            "confirmation_target": confirmation_target,
            "estimated_fee_sats": fee_sats,
            "estimated_fee_btc": _sats_to_btc(fee_sats),
            "source": "wdk-btc-wallet",
        }

    async def send_btc_transfer(
        self,
        *,
        recipient: str,
        amount_sats: int,
        fee_rate: int | None = None,
        confirmation_target: int | None = None,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError("wdk_btc_local is configured as sign_only.")
        payload: dict[str, Any] = {
            "walletId": self.wallet_id,
            "accountIndex": self.account_index,
            "network": self.network,
            "to": recipient,
            "value": int(amount_sats),
        }
        if fee_rate is not None:
            payload["feeRate"] = int(fee_rate)
        if confirmation_target is not None:
            payload["confirmationTarget"] = int(confirmation_target)
        data = await self.client.post("/v1/btc/transfer/send", payload)
        result = dict(data.get("result") or {})
        fee_sats = int(result.get("fee") or 0)
        return {
            "chain": self.chain,
            "network": self.network,
            "asset_type": "btc-transfer",
            "asset": "BTC",
            "wallet": self.wallet_id,
            "from_address": await self.get_address(),
            "recipient": recipient,
            "amount_sats": int(amount_sats),
            "amount_btc": _sats_to_btc(amount_sats),
            "fee_rate": fee_rate,
            "confirmation_target": confirmation_target,
            "estimated_fee_sats": fee_sats,
            "estimated_fee_btc": _sats_to_btc(fee_sats),
            "hash": result.get("hash"),
            "broadcasted": True,
            "confirmed": False,
            "source": "wdk-btc-wallet",
        }

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model=self.custody_model,
            sign_only=self.sign_only,
            has_signer=True,
            can_get_address=True,
            can_get_balance=True,
            can_sign_message=False,
            can_sign_transaction=not self.sign_only,
            can_send_transaction=not self.sign_only,
            external_dependencies=["wdk-btc-wallet", "electrum"],
        )
