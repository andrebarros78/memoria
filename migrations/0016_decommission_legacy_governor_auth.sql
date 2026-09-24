UPDATE governor_project_bindings
SET status='DISABLED',updated_at=now()
WHERE status='ACTIVE';

CREATE OR REPLACE FUNCTION reject_legacy_governor_binding_activation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status='ACTIVE' THEN
    RAISE EXCEPTION 'legacy Governor authentication is decommissioned; use universal HMAC client authentication'
      USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reject_legacy_governor_binding_activation ON governor_project_bindings;
CREATE TRIGGER trg_reject_legacy_governor_binding_activation
BEFORE INSERT OR UPDATE OF status ON governor_project_bindings
FOR EACH ROW EXECUTE FUNCTION reject_legacy_governor_binding_activation();

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.14.1')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
