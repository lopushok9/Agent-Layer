-- WalletConnect client state (pairing/session symmetric keys among it),
-- AES-256-GCM encrypted per key. One server process owns the relay connection.
CREATE TABLE IF NOT EXISTS walletconnect_storage (
  key text PRIMARY KEY,
  value text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS dapp_proposals (
  id text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  pairing_topic text NOT NULL,
  params jsonb NOT NULL,
  verification jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS dapp_sessions (
  topic text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  address text NOT NULL,
  app jsonb NOT NULL,
  verification jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dapp_sessions_user ON dapp_sessions(user_id);
CREATE TABLE IF NOT EXISTS dapp_requests (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  session_topic text NOT NULL REFERENCES dapp_sessions(topic),
  rpc_id text NOT NULL,
  method text NOT NULL,
  network text NOT NULL CHECK(network IN ('base','ethereum')),
  params jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','prepared','submitted','responded','rejected','expired')),
  operation_id uuid,
  signature_id uuid,
  expires_at timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(session_topic, rpc_id)
);
CREATE INDEX IF NOT EXISTS dapp_requests_user ON dapp_requests(user_id,status);
CREATE UNIQUE INDEX IF NOT EXISTS dapp_requests_operation ON dapp_requests(operation_id) WHERE operation_id IS NOT NULL;
