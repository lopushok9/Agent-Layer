# AgentLayer Universal Local MCP

This is the framework-neutral AgentLayer wallet MCP for any client that
supports local MCP over `stdio`. It uses the same local wallet runtime and the
same full tool surface as the Codex and Claude Code bridges.

## Connect a client

Install the runtime, then ask the CLI for the exact config for this machine:

```bash
npx --yes @agentlayer.tech/wallet@latest install --yes --runtime-only
npx --yes @agentlayer.tech/wallet@latest mcp config
```

Paste the resulting `mcpServers` object into the client's MCP settings. The
command contains an absolute path under
`~/.openclaw/agent-wallet-runtime/current`, so normal wallet updates keep the
client connected to the active runtime.

For clients that want a command rather than a JSON object:

```bash
npx --yes @agentlayer.tech/wallet@latest mcp serve
```

For clients that ask for a launcher path:

```bash
npx --yes @agentlayer.tech/wallet@latest mcp path
```

## Security and behavior

The MCP config contains no wallet secrets. The bridge reuses the existing
wallet adapter and therefore exposes the same read and write capabilities as
the Codex and Claude Code integrations. Write operations still preserve the
wallet's `preview -> prepare -> execute` flow and approval-token validation;
this universal launcher does not weaken those backend rules.
