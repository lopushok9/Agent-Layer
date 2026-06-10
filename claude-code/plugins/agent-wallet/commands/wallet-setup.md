---
description: Install or repair the AgentLayer wallet backend runtime without leaving Claude Code.
allowed-tools: Bash(sh:*), Bash(npx:*)
---

Install (or repair) the AgentLayer wallet backend that this plugin bridges to.

Run the bootstrap bridge to the npm installer:

```
sh "${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap_backend.sh" install
```

Then report the outcome to the user:

- If it succeeded, tell them the backend is installed and that they should
  restart Claude Code (or reload the `agent-wallet` plugin) so the wallet tools
  become available.
- If it failed because Node.js or Python is missing, relay the exact requirement
  (Node.js 18+, Python >= 3.10 with venv) and the manual fallback command from
  the script output.

Do not pass or generate any secrets. The npm installer manages the local wallet
keys and sealed secrets under `OPENCLAW_HOME` on its own.
