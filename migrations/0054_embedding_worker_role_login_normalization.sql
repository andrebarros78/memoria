-- Canonical 1.0 hardening: normalize the dedicated embedding discovery role
-- after 0053. On a fresh cluster the role has no password until provisioning,
-- so LOGIN does not make it usable prematurely. On additional databases this
-- restores LOGIN after 0053 without altering any existing password.

ALTER ROLE memory_embedding_worker
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
