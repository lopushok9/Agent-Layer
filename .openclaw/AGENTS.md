# AGENTS.md

## Scope
These instructions apply to the entire `.openclaw/` tree.

## Purpose
This tree contains local OpenClaw workspace assets. In the current repo, its primary responsibility is the `agent-wallet` extension that bridges OpenClaw to the Python `agent-wallet` backend.

## Current structure
- `.openclaw/extensions/agent-wallet/index.ts` — TypeScript extension entrypoint registered by OpenClaw.
- `.openclaw/extensions/agent-wallet/openclaw.plugin.json` — plugin manifest and config schema.
- `.openclaw/extensions/agent-wallet/package.json` — extension package metadata.
- `.openclaw/extensions/agent-wallet/skills/wallet-operator/SKILL.md` — user-facing operational wallet safety guidance.

## Design intent
- Keep the TypeScript extension thin.
- Let Python own wallet logic, policy, approvals, and Solana implementation details.
- Let the extension focus on:
  - resolving config
  - locating the Python package
  - invoking `python -m agent_wallet.openclaw_cli`
  - registering OpenClaw tools
  - passing JSON in and out safely

## Working rules

### Keep bridge logic thin
- Do not duplicate business logic from Python unless OpenClaw requires it at registration time.
- Do not reimplement approval validation, transaction policy, or Solana-specific rules in TypeScript.
- Prefer forwarding config into the CLI bridge and letting Python decide runtime behavior.

### Keep schemas synchronized
- If you change extension config fields, also update:
  - `.openclaw/extensions/agent-wallet/openclaw.plugin.json`
  - `.openclaw/extensions/agent-wallet/index.ts`
  - `agent-wallet/agent_wallet/openclaw_cli.py`
  - `agent-wallet/README.md`
- If you add or remove tools, also update:
  - `.openclaw/extensions/agent-wallet/index.ts`
  - `agent-wallet/agent_wallet/openclaw_adapter.py`
  - `agent-wallet/agent_wallet/plugin_bundle.py`

### Security rules
- Never add support for passing wallet secrets through OpenClaw config JSON as the preferred path.
- Keep deprecated sensitive config fields clearly marked as insecure/deprecated if retained for compatibility.
- Preserve the separation between host approval issuance and tool execution.

### Path resolution expectations
- The extension currently resolves the Python package root from:
  - explicit plugin config
  - env overrides
  - the repo-local sibling `agent-wallet/`
- Keep fallback resolution practical for local development.
- If changing path resolution, preserve a clear error when the package root cannot be found.

## Editing guidance
- Favor small edits in `index.ts`; it is intentionally straightforward.
- Keep tool parameter schemas explicit and JSON-schema-like.
- Keep stdout payloads machine-readable because OpenClaw expects structured JSON text content.
- Keep descriptions aligned with actual Python behavior, especially for `preview`, `prepare`, `execute`, and `approval_token`.

## Validation
- After extension changes, verify the matching Python CLI contract still lines up.
- Relevant Python-side tests live in `agent-wallet/tests/`, especially:
  - `agent-wallet/tests/smoke_openclaw_cli.py`
  - `agent-wallet/tests/smoke_openclaw_adapter.py`
  - `agent-wallet/tests/smoke_openclaw_runtime.py`

## Common change patterns

### If changing tool registration
1. Update `index.ts`.
2. Sync the Python adapter/tool bundle.
3. Confirm names, required params, and safety wording match.

### If changing plugin config
1. Update `openclaw.plugin.json`.
2. Update TypeScript config consumption.
3. Update Python CLI env/config mapping.
4. Update docs/examples if behavior changed.
