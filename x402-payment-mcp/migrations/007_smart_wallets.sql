-- Additive: legacy EOA wallets, balances and payment history are untouched.
CREATE TABLE IF NOT EXISTS smart_wallets (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  owner_name text NOT NULL UNIQUE,
  owner_address text NOT NULL UNIQUE,
  account_name text NOT NULL UNIQUE,
  address text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS wallet_operations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  network text NOT NULL CHECK(network IN ('base','ethereum')),
  address text NOT NULL,
  calls jsonb NOT NULL,
  descriptions jsonb NOT NULL,
  fingerprint text NOT NULL,
  simulation jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'prepared' CHECK(status IN ('prepared','reserved','signing','submitted','confirmed','failed','unknown')),
  purpose text,
  user_op_hash text,
  transaction_hash text,
  error text,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wallet_operations_pending ON wallet_operations(user_id,network,status);

ALTER TABLE payment_previews ADD COLUMN IF NOT EXISTS payer_address text;
