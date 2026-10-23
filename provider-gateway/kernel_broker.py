"""Provision isolated browsers, never relay browser code or card payloads.

Each request proves possession of an installation-specific Ed25519 key. That
identity is separate from the legacy gateway bearer token. Keys for existing
browsers are scoped by Kernel; the organization's credential stays server-side.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from starlette.responses import JSONResponse
from starlette.routing import Route

PROTOCOL = "agentlayer-kernel-v1"
CREATE_PATH = "/v1/kernel/browser-sessions"
HEX32 = re.compile(r"[a-f0-9]{32}\Z")
ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")


class BrokerError(Exception):
    def __init__(self, message, status=503):
        self.message, self.status = message, status


def configured():
    return (bool(os.getenv("KERNEL_API_KEY"))
            and bool(ID.fullmatch(os.getenv("KERNEL_PROJECT_ID", "")))
            and bool(os.getenv("KERNEL_BROKER_DB_PATH")))


def enabled():
    return os.getenv("KERNEL_SHARED_ENABLED", "false").lower() == "true" and configured()


def limit(name, default, maximum):
    return min(maximum, max(1, int(os.getenv(name, str(default)))))


def ttl():
    return max(300, limit("KERNEL_SESSION_TTL_SECONDS", 900, 1800))


def database():
    path = Path(os.environ["KERNEL_BROKER_DB_PATH"])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BrokerError("Unsafe browser broker database configuration.")
    finally:
        os.close(fd)
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS kernel_nonces (
        owner TEXT NOT NULL, nonce TEXT NOT NULL, seen INTEGER NOT NULL,
        PRIMARY KEY(owner, nonce));
      CREATE TABLE IF NOT EXISTS kernel_leases (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, ip TEXT NOT NULL,
        project TEXT NOT NULL, browser TEXT, key_id TEXT,
        state TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL,
        cleanup_at INTEGER NOT NULL DEFAULT 0);
      CREATE INDEX IF NOT EXISTS kernel_lease_owner ON kernel_leases(owner, created);
      CREATE INDEX IF NOT EXISTS kernel_lease_ip ON kernel_leases(ip, created);
      CREATE INDEX IF NOT EXISTS kernel_lease_created ON kernel_leases(created);
      CREATE INDEX IF NOT EXISTS kernel_lease_cleanup ON kernel_leases(state, expires);
    """)
    return db


