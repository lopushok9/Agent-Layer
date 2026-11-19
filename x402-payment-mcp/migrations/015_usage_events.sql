-- Product usage: one row per MCP tool call and per sign-in/consent step.
-- Tool arguments and results are never stored; detail holds a scrubbed error
-- class for failed calls, or "new_user" for a sign-in that created the user.
CREATE TABLE IF NOT EXISTS usage_events (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL CHECK(kind IN ('tool','auth')),
  name text NOT NULL,
  user_id uuid,
  client_id text,
  ok boolean NOT NULL,
  ms integer,
  detail text
);
CREATE INDEX IF NOT EXISTS usage_events_at ON usage_events(at);
CREATE INDEX IF NOT EXISTS usage_events_kind_name_at ON usage_events(kind,name,at);
