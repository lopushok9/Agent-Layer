"""Client/broker contract: no-key auto access, encrypted credentials, legacy direct sessions."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from starlette.applications import Starlette
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'provider-gateway'))
import kernel_broker as broker
from agent_wallet.card_vault import CardVault
from agent_wallet.kernel_browser import KernelBrowser
from agent_wallet.kernel_gateway import KernelGateway
from agent_wallet.wallet_layer.base import WalletBackendError


class ClientContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='kernel-client-contract-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.patches = []
        self.start(patch.dict(os.environ, {
            'OPENCLAW_HOME': temp.name, 'KERNEL_SHARED_ENABLED': 'true',
            'KERNEL_API_KEY': 'test-server-key', 'KERNEL_PROJECT_ID': 'test-project',
            'KERNEL_BROKER_DB_PATH': str(self.home / 'broker.sqlite'),
        }))
        self.start(patch('agent_wallet.card_runtime_secrets.resolve_wallet_master_key', return_value='isolated-runtime-master'))
        self.start(patch('agent_wallet.kernel_gateway.resolve_kernel_gateway_url', return_value='http://test'))
        self.start(patch('agent_wallet.kernel_browser.resolve_kernel_api_key', return_value=''))
        self.start(patch('agent_wallet.vault_executor.resolve_public_destination', new=AsyncMock(return_value=('example.com', '93.184.216.34'))))
        self.vault = CardVault('isolated-client')
        self.vault.initialize('isolated-fixture-password')
        self.browser = KernelBrowser(self.vault)
        self.provider = self.start(patch.object(broker, 'upstream', side_effect=self.upstream))
        self.calls = self.start(patch('agent_wallet.kernel_browser.KernelClient.call', new=AsyncMock(return_value={'success': True, 'result': {'url': 'https://example.com'}})))
        original = httpx.AsyncClient
        transport = httpx.ASGITransport(app=Starlette(routes=broker.routes))
        self.start(patch('agent_wallet.kernel_gateway.httpx.AsyncClient', side_effect=lambda **kw: original(transport=transport, **kw)))

    def start(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()

    async def upstream(self, method, path, project, body=None, **kwargs):
        if method == 'POST' and path == '/browsers':
            return {'session_id': 'scoped-browser'}
        if method == 'POST' and path == '/org/api_keys':
            return {**body, 'id': 'scoped-key-id', 'key': 'test-private-session-credential'}
        return {}

    async def test_no_key_opens_and_closes_shared_without_returning_credentials(self):
        result = await self.browser.invoke({'action': 'open', 'url': 'https://example.com', 'user_intent': True})
        self.assertEqual(result['connection_mode'], 'shared')
        self.assertNotIn('test-private-session-credential', json.dumps(result))
        ref = result['browser_reference']
        state = self.browser.storage.load(ref)
        self.assertEqual(state['session_key'], 'test-private-session-credential')
        for file in self.vault.root.iterdir():
            self.assertNotIn(b'test-private-session-credential', file.read_bytes())
        client = self.browser.client(state)
        self.assertEqual(client.key, state['session_key'])
        closed = await self.browser.invoke({'action': 'close', 'browser_reference': ref})
        self.assertFalse(closed['cleanup_pending'])
        self.assertNotIn('session_key', self.browser.storage.load(ref))
        with self.assertRaises(WalletBackendError):
            await self.browser.invoke({'action': 'observe', 'browser_reference': ref})

    async def test_existing_personal_connection_and_legacy_records_remain_direct(self):
        with patch('agent_wallet.kernel_browser.resolve_kernel_api_key', return_value='original-personal-key'):
            self.calls.return_value = {'session_id': 'original-browser', 'success': True, 'result': {}}
            result = await self.browser.invoke({'action': 'open', 'url': 'https://example.com', 'user_intent': True})
            self.assertEqual(result['connection_mode'], 'direct')
            self.provider.assert_not_called()
            self.assertEqual(self.browser.client({'session_id': 'legacy-without-mode'}).key, 'original-personal-key')

    async def test_expired_shared_record_fails_without_reallocation(self):
        with self.assertRaises(WalletBackendError):
            self.browser.client({'connection_mode': 'shared', 'session_key': 'expired-key', 'lease_expires_at': time.time() - 1})
        self.provider.assert_not_called()
        self.calls.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
