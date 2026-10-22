"""Existing-card import uses only hidden owner input and encrypted storage."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_wallet.card_catalog import CardCatalog
from agent_wallet.card_runtime_secrets import CardRuntimeSecrets
from agent_wallet.card_vault import CardVault
from agent_wallet.card_vault_import import import_interactive
from agent_wallet.wallet_layer.base import WalletBackendError
from smoke_vault_execution import ExecutionChecks


class ImportChecks(unittest.TestCase):
    setUp = ExecutionChecks.setUp

    def test_hidden_import_encrypts_and_returns_only_safe_metadata(self):
        with patch('agent_wallet.card_vault_cli.require_terminal'), patch('agent_wallet.card_vault_import.getpass.getpass', side_effect=['4111 1111 1111 1111', '12/34', '123']), patch.object(CardVault, 'unlock', side_effect=AssertionError('no owner read')):
            safe = import_interactive(self.vault, 'Non-Reloadable U.S.')
        self.assertEqual(safe['status'], 'ready')
        self.assertEqual(safe['last4'], '1111')
        ref = safe['vault_reference']
        self.assertEqual(CardRuntimeSecrets(self.vault).load_for_executor(ref)['card.number'], '4111111111111111')
        self.assertIsNone(CardCatalog(self.vault).load(ref)['job'])
        self.assertNotIn('4111111111111111', json.dumps(safe))
        for file in self.vault.root.iterdir():
            self.assertNotIn('4111111111111111', file.read_text())

    def test_pipe_is_rejected_before_collecting_secrets(self):
        with patch('agent_wallet.card_vault_cli.sys.stdin.isatty', return_value=False), patch('agent_wallet.card_vault_import.getpass.getpass') as prompt:
            with self.assertRaises(WalletBackendError):
                import_interactive(self.vault, 'Non-Reloadable U.S.')
            prompt.assert_not_called()

    def test_invalid_card_is_not_saved(self):
        for values in (['4111111111111112', '12/34', '123'], ['4111111111111111', '13/34', '123'], ['4111111111111111', '12/34', 'x']):
            with self.subTest(values=values), patch('agent_wallet.card_vault_cli.require_terminal'), patch('agent_wallet.card_vault_import.getpass.getpass', side_effect=values):
                with self.assertRaises(WalletBackendError):
                    import_interactive(self.vault, 'Non-Reloadable U.S.')
                self.assertEqual(self.vault.references(), [])

    def test_catalog_failure_removes_partial_import(self):
        with patch('agent_wallet.card_vault_cli.require_terminal'), patch('agent_wallet.card_vault_import.getpass.getpass', side_effect=['4111111111111111', '12/34', '123']), patch.object(CardCatalog, 'track', side_effect=WalletBackendError('fixture')):
            with self.assertRaises(WalletBackendError):
                import_interactive(self.vault, 'Non-Reloadable U.S.')
        self.assertEqual(self.vault.references(), [])
        self.assertEqual(list(self.vault.root.glob('*.use')), [])


if __name__ == '__main__':
    unittest.main()
