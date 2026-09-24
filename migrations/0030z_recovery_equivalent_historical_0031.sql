-- DISASTER RECOVERY 0.26.1: semantic equivalent of lost historical 0031.
-- Historical attestation only: 0031_restore_hardening_causal_function.sql
-- SHA-256 f3f513fd1ddb6f0e0c911e4a32f05f62a41361fcf1f31ef388df411445bbf371
-- This file intentionally has a different name and checksum.

ALTER FUNCTION memory_apply_ontology_transition(text,text,text,text,text,jsonb)
  SECURITY DEFINER;
ALTER FUNCTION memory_apply_ontology_transition(text,text,text,text,text,jsonb)
  SET search_path=public,pg_temp;
REVOKE ALL ON FUNCTION memory_apply_ontology_transition(text,text,text,text,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_apply_ontology_transition(text,text,text,text,text,jsonb) TO memory_app;

INSERT INTO schema_meta(key,value) VALUES
('restore_hardening_version','RH-1.0.0'),
('restore_hardening_historical_0031_sha256','f3f513fd1ddb6f0e0c911e4a32f05f62a41361fcf1f31ef388df411445bbf371'),
('restore_hardening_recovery_lineage','0.26.1-recovery'),
('schema_version','memory-0.23.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
