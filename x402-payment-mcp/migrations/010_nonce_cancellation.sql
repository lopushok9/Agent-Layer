ALTER TABLE wallet_operations DROP CONSTRAINT IF EXISTS wallet_operations_status_check;
ALTER TABLE wallet_operations ADD CONSTRAINT wallet_operations_status_check CHECK(status IN ('prepared','reserved','signing','submitted','confirmed','failed','unknown','cancelled'));
ALTER TABLE wallet_operations DROP CONSTRAINT IF EXISTS wallet_operations_kind_check;
ALTER TABLE wallet_operations ADD CONSTRAINT wallet_operations_kind_check CHECK(kind IN ('calls','swap','cancel'));
ALTER TABLE wallet_operations ADD COLUMN IF NOT EXISTS cancel_plan jsonb;
