"""Build a release bundle tarball for the OpenClaw wallet/plugin runtime."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

DEFAULT_BUNDLE_PREFIX = "openclaw-agent-wallet-bundle"
INCLUDED_ROOT_FILES = [
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "RELEASING.md",
    "VERSION",
    "install-from-github.sh",
    "requirements.txt",
    "setup.sh",
]
# Must cover every setup.sh require_path and mirror the npm package `files`
# allowlist (RELEASING.md "What Ships") — the bundle is the same runtime users
# get from npx, just delivered as a GitHub Release asset.
INCLUDED_TOP_LEVEL_DIRS = [
    ".claude-plugin",
    ".openclaw",
    "agent-wallet",
    "bin",
    "claude-code",
    "codex",
    "hermes",
    "scripts",
    "wdk-btc-wallet",
    "wdk-evm-wallet",
]
EXCLUDED_EXACT_RELATIVE_PATHS = {
    ".openclaw/extensions-local",
    ".openclaw/openclaw.local.example.json",
    ".openclaw/extensions/pay-bridge",
}
EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "extensions-local",
    "graphify-out",
    "__pycache__",
    "dist",
    "node_modules",
}
EXCLUDED_FILE_NAMES = {
    ".DS_Store",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_output_dir() -> Path:
    return _repo_root() / "dist"


def _git_version(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            check=True,
        )
        version = result.stdout.strip()
        if version:
            return version.replace("/", "-")
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _bundle_root_name(version: str) -> str:
    return f"{DEFAULT_BUNDLE_PREFIX}-{version}"


def _should_skip(path: Path, source_root: Path) -> bool:
    relative = path.relative_to(source_root)
    relative_text = relative.as_posix()
    if relative_text in EXCLUDED_EXACT_RELATIVE_PATHS:
        return True
    for part in relative.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    return any(path.name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def _iter_paths(base_path: Path, source_root: Path) -> list[Path]:
    if not base_path.exists():
        return []
    if base_path.is_file():
        return [] if _should_skip(base_path, source_root) else [base_path]

    collected: list[Path] = []
    for path in sorted(base_path.rglob("*")):
        if _should_skip(path, source_root):
            continue
        collected.append(path)
    return collected


def _normalize_tar_name(bundle_root: str, source_root: Path, path: Path) -> str:
    relative = PurePosixPath(path.relative_to(source_root).as_posix())
    return str(PurePosixPath(bundle_root) / relative)


def _build_manifest(source_root: Path, version: str, bundle_root: str) -> bytes:
    payload = {
        "bundle_prefix": DEFAULT_BUNDLE_PREFIX,
        "bundle_root": bundle_root,
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "included_root_files": INCLUDED_ROOT_FILES,
        "included_top_level_dirs": INCLUDED_TOP_LEVEL_DIRS,
        "excluded_dir_names": sorted(EXCLUDED_DIR_NAMES),
        "excluded_file_names": sorted(EXCLUDED_FILE_NAMES),
        "excluded_suffixes": sorted(EXCLUDED_SUFFIXES),
        "excluded_exact_relative_paths": sorted(EXCLUDED_EXACT_RELATIVE_PATHS),
    }
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default=str(_repo_root()))
    parser.add_argument("--output-dir", default=str(_default_output_dir()))
    parser.add_argument("--output-file", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--bundle-root", default="")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    source_root = Path(args.source_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    version = args.version.strip() or _git_version(source_root)
    bundle_root = args.bundle_root.strip() or _bundle_root_name(version)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output_file).expanduser().resolve()
        if args.output_file.strip()
        else output_dir / f"{bundle_root}.tar.gz"
    )

    included_paths: list[Path] = []
    for relative in INCLUDED_ROOT_FILES + INCLUDED_TOP_LEVEL_DIRS:
        included_paths.extend(_iter_paths(source_root / relative, source_root))

    manifest_bytes = _build_manifest(source_root, version, bundle_root)
    with tarfile.open(output_path, "w:gz") as archive:
        for path in included_paths:
            archive.add(path, arcname=_normalize_tar_name(bundle_root, source_root, path), recursive=False)

        manifest_info = tarfile.TarInfo(name=f"{bundle_root}/bundle-manifest.json")
        manifest_info.size = len(manifest_bytes)
        manifest_info.mtime = int(datetime.now(timezone.utc).timestamp())
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))

    print(
        json.dumps(
            {
                "ok": True,
                "source_root": str(source_root),
                "output_path": str(output_path),
                "bundle_root": bundle_root,
                "version": version,
                "included_root_files": INCLUDED_ROOT_FILES,
                "included_top_level_dirs": INCLUDED_TOP_LEVEL_DIRS,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
