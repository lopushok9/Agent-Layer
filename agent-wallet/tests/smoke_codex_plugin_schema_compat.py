"""Smoke test that Codex-facing wallet tool schemas avoid top-level combinators."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"
    module = _load_module(server_path, "codex_agent_wallet_server")

    definitions = module._build_tool_definitions()
    assert definitions, "Codex tool definitions must not be empty"
    for spec in definitions:
        schema = spec.get("input_schema")
        assert isinstance(schema, dict), f"{spec['name']} schema must be an object"
        assert schema.get("type") == "object", f"{spec['name']} schema must have top-level type=object"
        for forbidden in ("oneOf", "anyOf", "allOf", "enum", "not"):
            assert forbidden not in schema, f"{spec['name']} schema must not include top-level {forbidden}"

    print("smoke_codex_plugin_schema_compat: ok")


if __name__ == "__main__":
    main()
