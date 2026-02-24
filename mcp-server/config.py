"""Configuration via environment variables with sensible free-tier defaults."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Free-tier API URLs (no keys required) ---
    coingecko_api_url: str = "https://api.coingecko.com/api/v3"
    coincap_api_url: str = "https://api.coincap.io/v2"
    defillama_base_url: str = "https://api.llama.fi"
    defillama_yields_url: str = "https://yields.llama.fi"
    defillama_stablecoins_url: str = "https://stablecoins.llama.fi"
    curve_api_url: str = "https://api.curve.finance/v1"
    fear_greed_url: str = "https://api.alternative.me/fng"

    # RPC endpoints (Alchemy when key set, PublicNode as defaults)
    eth_rpc_url: str = "https://ethereum-rpc.publicnode.com"
    base_rpc_url: str = "https://base-rpc.publicnode.com"
    arbitrum_rpc_url: str = "https://arbitrum-one-rpc.publicnode.com"
    polygon_rpc_url: str = "https://polygon-bor-rpc.publicnode.com"
    optimism_rpc_url: str = "https://optimism-rpc.publicnode.com"
    bsc_rpc_url: str = "https://bsc-rpc.publicnode.com"

    # --- API Keys (optional) ---
    alchemy_api_key: str = ""
    tavily_api_key: str = ""
    firecrawl_api_key: str = ""

    # Blockchain explorer API keys (free tier)
    etherscan_api_key: str = ""
    arbiscan_api_key: str = ""
    basescan_api_key: str = ""

    # Explorer base URLs
    etherscan_api_url: str = "https://api.etherscan.io/api"
    arbiscan_api_url: str = "https://api.arbiscan.io/api"
    basescan_api_url: str = "https://api.basescan.org/api"

    # Tavily
    tavily_api_url: str = "https://api.tavily.com"

    # --- Cache TTLs (seconds) ---
    cache_ttl_prices: int = 30
    cache_ttl_market_overview: int = 60
    cache_ttl_trending: int = 300
    cache_ttl_fear_greed: int = 3600
    cache_ttl_defi_yields: int = 300
    cache_ttl_protocol_tvl: int = 600
    cache_ttl_protocol_fees: int = 600
    cache_ttl_stablecoins: int = 600
    cache_ttl_curve_pools: int = 300
    cache_ttl_curve_subgraph: int = 300
    cache_ttl_wallet_balance: int = 120
    cache_ttl_token_transfers: int = 60
    cache_ttl_tx_history: int = 60
    cache_ttl_gas: int = 15
    cache_ttl_token_balances: int = 120
    cache_ttl_portfolio: int = 60
    cache_ttl_search: int = 300
    cache_ttl_agent_identity: int = 120

    # Stale data max age (seconds) — used when provider fails
    cache_stale_max_age: int = 300

    # Max cache entries before eviction
    cache_max_entries: int = 10_000

    # --- Rate limits (calls/min, conservative) ---
    rate_limit_coingecko: int = 24
    rate_limit_coincap: int = 200
    rate_limit_defillama: int = 200
    rate_limit_curve: int = 120
    rate_limit_explorer: int = 80
    rate_limit_alchemy: int = 300
    rate_limit_dexscreener: int = 50
    rate_limit_tavily: int = 60

    # --- HTTP ---
    http_timeout: float = 10.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
