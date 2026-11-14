-- An x402 authorization is a NEAR MPC request, not an EVM transaction.
ALTER TABLE near_operations DROP CONSTRAINT IF EXISTS near_operations_kind_check;
ALTER TABLE near_operations ADD CONSTRAINT near_operations_kind_check CHECK (kind IN ('near_tx','chain_signature','intents_swap','intents_trade','near_plan','x402_authorization'));

CREATE TABLE IF NOT EXISTS near_x402_payments (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  amount text NOT NULL CHECK (amount ~ '^[0-9]+$'),
  -- Request credentials, authorization preimage and signature stay encrypted.
  payload text NOT NULL,
  status text NOT NULL DEFAULT 'prepared' CHECK (status IN ('prepared','reserved','signing','signed','sending','settled','failed','unknown','expired','cancelled')),
  purpose text,
  result jsonb,
  expires_at timestamptz NOT NULL,
  reserved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS near_x402_payments_user ON near_x402_payments(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS near_x402_payments_pending ON near_x402_payments(user_id,status) WHERE status IN ('reserved','signing','signed','sending','unknown');
