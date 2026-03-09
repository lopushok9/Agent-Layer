"""Pydantic response models shared across tools."""

from pydantic import BaseModel


class PriceData(BaseModel):
    symbol: str
    name: str
    price_usd: float
    change_24h: float | None = None
    volume_24h: float | None = None
    market_cap: float | None = None
    source: str = "coingecko"


class MarketOverview(BaseModel):
    total_market_cap_usd: float
    total_volume_24h_usd: float
    btc_dominance: float
    eth_dominance: float
    active_cryptocurrencies: int
    source: str = "coingecko"


class TrendingCoin(BaseModel):
    symbol: str
    name: str
    market_cap_rank: int | None = None
    price_usd: float | None = None
    change_24h: float | None = None
    source: str = "coingecko"


class FearGreedData(BaseModel):
    value: int
    classification: str
    timestamp: str
    source: str = "alternative.me"


class DefiYield(BaseModel):
    pool: str
    project: str
    chain: str
    tvl_usd: float
    apy: float
    apy_base: float | None = None
    apy_reward: float | None = None
    stablecoin: bool
    source: str = "defillama"


class ProtocolTvl(BaseModel):
    name: str
    tvl_usd: float
    change_1d: float | None = None
    change_7d: float | None = None
    chains: list[str] = []
    category: str | None = None
    source: str = "defillama"


class ProtocolFees(BaseModel):
    name: str
    fees_24h: float | None = None
    revenue_24h: float | None = None
    category: str | None = None
    source: str = "defillama"


class StablecoinData(BaseModel):
    name: str
    symbol: str
    peg_type: str
    circulating_usd: float
    chains: list[str] = []
    source: str = "defillama"


class CurvePool(BaseModel):
    pool: str
    address: str | None = None
    chain: str
    registry: str
    asset_type: str | None = None
    tvl_usd: float
    apy: float | None = None
    apy_base: float | None = None
    apy_reward: float | None = None
    has_gauge: bool = False
    gauge_address: str | None = None
    source: str = "curve"


class CurveSubgraphData(BaseModel):
    chain: str
    tvl_usd: float | None = None
    volume_24h_usd: float | None = None
    fees_24h_usd: float | None = None
    crv_apy: float | None = None
    pool_count: int | None = None
    crypto_share_percent: float | None = None
    crypto_volume_24h_usd: float | None = None
    avg_daily_apy: float | None = None
    avg_weekly_apy: float | None = None
    max_daily_apy: float | None = None
    max_weekly_apy: float | None = None
    source: str = "curve"


class WalletBalance(BaseModel):
    address: str
    chain: str
    balance_native: float
    balance_usd: float | None = None
    source: str = "publicnode-rpc"


class TokenTransfer(BaseModel):
    tx_hash: str
    block_number: int
    timestamp: str
    from_address: str
    to_address: str
    token_symbol: str
    value: float
    source: str = "etherscan"


class Transaction(BaseModel):
    tx_hash: str
    block_number: int
    timestamp: str
    from_address: str
    to_address: str
    value_eth: float
    gas_used: int
    gas_price_gwei: float
    status: str
    source: str = "etherscan"


class GasPrice(BaseModel):
    chain: str
    slow_gwei: float
    standard_gwei: float
    fast_gwei: float
    source: str = "explorer"


class TokenBalance(BaseModel):
    contract_address: str
    symbol: str | None = None
    name: str | None = None
    balance: float
    decimals: int = 18
    source: str = "alchemy"


class PortfolioToken(BaseModel):
    symbol: str
    name: str | None = None
    balance: float
    price_usd: float | None = None
    value_usd: float | None = None


class WalletPortfolio(BaseModel):
    address: str
    chain: str
    native_symbol: str
    native_balance: float
    native_price_usd: float | None = None
    native_value_usd: float | None = None
    tokens: list[PortfolioToken] = []
    total_value_usd: float | None = None
    source: str = "rpc+alchemy+coingecko"


class AgentIdentity(BaseModel):
    agent_id: int
    exists: bool
    owner: str | None = None
    agent_wallet: str | None = None
    agent_uri: str | None = None
    agent_metadata: dict | None = None
    source: str = "erc8004"


class AgentSearchItem(BaseModel):
    agent_id: str
    chain_id: int
    chain_name: str | None = None
    token_id: str
    name: str | None = None
    description: str | None = None
    owner_address: str
    supported_protocols: list[str] = []
    has_mcp: bool = False
    has_a2a: bool = False
    has_oasf: bool = False
    x402_supported: bool = False
    total_score: float | None = None
    star_count: int = 0
    is_testnet: bool | None = None
    source: str = "8004scan"


class AgentServiceSummary(BaseModel):
    protocol: str
    endpoint: str | None = None
    version: str | None = None
    tools_count: int = 0
    prompt_count: int = 0
    resource_count: int = 0
    skill_count: int = 0
    tools: list[str] = []
    skills: list[str] = []


class AgentStructuredProfile(BaseModel):
    agent_id: str
    chain_id: int
    token_id: str
    contract_address: str
    chain_type: str = "evm"
    is_testnet: bool | None = None
    name: str | None = None
    description: str | None = None
    owner_address: str
    creator_address: str | None = None
    agent_wallet: str | None = None
    image_url: str | None = None
    supported_protocols: list[str] = []
    x402_supported: bool = False
    services: list[AgentServiceSummary] = []
    tags: list[str] = []
    categories: list[str] = []
    total_score: float | None = None
    rank: int | None = None
    star_count: int = 0
    watch_count: int = 0
    available_tools_count: int = 0
    available_skills_count: int = 0
    source: str = "8004scan"


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float | None = None
    source: str = "tavily"
