-- P10 hardening: canonical mutation boundary + replay completeness.

CREATE OR REPLACE FUNCTION memory_require_decision_mutation_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF COALESCE(current_setting('app.decision_mutation_authorized',true),'') <> '1' THEN
    RAISE EXCEPTION 'direct sovereign decision mutation forbidden; use canonical Decision API' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_require_decision_context ON sovereign_decisions;
CREATE TRIGGER trg_require_decision_context BEFORE INSERT ON sovereign_decisions
FOR EACH ROW EXECUTE FUNCTION memory_require_decision_mutation_context();
DROP TRIGGER IF EXISTS trg_require_decision_context ON sovereign_decision_evidence;
CREATE TRIGGER trg_require_decision_context BEFORE INSERT ON sovereign_decision_evidence
FOR EACH ROW EXECUTE FUNCTION memory_require_decision_mutation_context();
DROP TRIGGER IF EXISTS trg_require_decision_context ON sovereign_decision_outcomes;
CREATE TRIGGER trg_require_decision_context BEFORE INSERT ON sovereign_decision_outcomes
FOR EACH ROW EXECUTE FUNCTION memory_require_decision_mutation_context();
DROP TRIGGER IF EXISTS trg_require_decision_context ON sovereign_decision_replays;
CREATE TRIGGER trg_require_decision_context BEFORE INSERT ON sovereign_decision_replays
FOR EACH ROW EXECUTE FUNCTION memory_require_decision_mutation_context();

INSERT INTO schema_meta(key,value) VALUES('decision_record_version','DR-1.1.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.18.1')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
