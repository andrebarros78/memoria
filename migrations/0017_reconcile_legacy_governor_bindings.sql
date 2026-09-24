SELECT set_config('app.current_tenant','__SYSTEM__',true);

UPDATE governor_project_bindings
SET status='DISABLED',updated_at=now()
WHERE status='ACTIVE';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM governor_project_bindings WHERE status='ACTIVE') THEN
    RAISE EXCEPTION 'legacy Governor bindings remain active after decommission reconciliation';
  END IF;
END $$;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.14.2')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
