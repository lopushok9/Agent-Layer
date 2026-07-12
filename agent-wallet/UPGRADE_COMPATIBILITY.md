# Upgrade Compatibility

The wallet installer supports direct upgrades from older production releases.
Compatibility code is removed according to the minimum supported source
version, not according to elapsed time or a fixed number of releases.

## Supported Floor

The current regression floor is `0.1.53`. CI must keep a direct upgrade fixture
at that floor until the project explicitly raises it in release documentation.

Raising the floor requires all of the following:

- a documented migration path for users below the new floor
- upgrade fixtures for the new floor and the latest stable release
- support and telemetry evidence that the retired path is no longer material
- a release note naming the removed compatibility behavior

## Compatibility Paths

| Path | Purpose | Removal condition |
|---|---|---|
| JavaScript boot-key fallback | Updates runtimes that predate the verified Python installer resolver. | The supported floor includes `resolve_boot_key_for_installer`, and direct-upgrade fixtures no longer require the fallback. |
| Directory runtime-pointer migration | Converts pre-versioned `current/` directories into release entries. | The supported floor guarantees symlink-based runtime pointers. |
| Hermes legacy adoption | Recognizes an AgentLayer plugin installed before the ownership registry. | The supported floor guarantees an `integrations.json` Hermes ownership entry. |
| Codex legacy adoption | Recognizes a matching local marketplace registration and AgentLayer manifest. | The supported floor guarantees an `integrations.json` Codex ownership entry. |
| Claude Code legacy adoption | Recognizes the AgentLayer marketplace and plugin manifest before registry ownership. | The supported floor guarantees an `integrations.json` Claude Code ownership entry. |

## Safety Rules

- Legacy adoption requires independent registration and manifest evidence.
- Unknown or externally managed integrations are never adopted automatically.
- Compatibility paths must not weaken boot-key, sealed-state, approval, or
  signing validation.
- Every retained path needs a direct-upgrade smoke test or an explicit fixture
  showing why it remains necessary.
