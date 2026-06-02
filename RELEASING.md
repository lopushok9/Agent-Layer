# Releasing

This repo publishes the npm installer as:

```text
@agentlayer.tech/wallet
```

The public install command is:

```bash
npx @agentlayer.tech/wallet install --yes
```

The repo also ships a native OpenClaw plugin package for ClawHub:

```text
@agentlayertech/agent-wallet-plugin
```

## When npm Publishes

Normal commits and pushes do not publish new npm versions. They only run the
GitHub Actions verification job.

An npm publish happens only when you push a git tag that starts with `v`, for
example `v0.1.10`.

The same tag workflow also creates a GitHub Release on the repository's
Releases page after npm publish succeeds.

## Version Single Source of Truth

The canonical version lives in **one** file at the repo root:

```text
VERSION
```

Every other manifest (npm `package.json`, `agent-wallet/pyproject.toml`, the
Python `__version__`, the OpenClaw extension, and the Codex / Claude Code /
Hermes / wdk plugin manifests) is a *derived* target. Do not edit them by hand —
stamp them from `VERSION`:

```bash
npm run version:sync          # stamp VERSION into all manifests
# or bump + stamp in one step:
node scripts/sync_version.mjs 0.1.34
```

`npm run check:release-version` verifies that `VERSION`, every derived manifest,
and (on a tag) the `v*` tag all agree. It runs on every PR/push, so drift cannot
be merged. The `v*` tag also triggers the ClawHub plugin publish workflow; since
all manifests are stamped from `VERSION`, one tag ships every surface in lockstep.

### Local release (install into all frameworks)

To make your own OpenClaw / Codex / Claude Code editors run a freshly bumped
version from the working tree (bump → stamp → verify → reinstall everywhere):

```bash
npm run release:local -- 0.1.34            # do it
npm run release:local -- 0.1.34 --dry-run  # preview the steps, change nothing
```

`wallet doctor` and `wallet status` report `runtime_in_sync`, flagging when the
installed runtime lags the repo version (i.e. you bumped but forgot to reinstall).

## Stable Release

Use a stable release when users should get it from the default install command.

Example: publish `0.1.10` as npm `latest`.

1. Bump the canonical version and stamp every manifest:

```bash
node scripts/sync_version.mjs 0.1.10
```

2. Run local checks:

```bash
npm run check
GITHUB_REF_NAME=v0.1.10 npm run check:release-version
python3 agent-wallet/tests/smoke_npm_installer.py
python3 agent-wallet/tests/smoke_install_agent_wallet.py
python3 agent-wallet/tests/smoke_version_consistency.py
npm --cache /tmp/npm-cache pack --dry-run
```

3. Commit the version change (VERSION + all stamped manifests):

```bash
git add -A
git commit -m "Release npm installer 0.1.10"
```

4. Create and push the release tag:

```bash
git tag -a v0.1.10 -m "v0.1.10"
git push origin main
git push origin v0.1.10
```

5. Check npm after GitHub Actions finishes:

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

Beta is the "earlier than users" channel: it publishes a real artifact to the
npm `beta` dist-tag (and a GitHub prerelease) without moving `latest`, so you can
test exactly what users would get before promoting it.

Example: publish `0.1.11-beta.1` as npm `beta`.

1. Bump + stamp the beta version:

```bash
node scripts/sync_version.mjs 0.1.11-beta.1
```

2. Run checks:

```bash
npm run check
GITHUB_REF_NAME=v0.1.11-beta.1 npm run check:release-version
npm --cache /tmp/npm-cache pack --dry-run
```

3. Commit, tag, and push:

```bash
git add -A
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

### Promote a beta to stable

Once a beta checks out, ship the same version as a stable `latest` release by
following the **Stable Release** steps with the promoted version number (e.g.
`0.1.11`). The update notice that runtimes show to agents reads the `latest`
dist-tag, so users are only nudged toward promoted releases, never betas.

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
```

Publish to ClawHub with the package-specific command documented by OpenClaw:

```bash
clawhub package publish .openclaw/extensions/agent-wallet --dry-run
clawhub package publish .openclaw/extensions/agent-wallet
```

Users then install them natively through OpenClaw:

```bash
openclaw plugins install clawhub:@agentlayertech/agent-wallet-plugin
```

GitHub Actions can publish the same packages automatically from tags and manual
dispatch through `.github/workflows/clawhub-plugins.yml`.

Required repository secret:

```text
CLAWHUB_TOKEN
```

Workflow behavior:

- `pull_request`: packs the plugin and runs ClawHub `--dry-run`
- `workflow_dispatch`: publishes or dry-runs based on the `dry_run` input
- `push` on `v*` tags: publishes the plugin automatically

The workflow currently publishes:

- `.openclaw/extensions/agent-wallet` as `bundle-plugin`

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
```

### Triggers

- `pull_request`
  - runs ClawHub publish in `--dry-run` mode for the plugin package
- `workflow_dispatch`
  - supports manual runs with a `dry_run` boolean input
- `push` on git tags matching `v*`
  - publishes the plugin package to ClawHub

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
