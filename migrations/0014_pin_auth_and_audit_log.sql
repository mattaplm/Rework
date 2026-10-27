-- 4-digit PIN auth replaces free-text passwords (requested 2026-10-22):
-- viewer accounts need no PIN at all, so password_hash must allow NULL now
-- (previously NOT NULL). A NULL password_hash + role='viewer' is what
-- services/auth.py's login check treats as "no PIN required" -- any other
-- role must still have a real hash.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

-- Append-only audit trail: every logon, entry, and modification, by
-- username -- browsable at Admin -> Audit Log. `username` is a plain text
-- snapshot, not just user_id, so the log stays readable even if the
-- account is later renamed or deleted (users.username has no history of
-- its own); `user_id` is a best-effort link, set NULL on a delete rather
-- than losing the log entry.
CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    username    TEXT NOT NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_at ON audit_log (at DESC);
