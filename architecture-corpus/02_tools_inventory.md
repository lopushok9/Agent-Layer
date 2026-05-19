# Tools Inventory

This file lists the major agent-facing tool surfaces across the repository.

## OpenClaw plugin: `agent-wallet`

Main clusters:

- Wallet state: `get_wallet_address`, `get_wallet_balance`, `get_wallet_portfolio`, `get_wallet_capabilities`, `get_active_wallet_backend`, `set_wallet_backend`
- Solana transfers and swaps: `transfer_sol`, `transfer_spl_token`, `swap_solana_tokens`, `swap_solana_privately`, `continue_solana_private_swap`, `get_solana_private_swap_status`, `list_pending_solana_private_swaps`
- Solana yield and lending: `get_jupiter_earn_tokens`, `get_jupiter_earn_positions`, `get_jupiter_earn_earnings`, `jupiter_earn_deposit`, `jupiter_earn_withdraw`, `get_kamino_lend_markets`, `get_kamino_lend_market_reserves`, `get_kamino_lend_user_obligations`, `get_kamino_lend_user_rewards`, `kamino_lend_deposit`, `kamino_lend_withdraw`, `kamino_lend_borrow`, `kamino_lend_repay`
- Bags and paid APIs: `launch_bags_token`, `get_bags_claimable_positions`, `claim_bags_fees`, `get_bags_fee_analytics`, `x402_search_services`, `x402_get_service_details`, `x402_preview_request`, `x402_pay_request`
- Bitcoin: `get_btc_fee_rates`, `get_btc_max_spendable`, `get_btc_transfer_history`, `transfer_btc`
- EVM reads and actions: `get_evm_network`, `set_evm_network`, `get_evm_fee_rates`, `get_evm_transaction_receipt`, `get_evm_token_balance`, `get_evm_token_metadata`, `get_evm_swap_quote`, `swap_evm_tokens`, `swap_evm_lifi_cross_chain_tokens`, `transfer_evm_native`, `transfer_evm_token`, `get_evm_aave_account`, `get_evm_aave_positions`, `get_evm_aave_reserves`, `manage_evm_aave_position`
- EVM Lido and cross-chain: `get_evm_lido_overview`, `get_evm_lido_positions`, `get_evm_lido_withdrawal_requests`, `manage_evm_lido_position`, `manage_evm_lido_withdrawal`, `get_lifi_quote`, `get_lifi_supported_chains`, `get_lifi_transfer_status`, `swap_solana_lifi_cross_chain_tokens`

## OpenClaw plugin: `pay-bridge`

- `pay_status`
- `pay_wallet_info`
- `pay_search_services`
- `pay_get_service_endpoints`
- `pay_api_request`

## Hermes plugin: `agent_wallet`

- `agent_wallet_tools`
- `agent_wallet_invoke`
- `agent_wallet_approve`
- `agent_wallet_evm_status`
- `agent_wallet_evm_setup`

## MCP server active tool groups

- Prices: `get_crypto_prices`, `get_market_overview`, `get_trending_coins`
- DeFi: `get_defi_yields`, `get_protocol_tvl`, `get_protocol_fees`, `get_stablecoin_stats`, `get_curve_pools`, `get_curve_subgraph_data`
- On-chain: `get_wallet_balance`, `get_wallet_portfolio`, `get_token_transfers`, `get_transaction_history`, `get_token_balances`
- Gas: `get_gas_prices`
- Search: `search_crypto`
- Sentiment: `get_fear_greed_index`
- ERC-8004 agents: `get_agent_by_id`, `list_erc8004_chains`, `search_erc8004_agents`, `get_erc8004_agent_profile`

## Provider gateway endpoint families

- Solana RPC: `/v1/rpc`
- EVM RPC: `/v1/evm/rpc/{network}`
- Bags trade, launch, claim, and fee analytics
- Jupiter Earn relay
- Flash Trade perps relay
- Houdini private swap relay

## A2A and registration surfaces

- `agent-a2a-gateway`: `/a2a`, `/.well-known/agent.json`, `/oasf.json`
- `solana-8004`: mainnet registration, IPFS upload, service URL publishing
