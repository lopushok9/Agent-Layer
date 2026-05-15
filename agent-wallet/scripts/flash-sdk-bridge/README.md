# Flash SDK Bridge

This package is the repo-owned local bridge between `agent-wallet` and Flash Trade's official `flash-sdk`.

Current goals:

- keep Flash Trade SDK usage isolated from the Python wallet runtime
- preserve `agent-wallet` custody, approval, signing, and execution policy
- provide a stable stdin/stdout JSON contract that the Python backend can call

## Modes

- `FLASH_SDK_BRIDGE_MODE=mock`
  Returns deterministic payloads for local smoke checks without installing SDK dependencies.
- `FLASH_SDK_BRIDGE_MODE=real`
  Loads `flash-sdk` and validates runtime config. This mode now supports market discovery, user-position discovery, open/close previews, and unsigned transaction preparation for the current same-collateral Flash perps MVP.

## Command

Recommended `agent-wallet` setting:

```bash
FLASH_SDK_BRIDGE_COMMAND="node /absolute/path/to/agent-wallet/scripts/flash-sdk-bridge/bridge.mjs"
```

For local smoke:

```bash
FLASH_SDK_BRIDGE_MODE=mock \
node agent-wallet/scripts/flash-sdk-bridge/bridge.mjs <<'EOF'
{"action":"preview_open_position_same_collateral","owner":"Fake11111111111111111111111111111111111111111","pool_name":"Crypto.1","market_symbol":"SOL","collateral_symbol":"SOL","collateral_amount_raw":"100000000","leverage":"5","side":"long","network":"mainnet"}
EOF
```
