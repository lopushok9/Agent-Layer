-- Off-chain EIP-191/EIP-712 signature previews. Single use like wallet_operations;
-- the signature itself is returned once and never stored.
CREATE TABLE IF NOT EXISTS wallet_signatures (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  network text NOT NULL CHECK(network IN ('base','ethereum')),
  address text NOT NULL,
  payload jsonb NOT NULL,
  digest text NOT NULL,
  description jsonb NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'prepared' CHECK(status IN ('prepared','signing','signed','failed')),
  purpose text,
  error text,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wallet_signatures_user ON wallet_signatures(user_id,created_at);
