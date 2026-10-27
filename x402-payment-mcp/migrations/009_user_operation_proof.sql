-- Public metadata is separate from encrypted unsigned UserOperation calldata.
-- Legacy opaque CDP operations keep NULL proof and remain unresolved.
ALTER TABLE wallet_operations ADD COLUMN IF NOT EXISTS operation_proof jsonb;
ALTER TABLE wallet_operations ADD COLUMN IF NOT EXISTS operation_ciphertext text;
