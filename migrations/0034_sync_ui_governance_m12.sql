-- P17 final hardening: keep UI governance metadata synchronized with Gate M12.
-- Migration 0033 remains immutable; this migration resolves the discovered metadata-state divergence.

CREATE OR REPLACE FUNCTION memory_sync_ui_governance_from_m12() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_enabled text;
DECLARE v_mode text;
BEGIN
  IF NEW.gate_id <> 'M12' THEN
    RETURN NEW;
  END IF;
  v_enabled := CASE WHEN NEW.status='PROVEN' THEN 'true' ELSE 'false' END;
  v_mode := CASE WHEN NEW.status='PROVEN' THEN 'P0-UI-B' ELSE 'P0-UI-A' END;
  INSERT INTO schema_meta(key,value) VALUES
    ('ui_governance_version','UI-GOV-1.1.0'),
    ('ui_governance_active_mode',v_mode),
    ('p0_ui_b_enabled',v_enabled),
    ('p0_ui_b_activation_gate','M12'),
    ('direct_purge_enabled','false'),
    ('delete_eligible_is_physical_delete','false'),
    ('governed_lifecycle_required','true')
  ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_lifecycle_gate_m12_sync_ui ON lifecycle_gate_m12;
CREATE TRIGGER trg_lifecycle_gate_m12_sync_ui
AFTER INSERT OR UPDATE OF status ON lifecycle_gate_m12
FOR EACH ROW EXECUTE FUNCTION memory_sync_ui_governance_from_m12();

INSERT INTO schema_meta(key,value) VALUES
('ui_governance_version','UI-GOV-1.1.0'),
('ui_governance_active_mode',CASE WHEN EXISTS(SELECT 1 FROM lifecycle_gate_m12 WHERE gate_id='M12' AND status='PROVEN') THEN 'P0-UI-B' ELSE 'P0-UI-A' END),
('p0_ui_b_enabled',CASE WHEN EXISTS(SELECT 1 FROM lifecycle_gate_m12 WHERE gate_id='M12' AND status='PROVEN') THEN 'true' ELSE 'false' END),
('p0_ui_b_activation_gate','M12'),
('direct_purge_enabled','false'),
('delete_eligible_is_physical_delete','false'),
('governed_lifecycle_required','true'),
('schema_version','memory-0.25.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
