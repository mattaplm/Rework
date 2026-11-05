-- Operator accounts no longer need a PIN (2026-11-05, "this doesn't actually
-- need one") -- clear existing operator PINs so they log in on username
-- alone, same as viewer. Admin accounts are untouched.
UPDATE users SET password_hash = NULL, must_change_password = FALSE WHERE role = 'operator';
