"""Signed ownership, replay, scoped credentials and durable cleanup regressions.

--live exercises two disposable real Kernel browsers. Credentials must be in the
process environment; no developer vault, card or payment is used.
"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
from nacl.signing import SigningKey
from starlette.applications import Starlette
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_broker as broker

LIVE = '--live' in sys.argv
if LIVE:
    sys.argv.remove('--live')


def headers(key, path, body):
    timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
    msg = '\n'.join((broker.PROTOCOL, 'POST', path, timestamp, nonce,
                     hashlib.sha256(body).hexdigest())).encode()
    return {'X-AgentLayer-Client-Key': bytes(key.verify_key).hex(),
            'X-AgentLayer-Timestamp': timestamp, 'X-AgentLayer-Nonce': nonce,
            'X-AgentLayer-Signature': key.sign(msg).signature.hex(),
            'Content-Type': 'application/json'}


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            'KERNEL_SHARED_ENABLED': 'true', 'KERNEL_PROJECT_ID': 'test-project',
            'KERNEL_API_KEY': 'test-operator-key',
            'KERNEL_BROKER_DB_PATH': str(Path(self.temp.name) / 'broker.sqlite'),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=Starlette(routes=broker.routes)), base_url='http://test')
        self.addAsyncCleanup(self.client.aclose)
        self.a, self.b = SigningKey.generate(), SigningKey.generate()
        self.calls = []
        self.policy_valid = True
        self.mock = patch.object(broker, 'upstream', self.fake_upstream)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    async def fake_upstream(self, method, path, project, body=None, **kwargs):
        self.calls.append((method, path, body))
        if method == 'POST' and path == '/browsers':
            return {'session_id': 'browser-' + body['name']}
        if method == 'POST' and path == '/org/api_keys':
            return {**body, 'id': 'test-key-' + body['name'], 'key': 'test-session-secret-123456',
                    'policy': body['policy'] if self.policy_valid else {}}
        return {}

    async def request(self, key, path=broker.CREATE_PATH, data=None):
        raw = json.dumps(data if data is not None else {'lease_id': uuid.uuid4().hex}).encode()
        return await self.client.post(path, content=raw, headers=headers(key, path, raw))

    async def test_invalid_proof_and_mutated_body_allocate_nothing(self):
        r = await self.client.post(broker.CREATE_PATH, json={'lease_id': uuid.uuid4().hex})
        self.assertEqual(r.status_code, 401)
        body = json.dumps({'lease_id': uuid.uuid4().hex}).encode()
        r = await self.client.post(broker.CREATE_PATH, content=body + b' ', headers=headers(self.a, broker.CREATE_PATH, body))
        self.assertEqual(r.status_code, 401)
        self.assertFalse(self.calls)

    async def test_replay_and_duplicate_lease_do_not_create_twice(self):
        lease = uuid.uuid4().hex
        raw = json.dumps({'lease_id': lease}).encode()
        proof = headers(self.a, broker.CREATE_PATH, raw)
        self.assertEqual((await self.client.post(broker.CREATE_PATH, content=raw, headers=proof)).status_code, 200)
        self.assertEqual((await self.client.post(broker.CREATE_PATH, content=raw, headers=proof)).status_code, 409)
        self.assertEqual((await self.request(self.a, data={'lease_id': lease})).status_code, 409)
        self.assertEqual(sum(m == 'POST' and p == '/browsers' for m, p, _ in self.calls), 1)

    async def test_owner_boundary_and_no_plaintext_key_on_disk(self):
        lease = uuid.uuid4().hex
        r = await self.request(self.a, data={'lease_id': lease})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['cache-control'], 'no-store')
        path = broker.CREATE_PATH + '/' + lease + '/close'
        self.assertEqual((await self.request(self.b, path, {})).status_code, 404)
        self.assertFalse(any(m == 'DELETE' for m, _, _ in self.calls))
        r = await self.request(self.a, path, {})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['closed'])
        for file in Path(self.temp.name).iterdir():
            self.assertNotIn(b'test-session-secret', file.read_bytes())

    async def test_upstream_policy_must_be_confirmed_then_cleanup(self):
        self.policy_valid = False
        lease = uuid.uuid4().hex
        r = await self.request(self.a, data={'lease_id': lease})
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('test-session-secret', r.text)
        await broker.cleanup_due()
        self.assertTrue(any(m == 'DELETE' and p.startswith('/browsers/') for m, p, _ in self.calls))
        self.assertTrue(any(m == 'DELETE' and p.startswith('/org/api_keys/') for m, p, _ in self.calls))

    async def test_quota_reserved_before_provider_calls(self):
        with patch.dict(os.environ, {'KERNEL_MAX_ACTIVE_PER_CLIENT': '1'}):
            self.assertEqual((await self.request(self.a)).status_code, 200)
            self.assertEqual((await self.request(self.a)).status_code, 429)
            self.assertEqual((await self.request(self.b)).status_code, 200)

    async def test_expiry_cleanup_survives_restart_and_disabled_creation(self):
        lease = uuid.uuid4().hex
        self.assertEqual((await self.request(self.a, data={'lease_id': lease})).status_code, 200)
        with closing(broker.database()) as db:
            db.execute('UPDATE kernel_leases SET expires=? WHERE id=?', (int(time.time()) - 1, lease))
        with patch.dict(os.environ, {'KERNEL_SHARED_ENABLED': 'false'}):
            self.assertEqual((await self.request(self.b)).status_code, 503)
            await broker.cleanup_due()
            r = await self.request(self.a, broker.CREATE_PATH + '/' + lease + '/close', {})
            self.assertTrue(r.json()['closed'])


@unittest.skipUnless(LIVE, 'real Kernel calls are opt-in')
class LiveIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_disposable_browsers_and_scoped_access(self):
        self.assertTrue(os.getenv('KERNEL_API_KEY') and os.getenv('KERNEL_PROJECT_ID'))
        with tempfile.TemporaryDirectory(prefix='kernel-live-release-') as directory:
            with patch.dict(os.environ, {'KERNEL_SHARED_ENABLED': 'true', 'KERNEL_BROKER_DB_PATH': str(Path(directory) / 'broker.sqlite')}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=Starlette(routes=broker.routes)), base_url='http://test') as client:
                    allocations = []
                    try:
                        for _ in range(2):
                            key, lease = SigningKey.generate(), uuid.uuid4().hex
                            allocations.append((key, lease, None))
                            raw = json.dumps({'lease_id': lease}).encode()
                            r = await client.post(broker.CREATE_PATH, content=raw, headers=headers(key, broker.CREATE_PATH, raw))
                            self.assertEqual(r.status_code, 200, r.text)
                            allocations[-1] = key, lease, r.json()
                        a, b = allocations
                        async with httpx.AsyncClient(base_url='https://api.onkernel.com', headers={
                            'Authorization': 'Bearer ' + a[2]['session_key'],
                            'X-Kernel-Project-Id': os.environ['KERNEL_PROJECT_ID']}, trust_env=False, timeout=30) as scoped:
                            self.assertEqual((await scoped.get('/browsers/' + a[2]['session_id'])).status_code, 200)
                            self.assertIn((await scoped.get('/browsers/' + b[2]['session_id'])).status_code, (403, 404))
                            self.assertIn((await scoped.post('/browsers', json={'headless': True})).status_code, (401, 403))
                            self.assertIn((await scoped.get('/org/api_keys')).status_code, (401, 403))
                            listed = await scoped.get('/browsers')
                            self.assertEqual(listed.status_code, 200)
                            self.assertNotIn(b[2]['session_id'], listed.text)
                        path = broker.CREATE_PATH + '/' + b[1] + '/close'
                        self.assertEqual((await client.post(path, content=b'{}', headers=headers(a[0], path, b'{}'))).status_code, 404)
                        # Absolute lifetime is enforced by persisted broker state,
                        # independently of browser activity and process memory.
                        with closing(broker.database()) as db:
                            db.execute('UPDATE kernel_leases SET expires=? WHERE id=?', (int(time.time()) - 1, a[1]))
                        await broker.cleanup_due()
                        with closing(broker.database()) as db:
                            self.assertEqual(db.execute('SELECT state FROM kernel_leases WHERE id=?', (a[1],)).fetchone()[0], 'closed')
                    finally:
                        for key, lease, allocation in allocations:
                            path = broker.CREATE_PATH + '/' + lease + '/close'
                            await client.post(path, content=b'{}', headers=headers(key, path, b'{}'))
                        await broker.cleanup_due()
                        with closing(broker.database()) as db:
                            self.assertEqual(db.execute("SELECT count(*) FROM kernel_leases WHERE state!='closed'").fetchone()[0], 0, 'test browser cleanup incomplete')


if __name__ == '__main__':
    unittest.main(verbosity=2)
