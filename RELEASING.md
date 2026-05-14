# Releasing

This repo publishes the npm installer as:

```text
@agentlayer.tech/wallet
```

The public install command is:

```bash
npx @agentlayer.tech/wallet install --yes
```

The repo also ships two native OpenClaw plugin packages for ClawHub:

```text
@agentlayertech/agent-wallet-plugin
@agentlayertech/pay-bridge-plugin
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
The same `v*` tag can also trigger the ClawHub plugin publish workflow, so keep
the root installer versions aligned with the ClawHub plugin package versions
when you want one GitHub release to ship both surfaces together.

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

## ClawHub Plugin Packages

The OpenClaw plugin packages are published separately from the npm installer.
They are additive and do not replace `@agentlayer.tech/wallet`.

Before publishing either package, build and validate the runtime artifacts:

```bash
npm run build:openclaw-plugins
npm run check:openclaw-plugins
```

Dry-run the package contents from each plugin directory:

```bash
(cd .openclaw/extensions/agent-wallet && npm pack --dry-run)
(cd .openclaw/extensions/pay-bridge && npm pack --dry-run)
```

Publish to ClawHub with the package-specific command documented by OpenClaw:

```bash
clawhub package publish .openclaw/extensions/agent-wallet --dry-run
clawhub package publish .openclaw/extensions/agent-wallet

clawhub package publish .openclaw/extensions/pay-bridge --dry-run
clawhub package publish .openclaw/extensions/pay-bridge
```

Users then install them natively through OpenClaw:

```bash
openclaw plugins install clawhub:@agentlayertech/agent-wallet-plugin
openclaw plugins install clawhub:@agentlayertech/pay-bridge-plugin
```

GitHub Actions can publish the same packages automatically from tags and manual
dispatch through `.github/workflows/clawhub-plugins.yml`.

Required repository secret:

```text
CLAWHUB_TOKEN
```

Workflow behavior:

- `pull_request`: packs both plugins and runs ClawHub `--dry-run`
- `workflow_dispatch`: publishes or dry-runs based on the `dry_run` input
- `push` on `v*` tags: publishes both plugins automatically

The workflow currently publishes:

- `.openclaw/extensions/agent-wallet` as `bundle-plugin`
- `.openclaw/extensions/pay-bridge` as `code-plugin`

`agent-wallet` stays on `bundle-plugin` because that package name was first
published to ClawHub with that family, and ClawHub does not allow family
changes for an existing package record.

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

## ClawHub Release Workflow

This repo also includes a separate GitHub Actions workflow for the OpenClaw
plugin packages:

```text
.github/workflows/clawhub-plugins.yml
```

It publishes these ClawHub packages:

```text
@agentlayertech/agent-wallet-plugin
@agentlayertech/pay-bridge-plugin
```

### Triggers

- `pull_request`
  - runs ClawHub publish in `--dry-run` mode for both plugin packages
- `workflow_dispatch`
  - supports manual runs with a `dry_run` boolean input
- `push` on git tags matching `v*`
  - publishes both plugin packages to ClawHub

### Required secret

The workflow requires this repository Actions secret:

```text
CLAWHUB_TOKEN
```

That token is created in the ClawHub web UI and must belong to an account with
publisher access to:

```text
@agentlayertech
```

### Family mapping

The workflow currently publishes:

- `.openclaw/extensions/agent-wallet` as `bundle-plugin`
- `.openclaw/extensions/pay-bridge` as `code-plugin`

`agent-wallet` remains on `bundle-plugin` because the package
`@agentlayertech/agent-wallet-plugin` was first created in ClawHub with that
family, and ClawHub does not allow family changes for an existing package name.

### Release flow with tags

If you want one git tag to publish both npm and ClawHub surfaces together:

1. Keep these versions aligned:

```text
package.json
agent-wallet/pyproject.toml
.openclaw/extensions/agent-wallet/package.json
.openclaw/extensions/pay-bridge/package.json
```

2. Commit the release version bump.

3. Push `main`.

4. Create and push the tag:

```bash
git tag -a v0.1.16 -m "v0.1.16"
git push origin v0.1.16
```

That tag will trigger:

- `.github/workflows/npm-installer.yml`
- `.github/workflows/clawhub-plugins.yml`

### Manual verification without publishing

To verify the ClawHub workflow and token without creating a new release:

1. Open GitHub Actions
2. Select `ClawHub plugins`
3. Click `Run workflow`
4. Choose branch `main`
5. Set `dry_run=true`
6. Run it

Expected result:

- both matrix jobs succeed
- ClawHub login succeeds
- both package publishes resolve in dry-run mode without uploading
