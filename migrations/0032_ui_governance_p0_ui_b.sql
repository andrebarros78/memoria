-- MEMORIA PLUS P16: formal UI governance boundary.
-- P0-UI-A remains non-destructive. P0-UI-B is locked until Gate M12 is proven.

INSERT INTO schema_meta(key,value) VALUES
  ('ui_governance_version','UI-GOV-1.0.0'),
  ('ui_governance_active_mode','P0-UI-A'),
  ('p0_ui_a_enabled','true'),
  ('p0_ui_b_enabled','false'),
  ('p0_ui_b_activation_gate','M12'),
  ('direct_purge_enabled','false'),
  ('delete_eligible_is_physical_delete','false'),
  ('schema_version','memory-0.24.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value;
