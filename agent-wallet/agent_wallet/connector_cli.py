"""JSON CLI for installing and managing optional AgentLayer connectors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent_wallet.connectors.manifest import ConnectorManifestError
from agent_wallet.connectors.registry import ConnectorRegistry, ConnectorRegistryError


MAX_MANIFEST_BYTES = 1024 * 1024


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _load_manifest_file(value: str) -> tuple[dict[str, Any], str]:
    path = Path(value).expanduser().resolve()
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ConnectorRegistryError(f"Connector manifest cannot be read: {path}: {exc}") from exc
    if size > MAX_MANIFEST_BYTES:
        raise ConnectorRegistryError(
            f"Connector manifest exceeds the {MAX_MANIFEST_BYTES}-byte limit."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConnectorRegistryError(f"Connector manifest is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConnectorRegistryError("Connector manifest root must be an object.")
    return payload, str(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wallet connectors")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List locally installed connectors.")

    info = subparsers.add_parser("info", help="Show one installed connector.")
    info.add_argument("connector_id")

    install = subparsers.add_parser("install", help="Install an immutable connector manifest.")
    install.add_argument("manifest", help="Path to a connector manifest JSON file.")
    install.add_argument("--enable", action="store_true", help="Enable this exact version.")

    enable = subparsers.add_parser("enable", help="Enable an installed connector version.")
    enable.add_argument("connector_id")
    enable.add_argument("--version", default=None)

    disable = subparsers.add_parser("disable", help="Disable an installed connector.")
    disable.add_argument("connector_id")

    remove = subparsers.add_parser("remove", help="Remove a disabled connector version.")
    remove.add_argument("connector_id")
    remove.add_argument("--version", default=None)
    remove.add_argument("--yes", action="store_true", help="Confirm removal.")

    subparsers.add_parser("doctor", help="Validate the registry and all installed manifests.")
    return parser


def _doctor(registry: ConnectorRegistry) -> dict[str, Any]:
    entries = registry.list()
    checks: list[dict[str, Any]] = []
    ok = True
    for entry in entries:
        connector_id = str(entry["id"])
        for version in entry["installed_versions"]:
            try:
                registry.load_manifest(connector_id, str(version))
                checks.append(
                    {
                        "connector_id": connector_id,
                        "version": version,
                        "ok": True,
                    }
                )
            except (ConnectorManifestError, ConnectorRegistryError) as exc:
                ok = False
                checks.append(
                    {
                        "connector_id": connector_id,
                        "version": version,
                        "ok": False,
                        "error": str(exc),
                    }
                )
    return {
        "ok": ok,
        "registry_path": str(registry.registry_path),
        "connector_count": len(entries),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    registry = ConnectorRegistry()
    try:
        if args.command == "list":
            _print({"ok": True, "connectors": registry.list()})
            return 0
        if args.command == "info":
            _print({"ok": True, "connector": registry.describe(args.connector_id)})
            return 0
        if args.command == "install":
            manifest, source = _load_manifest_file(args.manifest)
            connector = registry.install(manifest, source=source, enable=bool(args.enable))
            _print({"ok": True, "connector": connector})
            return 0
        if args.command == "enable":
            connector = registry.enable(args.connector_id, version=args.version)
            _print({"ok": True, "connector": connector})
            return 0
        if args.command == "disable":
            connector = registry.disable(args.connector_id)
            _print({"ok": True, "connector": connector})
            return 0
        if args.command == "remove":
            if not args.yes:
                raise ConnectorRegistryError("remove requires --yes after the connector is disabled.")
            result = registry.remove(args.connector_id, version=args.version)
            _print({"ok": True, **result})
            return 0
        if args.command == "doctor":
            result = _doctor(registry)
            _print(result)
            return 0 if result["ok"] else 1
        raise ConnectorRegistryError(f"Unsupported connectors command: {args.command}.")
    except (ConnectorManifestError, ConnectorRegistryError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

