# pay-bridge

Thin OpenClaw bridge to the locally installed `pay` CLI.

External install path:

```bash
openclaw plugins install clawhub:@agentlayertech/pay-bridge-plugin
```

This plugin is intentionally separate from `agent-wallet`:

- `agent-wallet` remains the execution wallet stack for Solana/EVM/BTC
- `pay-bridge` only discovers and calls paid APIs through `pay`
- the `pay` wallet stays separate from the AgentLayer wallet runtime

## Exposed tools

- `pay_status`
- `pay_wallet_info`
- `pay_search_services`
- `pay_get_service_endpoints`
- `pay_api_request`

## Intended workflow

1. `pay_status`
2. `pay_search_services`
3. `pay_get_service_endpoints`
4. `pay_api_request`

`pay_api_request` is deliberately narrow:

- it requires a `service_fqn`, `resource`, and `url`
- it validates the URL against `pay skills endpoints`
- it requires `purpose` and `user_confirmed=true`

This keeps the bridge thin and prevents it from becoming a generic arbitrary paid-curl launcher.
