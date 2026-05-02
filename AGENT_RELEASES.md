# Agent Release Notes

Use this short checklist when changing versions or publishing releases.

## Core Rule

Normal commits do not publish npm packages.

Only a pushed git tag that starts with `v` publishes a new npm version and
creates a GitHub Release.

## Version Files

Always keep these two files in sync:

```text
package.json
agent-wallet/pyproject.toml
```

Example stable release:

```text
package.json: "version": "0.1.10"
agent-wallet/pyproject.toml: version = "0.1.10"
git tag: v0.1.10
```

Example beta release:

```text
package.json: "version": "0.1.11-beta.1"
agent-wallet/pyproject.toml: version = "0.1.11-beta.1"
git tag: v0.1.11-beta.1
```

## Stable Release

Stable versions publish to npm tag `latest`.

```bash
npm run check
GITHUB_REF_NAME=v0.1.10 npm run check:release-version
npm --cache /tmp/npm-cache pack --dry-run
git add package.json agent-wallet/pyproject.toml
git commit -m "Release npm installer 0.1.10"
git tag -a v0.1.10 -m "v0.1.10"
git push origin main
git push origin v0.1.10
```

After GitHub Actions finishes:

```bash
npm view @agentlayer.tech/wallet dist-tags
npm view @agentlayer.tech/wallet@latest version
```

## Beta Release

Beta versions publish to npm tag `beta`.

```bash
npm run check
GITHUB_REF_NAME=v0.1.11-beta.1 npm run check:release-version
npm --cache /tmp/npm-cache pack --dry-run
git add package.json agent-wallet/pyproject.toml
git commit -m "Release npm installer 0.1.11-beta.1"
git tag -a v0.1.11-beta.1 -m "v0.1.11-beta.1"
git push origin main
git push origin v0.1.11-beta.1
```

Test beta installs with:

```bash
npx @agentlayer.tech/wallet@beta --version
npx @agentlayer.tech/wallet@beta doctor
```

## What Must Not Ship

The npm package should stay limited to wallet installer runtime code. Do not add
unrelated repo directories to `package.json` `files`.

Do not ship:

```text
landing
solana-8004
provider-gateway
mcp-server
agent-a2a-gateway
docs
node_modules
.venv
wallet files
OpenClaw secrets
```

## More Detail

Use `RELEASING.md` for the full release process and Trusted Publishing setup.
