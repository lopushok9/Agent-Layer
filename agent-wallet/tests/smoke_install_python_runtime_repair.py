"""Smoke test repair of a partially created shared Python runtime."""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch


def _installer_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "install_agent_wallet.py"
    spec = importlib.util.spec_from_file_location("installer_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    installer = _installer_module()
    temp_root = Path(tempfile.mkdtemp(prefix="agent-wallet-runtime-repair-"))
    try:
        runtime_root = temp_root / "runtime" / "releases" / "staging"
        release_venv = runtime_root / "agent-wallet" / ".runtime-venv"
        shared_venv = temp_root / "runtime" / "shared" / "python" / "test-fingerprint" / "venv"
        python_bin = shared_venv / "bin" / "python"
        python_bin.parent.mkdir(parents=True)
        python_bin.touch()

        with (
            patch.object(installer, "_shared_dependency_links_supported", return_value=True),
            patch.object(installer, "_python_runtime_fingerprint", return_value="test-fingerprint"),
            patch.object(installer, "_python_runtime_is_healthy", return_value=False),
            patch.object(installer, "_bootstrap_venv_pip") as bootstrap_pip,
            patch.object(installer, "_pip_install_editable") as pip_install,
        ):
            _, created, plan = installer._ensure_python_runtime(
                release_venv,
                temp_root / "package",
                runtime_root,
            )

        assert created is False
        assert plan["action"] == "repair"
        assert bootstrap_pip.call_args.args[0].resolve() == python_bin.resolve()
        assert pip_install.call_args.args[0].resolve() == python_bin.resolve()
        assert pip_install.call_args.args[1] == temp_root / "package"
        assert release_venv.resolve() == shared_venv.resolve()
    finally:
        shutil.rmtree(temp_root)

    print("smoke_install_python_runtime_repair: ok")


if __name__ == "__main__":
    main()
