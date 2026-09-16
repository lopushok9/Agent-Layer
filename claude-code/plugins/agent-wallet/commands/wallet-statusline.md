---
description: Show live SOL/Base USDC balances in the Claude Code status line.
allowed-tools: Bash(sh:*)
disable-model-invocation: true
---

Enable the wallet balance status line (shows SOL and Base USDC balances
under the input box, refreshed roughly every 30 seconds, from public RPCs
only — no secret material is touched after the one-time address lookup).

Run the setup script:

```
sh "${CLAUDE_PLUGIN_ROOT}/scripts/wallet_statusline_setup.sh"
```

This resolves the connected Solana and Base addresses once through the real
wallet backend (can take several seconds if it's cold), caches them under
`~/.openclaw/wallet-statusline/`, copies the lightweight polling script
there, and adds a `statusLine` entry to the user's `~/.claude/settings.json`.

Then report the outcome to the user:

- If it succeeded, tell them the status line is set and to restart Claude
  Code (or start a new session) to see it.
- If it failed because a different statusLine is already configured, tell
  them to run `/statusline delete` first if they want to replace it, then
  re-run `/wallet-statusline` — otherwise their existing one is untouched.
- If wallet address resolution failed, relay the error and suggest running
  `/wallet-setup` first to make sure the wallet backend itself is installed
  and working.

Also mention: it can be turned off anytime with `/statusline delete` (a
built-in Claude Code command) — this plugin does not add its own toggle.