async def proof(request, *, allow_disabled=False):
    if not (configured() if allow_disabled else enabled()):
        raise BrokerError("Shared browsers are not available.")
    if request.url.query:
        raise BrokerError("Query parameters are not supported.", 400)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024:
            raise BrokerError("Browser request is too large.", 413)
    try:
        key = request.headers["x-agentlayer-client-key"]
        timestamp = request.headers["x-agentlayer-timestamp"]
        nonce = request.headers["x-agentlayer-nonce"]
        signature = request.headers["x-agentlayer-signature"]
        if (not re.fullmatch(r"[a-f0-9]{64}", key) or not HEX32.fullmatch(nonce)
                or not re.fullmatch(r"[0-9]{10}", timestamp)
                or not re.fullmatch(r"[a-f0-9]{128}", signature)
                or not -30 <= time.time() - int(timestamp) <= 90):
            raise ValueError()
        message = "\n".join((PROTOCOL, request.method, request.url.path,
                             timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
        VerifyKey(bytes.fromhex(key)).verify(message, bytes.fromhex(signature))
        owner = hashlib.sha256(bytes.fromhex(key)).hexdigest()
    except (KeyError, ValueError, BadSignatureError):
        raise BrokerError("Invalid or expired browser access proof.", 401) from None
    with closing(database()) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM kernel_nonces WHERE seen < ?", (int(time.time()) - 180,))
            db.execute("INSERT INTO kernel_nonces VALUES (?, ?, ?)", (owner, nonce, int(time.time())))
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            raise BrokerError("Browser access proof was already used.", 409) from None
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise BrokerError("Expected a browser request object.", 400) from None
    return owner, data


async def upstream(method, path, project, body=None, *, missing_ok=False):
    # A new pool with zero transport retries; no caller-supplied URL or headers.
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
        async with client.stream(method, "https://api.onkernel.com" + path,
                headers={"Authorization": "Bearer " + os.environ["KERNEL_API_KEY"],
                         "X-Kernel-Project-Id": project},
                **({"json": body} if body is not None else {})) as response:
            if missing_ok and response.status_code == 404:
                return {}
            if not 200 <= response.status_code < 300:
                raise BrokerError("Kernel browser provisioning is temporarily unavailable.")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 256 * 1024:
                    raise BrokerError("Invalid Kernel provisioning response.")
            value = json.loads(raw) if raw else {}
            if not isinstance(value, dict):
                raise BrokerError("Invalid Kernel provisioning response.")
            return value


def reserve(request, owner, lease):
    now = int(time.time())
    ip = request.client.host if request.client else "unknown"
    ip_hash = hmac.new(os.environ["KERNEL_API_KEY"].encode(), ip.encode(), hashlib.sha256).hexdigest()
    with closing(database()) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM kernel_leases WHERE id=?", (lease,)).fetchone():
            raise BrokerError("Browser allocation already exists; it will not be repeated.", 409)
        checks = (
            ("state != 'closed'", (), limit("KERNEL_MAX_ACTIVE", 10, 1000)),
            ("owner=? AND state != 'closed'", (owner,), limit("KERNEL_MAX_ACTIVE_PER_CLIENT", 2, 50)),
            ("created>?", (now - 86400,), limit("KERNEL_MAX_DAILY", 100, 100000)),
            ("owner=? AND created>?", (owner, now - 86400), limit("KERNEL_MAX_DAILY_PER_CLIENT", 10, 10000)),
            ("ip=? AND created>?", (ip_hash, now - 86400), limit("KERNEL_MAX_DAILY_PER_IP", 20, 10000)),
        )
        for where, params, maximum in checks:
            if db.execute("SELECT count(*) FROM kernel_leases WHERE " + where, params).fetchone()[0] >= maximum:
                raise BrokerError("Shared browser quota reached. Try again later.", 429)
        db.execute("INSERT INTO kernel_leases (id,owner,ip,project,state,created,expires) VALUES (?,?,?,?,?,?,?)",
                   (lease, owner, ip_hash, os.environ["KERNEL_PROJECT_ID"], "creating", now, now + ttl()))
        db.commit()


async def cleanup_one(lease):
    with closing(database()) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM kernel_leases WHERE id=? AND state!='closed' AND cleanup_at<?",
                         (lease, int(time.time()) - 10)).fetchone()
        if not row:
            return
        db.execute("UPDATE kernel_leases SET cleanup_at=? WHERE id=?", (int(time.time()), lease))
        db.commit()
    # The deterministic name also recovers a lost browser-create response.
    await upstream("DELETE", "/browsers/" + quote(row["browser"] or "al-" + lease, safe=""), row["project"], missing_ok=True)
    if row["key_id"]:
        await upstream("DELETE", "/org/api_keys/" + quote(row["key_id"], safe=""), row["project"], missing_ok=True)
    # Allow an in-flight create to settle before treating a missing named browser
    # as final. Cleanup retries even when the original client has disconnected.
    if row["browser"] or int(time.time()) - row["created"] > 120:
        with closing(database()) as db:
            db.execute("UPDATE kernel_leases SET state='closed' WHERE id=?", (lease,))


async def cleanup_due():
    if not configured():
        return
    with closing(database()) as db:
        now = int(time.time())
        leases = db.execute("SELECT id FROM kernel_leases WHERE state!='closed' AND cleanup_at<? "
                            "AND (expires<=? OR state='closing') ORDER BY cleanup_at, expires LIMIT 20",
                            (now - 10, now)).fetchall()
    for lease in leases:
        try:
            await cleanup_one(lease["id"])
        except Exception:
            pass  # Persisted lease is retried; never log provider bodies or keys.


async def cleanup_loop():
    while True:
        try:
            await cleanup_due()
        except Exception:
            pass
        await asyncio.sleep(15)


async def capabilities(_):
    return JSONResponse({"protocol": PROTOCOL, "available": enabled(), "session_ttl_seconds": ttl()},
                        headers={"Cache-Control": "no-store"})


async def create(request):
    lease = None
    try:
        owner, data = await proof(request)
        if set(data) != {"lease_id"} or not isinstance(data["lease_id"], str) or not HEX32.fullmatch(data["lease_id"]):
            raise BrokerError("Expected one browser lease_id.", 400)
        await cleanup_due()
        reserve(request, owner, data["lease_id"])
        lease = data["lease_id"]
        project = os.environ["KERNEL_PROJECT_ID"]
        browser = await upstream("POST", "/browsers", project, {
            "name": "al-" + lease, "headless": True, "timeout_seconds": 300,
            "telemetry": {"enabled": False}})
        browser_id = browser.get("session_id")
        if not isinstance(browser_id, str) or not ID.fullmatch(browser_id):
            raise BrokerError("Invalid Kernel browser allocation.")
        with closing(database()) as db:
            db.execute("UPDATE kernel_leases SET browser=? WHERE id=?", (browser_id, lease))
            row = db.execute("SELECT * FROM kernel_leases WHERE id=?", (lease,)).fetchone()
        resource = "projects/" + project + "/browsers/" + browser_id
        policy = {"statements": [{"action": "browsers:use", "resource": resource}]}
        expires = datetime.fromtimestamp(row["expires"], timezone.utc).isoformat()
        key = await upstream("POST", "/org/api_keys", project, {
            "name": "al-" + lease, "project_id": project, "expires_at": expires, "policy": policy})
        key_id, secret = key.get("id"), key.get("key")
        if isinstance(key_id, str) and ID.fullmatch(key_id):
            with closing(database()) as db:
                db.execute("UPDATE kernel_leases SET key_id=? WHERE id=?", (key_id, lease))
        # Fail closed if an older upstream ignores policy fields. An unrestricted
        # project credential must never escape in the client response.
        try:
            parsed_expiry = datetime.fromisoformat(key["expires_at"].replace("Z", "+00:00"))
            key_expiry = parsed_expiry.timestamp() if parsed_expiry.tzinfo is not None else 0
        except (KeyError, ValueError, AttributeError, TypeError):
            key_expiry = 0
        if (not isinstance(key_id, str) or not ID.fullmatch(key_id)
                or key.get("policy") != policy or key.get("project_id") != project
                or not time.time() + 5 < key_expiry <= row["expires"] + 2
                or not isinstance(secret, str) or not 16 <= len(secret) <= 8192
                or any(ord(c) < 33 or ord(c) > 126 for c in secret)):
            raise BrokerError("Kernel did not confirm a browser-scoped credential.")
        with closing(database()) as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state,expires FROM kernel_leases WHERE id=?", (lease,)).fetchone()
            if current["state"] != "creating" or current["expires"] <= time.time():
                raise BrokerError("Browser allocation was cancelled or expired.", 409)
            db.execute("UPDATE kernel_leases SET state='active' WHERE id=?", (lease,))
            db.commit()
        return JSONResponse({"protocol": PROTOCOL, "lease_id": lease, "session_id": browser_id,
                             "session_key": secret, "expires_at": row["expires"]},
                            headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
    except BaseException as exc:
        if lease:
            with closing(database()) as db:
                db.execute("UPDATE kernel_leases SET state='closing' WHERE id=?", (lease,))
            # Cleanup worker handles cancellation too; it survives this request.
        if isinstance(exc, asyncio.CancelledError):
            raise
        if isinstance(exc, BrokerError):
            return JSONResponse({"error": exc.message}, exc.status, headers={"Cache-Control": "no-store"})
        return JSONResponse({"error": "Shared browser provisioning failed."}, 503)


async def close(request):
    try:
        owner, data = await proof(request, allow_disabled=True)
        lease = request.path_params["lease_id"]
        if data or not HEX32.fullmatch(lease):
            raise BrokerError("Expected an empty browser close request.", 400)
        with closing(database()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM kernel_leases WHERE id=? AND owner=?", (lease, owner)).fetchone()
            if not row:
                raise BrokerError("Browser lease not found.", 404)
            if row["state"] != "closed":
                db.execute("UPDATE kernel_leases SET state='closing' WHERE id=?", (lease,))
            db.commit()
        if row["state"] != "closed":
            await cleanup_one(lease)
        with closing(database()) as db:
            done = db.execute("SELECT state FROM kernel_leases WHERE id=?", (lease,)).fetchone()[0] == "closed"
        return JSONResponse({"closed": done, "cleanup_pending": not done}, 200 if done else 202)
    except BrokerError as exc:
        return JSONResponse({"error": exc.message}, exc.status)
    except Exception:
        return JSONResponse({"error": "Browser cleanup pending."}, 503)


routes = [Route("/v1/kernel/capabilities", capabilities, methods=["GET"]),
          Route(CREATE_PATH, create, methods=["POST"]),
          Route(CREATE_PATH + "/{lease_id:str}/close", close, methods=["POST"])]
