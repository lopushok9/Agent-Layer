-- A new receive address never resets or reinterprets the former wallet's ledger.
CREATE TABLE IF NOT EXISTS smart_wallet_history (
  address text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  owner_name text NOT NULL,
  owner_address text NOT NULL,
  account_name text NOT NULL,
  original_created_at timestamptz NOT NULL,
  replacement_address text NOT NULL,
  replacement_request_id uuid NOT NULL UNIQUE,
  reason text NOT NULL,
  replaced_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS smart_wallet_history_user ON smart_wallet_history(user_id);
