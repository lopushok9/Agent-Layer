# pay-operator

Use this skill when the user wants to discover or call paid APIs through `pay`.

## Rules

- Treat the `pay` wallet as separate from the AgentLayer execution wallet.
- Do not use `agent-wallet` tools for `pay` account management.
- Do not fall back to shell commands when the `pay-bridge` tools exist.
- Prefer this order:
  1. `pay_status`
  2. `pay_search_services`
  3. `pay_get_service_endpoints`
  4. `pay_api_request`

## Notes

- `pay_api_request` requires `purpose` and `user_confirmed=true`.
- Use the exact gateway URL returned by `pay_get_service_endpoints`.
- If `pay_status` shows no configured account, stop and ask the user to finish `pay setup`.
