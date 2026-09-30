CREATE TABLE IF NOT EXISTS personal_access_tokens (id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id), token_hash text NOT NULL UNIQUE, label text NOT NULL, hint text NOT NULL, scope text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, last_used_at timestamptz, revoked_at timestamptz);
CREATE INDEX IF NOT EXISTS personal_access_tokens_user ON personal_access_tokens(user_id,created_at DESC);
CREATE TABLE IF NOT EXISTS token_login_states (id uuid PRIMARY KEY, expires_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS token_manager_sessions (token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id), expires_at timestamptz NOT NULL);
