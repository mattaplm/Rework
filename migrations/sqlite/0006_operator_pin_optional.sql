-- Operator accounts no longer need a PIN (2026-11-05) -- see
-- migrations/0019_operator_pin_optional.sql.
UPDATE users SET password_hash = NULL, must_change_password = 0 WHERE role = 'operator';
