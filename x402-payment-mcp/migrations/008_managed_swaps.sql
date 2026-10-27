ALTER TABLE wallet_operations ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'calls' CHECK(kind IN ('calls','swap'));
ALTER TABLE wallet_operations ADD COLUMN IF NOT EXISTS swap_plan jsonb;
-- Quote snapshot before Permit2 or UserOperation signing, never signature/key material.
ALTER TABLE wallet_operations ADD COLUMN IF NOT EXISTS execution_context jsonb;
