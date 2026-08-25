"""Persistent local lifecycle registry for optional AgentLayer connectors."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from agent_wallet.config import resolve_openclaw_home
from agent_wallet.connectors.manifest import validate_connector_manifest
from agent_wallet.file_ops import atomic_write_text


REGISTRY_SCHEMA_VERSION = 1


class ConnectorRegistryError(RuntimeError):
    """Raised when connector lifecycle state is invalid or unsafe to change."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _manifest_digest(manifest: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(manifest).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    """Serialize cross-process registry mutations with an OS advisory lock."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        os.chmod(path, 0o600)
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ConnectorRegistry:
    """Install and toggle immutable connector manifests outside runtime releases."""

    def __init__(self, root: Path | None = None):
        runtime_base = resolve_openclaw_home() / "agent-wallet-runtime"
        self.root = (root or (runtime_base / "connectors")).expanduser().resolve()
        self.registry_path = self.root / "registry.json"
        self.manifests_root = self.root / "manifests"
        self.lock_path = self.root / ".registry.lock"

    @staticmethod
    def _empty_registry() -> dict[str, Any]:
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "connectors": {},
        }

    def read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty_registry()
        except (OSError, json.JSONDecodeError) as exc:
            raise ConnectorRegistryError(f"Connector registry is unreadable: {exc}") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION
            or not isinstance(payload.get("connectors"), dict)
        ):
            raise ConnectorRegistryError("Connector registry schema is invalid.")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        atomic_write_text(
            self.registry_path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            mode=0o600,
        )

    def _manifest_path(self, connector_id: str, version: str) -> Path:
        return self.manifests_root / connector_id / f"{version}.json"

    def _recorded_manifest_path(self, relative_path: Any) -> Path:
        if not isinstance(relative_path, str) or not relative_path:
            raise ConnectorRegistryError("Installed connector manifest path is missing.")
        candidate = (self.root / relative_path).resolve()
        manifests_root = self.manifests_root.resolve()
        try:
            candidate.relative_to(manifests_root)
        except ValueError as exc:
            raise ConnectorRegistryError("Installed connector manifest path escapes the registry.") from exc
        return candidate

    def load_manifest(self, connector_id: str, version: str | None = None) -> dict[str, Any]:
        registry = self.read()
        entry = registry["connectors"].get(connector_id)
        if not isinstance(entry, dict):
            raise ConnectorRegistryError(f"Connector is not installed: {connector_id}.")
        selected_version = version or entry.get("enabled_version")
        if not isinstance(selected_version, str) or not selected_version:
            raise ConnectorRegistryError(f"Connector is not enabled: {connector_id}.")
        versions = entry.get("installed_versions")
        version_entry = versions.get(selected_version) if isinstance(versions, dict) else None
        if not isinstance(version_entry, dict):
            raise ConnectorRegistryError(
                f"Connector version is not installed: {connector_id}@{selected_version}."
            )
        path = self._recorded_manifest_path(version_entry.get("manifest_path"))
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConnectorRegistryError(
                f"Installed manifest is unreadable: {connector_id}@{selected_version}: {exc}"
            ) from exc
        validated = validate_connector_manifest(manifest)
        actual_digest = _manifest_digest(validated)
        if actual_digest != version_entry.get("manifest_digest"):
            raise ConnectorRegistryError(
                f"Installed manifest digest mismatch: {connector_id}@{selected_version}."
            )
        return validated

    def install(
        self,
        manifest_payload: dict[str, Any],
        *,
        source: str,
        enable: bool = False,
    ) -> dict[str, Any]:
        manifest = validate_connector_manifest(manifest_payload)
        connector_id = str(manifest["id"])
        version = str(manifest["version"])
        manifest_digest = _manifest_digest(manifest)
        manifest_path = self._manifest_path(connector_id, version)
        relative_manifest_path = manifest_path.relative_to(self.root).as_posix()

        with _exclusive_file_lock(self.lock_path):
            registry = self.read()
            connectors = registry["connectors"]
            entry = connectors.get(connector_id)
            if entry is None:
                entry = {
                    "id": connector_id,
                    "name": manifest["name"],
                    "publisher": manifest["publisher"],
                    "enabled_version": None,
                    "installed_versions": {},
                    "restart_required": False,
                }
                connectors[connector_id] = entry
            elif not isinstance(entry, dict) or not isinstance(
                entry.get("installed_versions"), dict
            ):
                raise ConnectorRegistryError(f"Registry entry is invalid: {connector_id}.")

            existing = entry["installed_versions"].get(version)
            if isinstance(existing, dict) and existing.get("manifest_digest") != manifest_digest:
                raise ConnectorRegistryError(
                    f"Connector versions are immutable: {connector_id}@{version} is already installed."
                )

            if manifest_path.exists():
                try:
                    disk_manifest = validate_connector_manifest(
                        json.loads(manifest_path.read_text(encoding="utf-8"))
                    )
                except Exception as exc:
                    raise ConnectorRegistryError(
                        f"Existing connector manifest is invalid: {connector_id}@{version}."
                    ) from exc
                if _manifest_digest(disk_manifest) != manifest_digest:
                    raise ConnectorRegistryError(
                        f"Connector versions are immutable: {connector_id}@{version} differs on disk."
                    )
            else:
                atomic_write_text(
                    manifest_path,
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    mode=0o600,
                )

            now = _timestamp()
            if not isinstance(existing, dict):
                entry["installed_versions"][version] = {
                    "version": version,
                    "trust": manifest["trust"],
                    "artifact_digest": manifest.get("artifact_digest"),
                    "manifest_digest": manifest_digest,
                    "manifest_path": relative_manifest_path,
                    "source": str(source),
                    "installed_at": now,
                }
            if enable and entry.get("enabled_version") != version:
                entry["enabled_version"] = version
                entry["restart_required"] = True
            entry["updated_at"] = now
            registry["updated_at"] = now
            self._write(registry)
            return self.describe(connector_id, registry=registry)

    def enable(self, connector_id: str, *, version: str | None = None) -> dict[str, Any]:
        with _exclusive_file_lock(self.lock_path):
            registry = self.read()
            entry = registry["connectors"].get(connector_id)
            if not isinstance(entry, dict):
                raise ConnectorRegistryError(f"Connector is not installed: {connector_id}.")
            versions = entry.get("installed_versions")
            if not isinstance(versions, dict) or not versions:
                raise ConnectorRegistryError(f"Connector has no installed versions: {connector_id}.")
            if version is None and len(versions) != 1:
                raise ConnectorRegistryError(
                    f"Specify a version when enabling {connector_id}; multiple versions are installed."
                )
            selected = version or next(iter(versions))
            if selected not in versions:
                raise ConnectorRegistryError(
                    f"Connector version is not installed: {connector_id}@{selected}."
                )
            self.load_manifest(connector_id, selected)
            if entry.get("enabled_version") != selected:
                entry["enabled_version"] = selected
                entry["restart_required"] = True
                entry["updated_at"] = _timestamp()
                registry["updated_at"] = entry["updated_at"]
                self._write(registry)
            return self.describe(connector_id, registry=registry)

    def disable(self, connector_id: str) -> dict[str, Any]:
        with _exclusive_file_lock(self.lock_path):
            registry = self.read()
            entry = registry["connectors"].get(connector_id)
            if not isinstance(entry, dict):
                raise ConnectorRegistryError(f"Connector is not installed: {connector_id}.")
            if entry.get("enabled_version") is not None:
                entry["enabled_version"] = None
                entry["restart_required"] = True
                entry["updated_at"] = _timestamp()
                registry["updated_at"] = entry["updated_at"]
                self._write(registry)
            return self.describe(connector_id, registry=registry)

    def remove(self, connector_id: str, *, version: str | None = None) -> dict[str, Any]:
        with _exclusive_file_lock(self.lock_path):
            registry = self.read()
            entry = registry["connectors"].get(connector_id)
            if not isinstance(entry, dict):
                raise ConnectorRegistryError(f"Connector is not installed: {connector_id}.")
            enabled_version = entry.get("enabled_version")
            selected = version or enabled_version
            if not isinstance(selected, str) or not selected:
                versions = entry.get("installed_versions")
                if not isinstance(versions, dict) or len(versions) != 1:
                    raise ConnectorRegistryError("Specify the connector version to remove.")
                selected = next(iter(versions))
            if enabled_version == selected:
                raise ConnectorRegistryError(
                    f"Disable {connector_id}@{selected} before removing it."
                )
            versions = entry.get("installed_versions")
            removed = versions.pop(selected, None) if isinstance(versions, dict) else None
            if not isinstance(removed, dict):
                raise ConnectorRegistryError(
                    f"Connector version is not installed: {connector_id}@{selected}."
                )
            manifest_path = self._recorded_manifest_path(removed.get("manifest_path"))
            try:
                manifest_path.unlink()
            except FileNotFoundError:
                pass
            if not versions:
                registry["connectors"].pop(connector_id, None)
            else:
                entry["updated_at"] = _timestamp()
            registry["updated_at"] = _timestamp()
            self._write(registry)
            return {
                "id": connector_id,
                "removed_version": selected,
                "removed": True,
                "restart_required": False,
            }

    def describe(
        self,
        connector_id: str,
        *,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = registry or self.read()
        entry = payload["connectors"].get(connector_id)
        if not isinstance(entry, dict):
            raise ConnectorRegistryError(f"Connector is not installed: {connector_id}.")
        versions = entry.get("installed_versions")
        version_items = versions if isinstance(versions, dict) else {}
        enabled_version = entry.get("enabled_version")
        return {
            "id": connector_id,
            "name": entry.get("name"),
            "publisher": entry.get("publisher"),
            "enabled": isinstance(enabled_version, str) and bool(enabled_version),
            "enabled_version": enabled_version,
            "installed_versions": sorted(version_items),
            "enabled_trust": (
                version_items.get(enabled_version, {}).get("trust") if enabled_version else None
            ),
            "restart_required": bool(entry.get("restart_required")),
        }

    def list(self) -> list[dict[str, Any]]:
        registry = self.read()
        return [
            self.describe(connector_id, registry=registry)
            for connector_id in sorted(registry["connectors"])
        ]
