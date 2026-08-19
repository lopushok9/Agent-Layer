"""Regression coverage for the shared EVM network policy contract."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.autonomous_policy import MAINNET_NETWORKS  # noqa: E402
from agent_wallet.config import normalize_evm_network  # noqa: E402
from agent_wallet.networks import (  # noqa: E402
    EVM_CORE_MAINNET_CAIP_IDS,
    EVM_CORE_MAINNETS,
)
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402


def main() -> None:
    assert EVM_CORE_MAINNETS == frozenset({"ethereum", "base", "robinhood", "goat"})
    assert EVM_CORE_MAINNETS.issubset(MAINNET_NETWORKS)
    adapter = OpenClawWalletAdapter(SimpleNamespace(chain="evm", network="ethereum"))
    for network in EVM_CORE_MAINNETS:
        assert normalize_evm_network(network) == network
        assert adapter._is_mainnet_network(network) is True
    for caip_network in EVM_CORE_MAINNET_CAIP_IDS:
        assert adapter._is_mainnet_network(caip_network) is True
    assert normalize_evm_network("goat-mainnet") == "goat"
    print("smoke_evm_network_policy: ok")


if __name__ == "__main__":
    main()
