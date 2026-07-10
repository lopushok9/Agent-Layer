# Versioning Guide

A short, practical guide to how the project version works. One number, one
source of truth, the same everywhere — from your local editors to what users
install.

## The one rule

**The root `VERSION` file is canonical. Never hand-edit any other version
field.** Everything else is stamped from it.

```text
VERSION            ← the only file a human edits
```

Eleven derived manifests carry the same version and are generated, not edited:

| Surface | File |
|---|---|
| npm installer | `package.json` |
| Python package | `agent-wallet/pyproject.toml`, `agent-wallet/agent_wallet/__init__.py` |
| OpenClaw | `.openclaw/extensions/agent-wallet/package.json`, `.openclaw/extensions/agent-wallet/openclaw.plugin.json`, `agent-wallet/openclaw.plugin.json` |
| Codex | `codex/plugins/agent-wallet/.codex-plugin/plugin.json` |
| Claude Code | `claude-code/plugins/agent-wallet/.claude-plugin/plugin.json` |
| Hermes | `hermes/plugins/agent_wallet/plugin.yaml` |
| wdk services | `wdk-btc-wallet/package.json`, `wdk-evm-wallet/package.json` |

The registry of these targets lives in `scripts/version_targets.mjs`.

## Everyday commands

```bash
# Stamp the current VERSION into all 11 manifests
npm run version:sync

# Bump VERSION and stamp in one step
node scripts/sync_version.mjs 0.1.34

# Verify everything agrees with VERSION (and with a v* tag, if set).
# This is what CI runs on every PR/push — drift cannot be merged.
npm run check:release-version

# Am I consistent locally?
node agent-wallet/tests/smoke_version_consistency.py
```

## Local release: make YOUR editors run the new version

When you bump locally and want OpenClaw, Codex, and Claude Code to all run the
new version from the working tree:

```bash
npm run release:local -- 0.1.34            # bump → stamp → check → reinstall all
npm run release:local -- 0.1.34 --dry-run  # preview the steps, change nothing
```

It runs five steps in order: `sync_version` → `check_version` →
`install_openclaw` → `install_codex` → `install_claude_code`. Because it installs
from the same files that ship to npm/ClawHub, your local install matches what a
user gets.

### Did I forget to reinstall?

```bash
wallet doctor     # look for the runtime_in_sync check
wallet status     # runtime_in_sync: { in_sync, active_version, cli_version }
```

`in_sync: false` means the installed runtime lags the repo version — run
`release:local`. (Informational; it never fails doctor.)

## Publishing (stable + beta)

Publishing is driven by a `v*` git tag — see `RELEASING.md` for the full steps.
In short:

```bash
node scripts/sync_version.mjs 0.1.34
npm run check
git add -A && git commit -m "Release npm installer 0.1.34"
git tag -a v0.1.34 -m "v0.1.34" && git push origin main && git push origin v0.1.34
```

The tag must equal `VERSION` or CI fails before publishing. The same tag ships
npm + ClawHub in lockstep.

### Test before users (the beta channel)

Cut a `-beta.N` version to publish a real artifact to the npm `beta` dist-tag
(and a GitHub prerelease) **without moving `latest`**:

```bash
node scripts/sync_version.mjs 0.1.34-beta.1
# commit, tag v0.1.34-beta.1, push
npx @agentlayer.tech/wallet@beta install   # test the exact artifact
```

When it checks out, run the `promote npm beta` workflow for the published beta
version. It acceptance-tests that exact immutable tarball before moving the npm
`latest` dist-tag; no rebuild is involved. The promoted artifact keeps its
prerelease version string, while agents only receive an update notice after it
has entered the `latest` channel. See `RELEASING.md` for token and environment
requirements.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `check:release-version` fails with "version mismatch" | `npm run version:sync` then commit |
| `check:release-version` fails with "tag/version mismatch" | The `v*` tag must equal `VERSION` |
| `wallet doctor` shows `runtime_in_sync: false` | `npm run release:local -- <VERSION>` |
| Editor still runs old version after release | Re-run `release:local`; Claude Code keeps a version-keyed cache copy that the install refreshes |
