"""Unavailable vault locking cannot break unrelated wallet startup on Windows."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='vault-platform-import-') as directory:
    env = {**os.environ, 'PYTHONPATH': str(root), 'OPENCLAW_HOME': directory}
    subprocess.run([sys.executable, '-c', '''
import sys
sys.modules['fcntl'] = None
import agent_wallet.openclaw_runtime
import agent_wallet.kernel_cli
from agent_wallet.card_vault import CardVault
from agent_wallet.wallet_layer.base import WalletBackendError
vault = CardVault('platform-probe')
try:
    with vault.owner_lock():
        raise AssertionError('Vault silently proceeded without file locks')
except WalletBackendError:
    pass
assert not vault.root.exists(), 'Unsupported locking mutated vault files'
print('smoke_vault_platform_import: startup works; unsupported vault locking fails closed')
'''], cwd=root, env=env, check=True)
