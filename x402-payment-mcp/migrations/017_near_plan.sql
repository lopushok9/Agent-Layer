-- near_plan: one confirmed preview of several NEAR transactions executed in
-- order; each step runs as its own near_tx operation that references the plan.
ALTER TABLE near_operations DROP CONSTRAINT IF EXISTS near_operations_kind_check;
ALTER TABLE near_operations ADD CONSTRAINT near_operations_kind_check CHECK (kind IN ('near_tx','chain_signature','intents_swap','intents_trade','near_plan'));
