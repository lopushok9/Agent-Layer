# Releasing

This repo publishes the npm installer as:

```text
@agentlayer.tech/wallet
```

The public install command is:

```bash
npx @agentlayer.tech/wallet install --yes
```

## When npm Publishes

Normal commits and pushes do not publish new npm versions. They only run the
GitHub Actions verification job.

An npm publish happens only when you push a git tag that starts with `v`, for
example `v0.1.10`.

The same tag workflow also creates a GitHub Release on the repository's
Releases page after npm publish succeeds.

The tag version must match both source version files:

```text
package.json
agent-wallet/pyproject.toml
```

If those versions do not match the tag, the workflow fails before publishing.

## Stable Release

Use a stable release when users should get it from the default install command.

Example: publish `0.1.10` as npm `latest`.

1. Update `package.json`:

```json
"version": "0.1.10"
```

2. Update `agent-wallet/pyproject.toml`:

```toml
version = "0.1.10"
```

3. Run local checks:

```bash
npm run check
GITHUB_REF_NAME=v0.1.10 npm run check:release-version
python3 agent-wallet/tests/smoke_npm_installer.py
python3 agent-wallet/tests/smoke_install_agent_wallet.py
npm --cache /tmp/npm-cache pack --dry-run
```

4. Commit the version change:

```bash
git add package.json agent-wallet/pyproject.toml
git commit -m "Release npm installer 0.1.10"
```

5. Create and push the release tag:

```bash
git tag -a v0.1.10 -m "v0.1.10"
git push origin main
git push origin v0.1.10
```

6. Check npm after GitHub Actions finishes:

```bash
npm view @agentlayer.tech/wallet dist-tags
npm view @agentlayer.tech/wallet@latest version
```

Expected result:

```text
latest: 0.1.10
```

The GitHub Releases page should also contain a new release named `v0.1.10`.

## Beta Release

Use a beta release when you want to test npm publishing without changing the
default user install command.

Example: publish `0.1.11-beta.1` as npm `beta`.

1. Set both version files to the beta version:

```json
"version": "0.1.11-beta.1"
```

```toml
version = "0.1.11-beta.1"
```

2. Run checks:

```bash
npm run check
GITHUB_REF_NAME=v0.1.11-beta.1 npm run check:release-version
npm --cache /tmp/npm-cache pack --dry-run
```

3. Commit, tag, and push:

```bash
git add package.json agent-wallet/pyproject.toml
git commit -m "Release npm installer 0.1.11-beta.1"
git tag -a v0.1.11-beta.1 -m "v0.1.11-beta.1"
git push origin main
git push origin v0.1.11-beta.1
```

4. Test the beta package:

```bash
npx @agentlayer.tech/wallet@beta --version
npx @agentlayer.tech/wallet@beta doctor
```

The GitHub Releases page should contain a new prerelease named
`v0.1.11-beta.1`.

## What Ships

The npm package is intentionally limited to the wallet installer runtime:

```text
.openclaw/extensions/agent-wallet
agent-wallet
wdk-btc-wallet
wdk-evm-wallet
bin
scripts
setup.sh
install-from-github.sh
README.md
CHANGELOG.md
RELEASING.md
LICENSE
```

It must not ship unrelated repo projects or generated local state:

```text
landing
solana-8004
provider-gateway
mcp-server
agent-a2a-gateway
docs
node_modules
.venv
__pycache__
.pytest_cache
.DS_Store
wallet files
OpenClaw secrets
```

The package allowlist lives in `package.json` under `files`.

## Runtime Layout

Installer releases are copied into the user's OpenClaw home:

```text
~/.openclaw/agent-wallet-runtime/releases/<version>
~/.openclaw/agent-wallet-runtime/current
```

The CLI switches `current` only after a successful install or update.

Rollback switches `current` back to the previous runtime or to a specific
installed version:

```bash
npx @agentlayer.tech/wallet rollback
```

## GitHub And npm Setup

Publishing uses npm Trusted Publishing through GitHub Actions. The npm package
must have this trusted publisher configured:

```text
Provider: GitHub Actions
Organization or user: lopushok9
Repository: Agent-Layer
Workflow filename: npm-installer.yml
Environment name: empty
```

The `repository.url` field in `package.json` must exactly match the GitHub
repository URL:

```text
https://github.com/lopushok9/Agent-Layer.git
```

Do not use `NPM_TOKEN` unless Trusted Publishing is unavailable. Token-based
publishes can fail with `EOTP` when npm requires two-factor authentication.
