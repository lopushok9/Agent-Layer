"""Offline regression for buying tokenized stocks on Base.

Covers the failure seen in a live session ("buy TSLA stock on base"): the agent
could not find the token because (1) the onchain symbol is TSLAc, not TSLA,
(2) DexScreener's global search is cut at ~30 pairs before the Base filter runs,
and (3) Uniswap tools were not routed to the EVM backend when Solana was active.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import dexscreener, tokenized_stocks  # noqa: E402
from agent_wallet.wallet_layer.wdk_evm import WdkEvmLocalWalletBackend  # noqa: E402

TSLA = "0xb2000000000000000000001e800a7f5189430cD0"
AAPL = "0xb200000000000000000000C2e324d24d7eEcd1fb"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

PAGES = {
    None: {
        "tokens": [
            {"contract_address": AAPL, "symbol": "AAPLc", "name": "Apple Inc.", "decimals": 8,
             "isin": "US0378331005", "multiplier": 1},
        ],
        "next_page_token": "p2",
    },
    "p2": {
        "tokens": [
            {"contract_address": TSLA, "symbol": "TSLAc", "name": "Tesla Inc.", "decimals": 8,
             "isin": "US88160R1014", "multiplier": 1},
            {"contract_address": "not-an-address", "symbol": "BADc"},
        ],
        "next_page_token": "",
    },
}


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.calls: list[str] = []

    async def get(self, url, params=None):
        self.calls.append(url)
        token = (params or {}).get("page_token")
        return _Response(PAGES[token])


def _pair(chain, dex, base_symbol, base_address, liquidity):
    return {
        "chainId": chain,
        "dexId": dex,
        "pairAddress": f"0xpair{dex}",
        "baseToken": {"address": base_address, "symbol": base_symbol, "name": base_symbol},
        "quoteToken": {"address": USDC, "symbol": "USDC", "name": "USD Coin"},
        "liquidity": {"usd": liquidity},
        "priceUsd": "360",
    }


async def _run() -> None:
    fake_client = _FakeClient()
    tokenized_stocks.get_client = lambda: fake_client
    tokenized_stocks._cache.clear()

    # Registry resolution: ticker, suffixed symbol, company name, ISIN, address, no match.
    for query in ("TSLA", "tsla", "TSLAc", "Tesla", "US88160R1014", TSLA):
        result = await tokenized_stocks.find_tokenized_stocks(query)
        assert result["matches"], query
        top = result["matches"][0]
        assert top["address"] == TSLA and top["exact_match"] is True, (query, top)
        assert top["underlying_ticker"] == "TSLA" and top["decimals"] == 8
    assert result["registry_size"] == 2, "pagination must collect both pages and drop bad rows"
    assert (await tokenized_stocks.find_tokenized_stocks("zzzz"))["matches"] == []
    assert len(fake_client.calls) == 2, "registry must be cached after the first paginated fetch"
    try:
        await tokenized_stocks.find_tokenized_stocks("TSLA", network="ethereum")
    except Exception as exc:
        assert "base" in str(exc)
    else:
        raise AssertionError("unsupported network must fail loudly")

    # search_uniswap_pairs: global search has no Base hit for "TSLA" (as observed live);
    # the canonical TSLAc pools must still be returned and flagged.
    async def fake_search(query):
        if query.endswith(" base"):
            return [_pair("base", "uniswap", "Basecat", "0x" + "1" * 40, 381000)]
        return [_pair("robinhood", "uniswap", "TSLA", "0x" + "2" * 40, 50000)]

    async def fake_token_pairs(*, chain, token_address):
        assert chain == "base" and token_address == TSLA
        return [
            _pair("base", "uniswap", "TSLAc", TSLA, 31000),
            _pair("base", "aero", "TSLAc", TSLA, 215000),
        ]

    dexscreener.search_pairs = fake_search
    dexscreener.get_pairs_for_token = fake_token_pairs
    backend = types.SimpleNamespace(network="base")

    search = await WdkEvmLocalWalletBackend.search_uniswap_pairs(backend, query="TSLA", chain="base")
    canonical_pairs = [p for p in search["pairs"] if p["base_token"]["canonical_tokenized_stock"]]
    assert len(canonical_pairs) == 2, search
    assert search["canonical_tokenized_stocks"]["matches"][0]["address"] == TSLA
    assert any(p["base_token"]["symbol"] == "Basecat" and not p["base_token"]["canonical_tokenized_stock"]
               for p in search["pairs"])

    # Non-stock query must not get a canonical block.
    async def no_token_pairs(**_):
        raise AssertionError("must not look up canonical pairs for a non-stock query")

    dexscreener.get_pairs_for_token = no_token_pairs
    other = await WdkEvmLocalWalletBackend.search_uniswap_pairs(backend, query="AERO", chain="base")
    assert "canonical_tokenized_stocks" not in other

    # get_evm_tokenized_stock: canonical address, deepest venue first, next quoting step.
    dexscreener.get_pairs_for_token = fake_token_pairs
    stock = await WdkEvmLocalWalletBackend.get_evm_tokenized_stock(backend, query="Tesla")
    assert stock["matches"][0]["address"] == TSLA
    assert stock["liquidity"]["top_venues"][0]["dex_id"] == "aero"
    assert stock["next_step"]["tool"] == "get_evm_swap_quote"
    assert stock["next_step"]["token_out"] == TSLA
    assert stock["next_step"]["suggested_token_in"] == USDC
    assert any("U.S. persons" in notice for notice in stock["notices"])


def _check_routing() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"
    spec = importlib.util.spec_from_file_location("codex_server_routing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("get_uniswap_swap_quote", "search_uniswap_pairs", "get_evm_tokenized_stock"):
        assert module._infer_backend_for_tool(name) == "wdk_evm_local", name
    hermes_source = (repo_root / "hermes" / "plugins" / "agent_wallet" / "tools.py").read_text()
    assert '"uniswap" in tool_name' in hermes_source
    ts_source = (repo_root / ".openclaw" / "extensions" / "agent-wallet" / "index.ts").read_text()
    assert 'toolName.includes("uniswap")' in ts_source
    assert 'name: "get_evm_tokenized_stock"' in ts_source


def main() -> None:
    asyncio.run(_run())
    _check_routing()
    print("smoke_tokenized_stocks: ok")


if __name__ == "__main__":
    main()
