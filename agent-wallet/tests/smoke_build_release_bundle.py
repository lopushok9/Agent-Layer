"""Smoke test for the release bundle builder."""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    temp_root = Path("/tmp/openclaw-build-release-bundle-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    source_root = temp_root / "source"
    output_dir = temp_root / "dist"
    source_root.mkdir(parents=True, exist_ok=True)

    for root_file in [
        ".env.example",
        ".gitignore",
        "AGENTS.md",
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "RELEASING.md",
        "install-from-github.sh",
        "requirements.txt",
        "setup.sh",
    ]:
        _write(source_root / root_file, f"{root_file}\n")

    _write(source_root / "agent-wallet" / "scripts" / "install_agent_wallet.py", "print('ok')\n")
    _write(source_root / "agent-wallet" / "graphify-out" / "cache.json", "{}\n")
    _write(source_root / "wdk-btc-wallet" / "package.json", '{"name":"wdk-btc-wallet"}\n')
    _write(source_root / "wdk-btc-wallet" / "node_modules" / "ignored.txt", "ignored\n")
    _write(source_root / "wdk-evm-wallet" / "package.json", '{"name":"wdk-evm-wallet"}\n')
    _write(source_root / ".openclaw" / "extensions" / "agent-wallet" / "index.ts", "export {};\n")
    _write(source_root / ".openclaw" / "extensions-local" / "cache.txt", "ignored\n")
    _write(source_root / "mcp-server" / "server.py", "print('mcp')\n")
    _write(source_root / "provider-gateway" / "requirements.txt", "httpx\n")
    _write(source_root / "solana-8004" / "package.json", '{"name":"solana-8004"}\n')
    _write(source_root / "agent-a2a-gateway" / "requirements.txt", "fastapi\n")

    _write(source_root / "landing" / "package.json", '{"name":"landing"}\n')
    _write(source_root / "docs" / "package.json", '{"name":"docs"}\n')
    _write(source_root / "bot_mvp.md", "local note\n")

    script = repo_root / "agent-wallet" / "scripts" / "build_release_bundle.py"
    result = subprocess.run(
        [
            "python3.11",
            str(script),
            "--source-root",
            str(source_root),
            "--output-dir",
            str(output_dir),
            "--version",
            "smoke-test",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    bundle_path = Path(payload["output_path"])
    assert bundle_path.exists()

    with tarfile.open(bundle_path, "r:gz") as archive:
        names = set(archive.getnames())

    bundle_root = "openclaw-agent-wallet-bundle-smoke-test"
    assert f"{bundle_root}/setup.sh" in names
    assert f"{bundle_root}/agent-wallet/scripts/install_agent_wallet.py" in names
    assert f"{bundle_root}/wdk-btc-wallet/package.json" in names
    assert f"{bundle_root}/wdk-evm-wallet/package.json" in names
    assert f"{bundle_root}/.openclaw/extensions/agent-wallet/index.ts" in names
    assert f"{bundle_root}/mcp-server/server.py" in names
    assert f"{bundle_root}/provider-gateway/requirements.txt" in names
    assert f"{bundle_root}/solana-8004/package.json" in names
    assert f"{bundle_root}/agent-a2a-gateway/requirements.txt" in names
    assert f"{bundle_root}/bundle-manifest.json" in names

    assert f"{bundle_root}/landing/package.json" not in names
    assert f"{bundle_root}/docs/package.json" not in names
    assert f"{bundle_root}/bot_mvp.md" not in names
    assert f"{bundle_root}/agent-wallet/graphify-out/cache.json" not in names
    assert f"{bundle_root}/wdk-btc-wallet/node_modules/ignored.txt" not in names
    assert f"{bundle_root}/.openclaw/extensions-local/cache.txt" not in names

    print("smoke_build_release_bundle: ok")


if __name__ == "__main__":
    main()
