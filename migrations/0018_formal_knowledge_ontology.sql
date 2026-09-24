-- MEMORIA PLUS P07 - Formal Knowledge Ontology KO-1.0.0

CREATE TABLE IF NOT EXISTS ontology_legacy_category_migrations(
  migration_id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  from_category text NOT NULL,
  to_category text NOT NULL,
  migration_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(item_id,migration_version)
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM memory_items
    WHERE category NOT IN (
      'FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE',
      'EVENT','REQUIREMENT','RULE','DOCUMENT','STATE'
    )
  ) THEN
    RAISE EXCEPTION 'P07 ontology migration found unknown legacy categories';
  END IF;
END $$;

INSERT INTO ontology_legacy_category_migrations(tenant_id,item_id,from_category,to_category,migration_version)
SELECT tenant_id,item_id,category,
  CASE category
    WHEN 'EVENT' THEN 'OBSERVATION'
    WHEN 'REQUIREMENT' THEN 'CONSTRAINT'
    WHEN 'RULE' THEN 'CONSTRAINT'
    WHEN 'DOCUMENT' THEN 'EVIDENCE'
    WHEN 'STATE' THEN 'OBSERVATION'
  END,
  '0018_formal_knowledge_ontology'
FROM memory_items
WHERE category IN ('EVENT','REQUIREMENT','RULE','DOCUMENT','STATE')
ON CONFLICT(item_id,migration_version) DO NOTHING;

UPDATE memory_items SET category=CASE category
  WHEN 'EVENT' THEN 'OBSERVATION'
  WHEN 'REQUIREMENT' THEN 'CONSTRAINT'
  WHEN 'RULE' THEN 'CONSTRAINT'
  WHEN 'DOCUMENT' THEN 'EVIDENCE'
  WHEN 'STATE' THEN 'OBSERVATION'
  ELSE category END
WHERE category IN ('EVENT','REQUIREMENT','RULE','DOCUMENT','STATE');

ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_items_category_ontology_check;
ALTER TABLE memory_items ADD CONSTRAINT memory_items_category_ontology_check CHECK(category IN (
  'FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE'
));

CREATE TABLE IF NOT EXISTS ontology_relation_rules(
  source_category text NOT NULL,
  relation_type text NOT NULL,
  target_category text NOT NULL,
  ontology_version text NOT NULL DEFAULT 'KO-1.0.0',
  PRIMARY KEY(source_category,relation_type,target_category),
  CHECK(source_category IN ('FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE')),
  CHECK(target_category IN ('FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE')),
  CHECK(relation_type IN ('SUPPORTS','REFUTES','DERIVED_FROM','CORRELATES_WITH','CAUSES','TESTS','PRODUCES','IMPLEMENTS','CONSTRAINS','ADVANCES','BASED_ON'))
);

WITH raw(rule) AS (
  SELECT unnest(string_to_array('CAUSE|CAUSES|OBSERVATION;CAUSE|CAUSES|OUTCOME;CAUSE|DERIVED_FROM|EVIDENCE;CAUSE|DERIVED_FROM|EXPERIMENT;CAUSE|DERIVED_FROM|OBSERVATION;CAUSE|DERIVED_FROM|OUTCOME;CONSTRAINT|CONSTRAINS|DECISION;CONSTRAINT|CONSTRAINS|EXPERIMENT;CONSTRAINT|CONSTRAINS|INTERVENTION;CONSTRAINT|CONSTRAINS|OBJECTIVE;CONSTRAINT|CONSTRAINS|PROCEDURE;CORRELATION|CORRELATES_WITH|EVIDENCE;CORRELATION|CORRELATES_WITH|FACT;CORRELATION|CORRELATES_WITH|OBSERVATION;CORRELATION|DERIVED_FROM|EVIDENCE;CORRELATION|DERIVED_FROM|FACT;CORRELATION|DERIVED_FROM|OBSERVATION;DECISION|ADVANCES|OBJECTIVE;DECISION|BASED_ON|CONSTRAINT;DECISION|BASED_ON|EVIDENCE;DECISION|BASED_ON|FACT;DECISION|BASED_ON|LEARNING;DECISION|BASED_ON|OBJECTIVE;DECISION|DERIVED_FROM|CONSTRAINT;DECISION|DERIVED_FROM|EVIDENCE;DECISION|DERIVED_FROM|FACT;DECISION|DERIVED_FROM|LEARNING;DECISION|DERIVED_FROM|OBJECTIVE;EVIDENCE|REFUTES|CAUSE;EVIDENCE|REFUTES|CORRELATION;EVIDENCE|REFUTES|HYPOTHESIS;EVIDENCE|REFUTES|INFERENCE;EVIDENCE|SUPPORTS|CAUSE;EVIDENCE|SUPPORTS|CORRELATION;EVIDENCE|SUPPORTS|DECISION;EVIDENCE|SUPPORTS|FACT;EVIDENCE|SUPPORTS|HYPOTHESIS;EVIDENCE|SUPPORTS|INFERENCE;EVIDENCE|SUPPORTS|LEARNING;EXPERIMENT|ADVANCES|OBJECTIVE;EXPERIMENT|BASED_ON|CAUSE;EXPERIMENT|BASED_ON|CONSTRAINT;EXPERIMENT|BASED_ON|CORRELATION;EXPERIMENT|BASED_ON|HYPOTHESIS;EXPERIMENT|BASED_ON|OBJECTIVE;EXPERIMENT|PRODUCES|EVIDENCE;EXPERIMENT|PRODUCES|OUTCOME;EXPERIMENT|TESTS|CAUSE;EXPERIMENT|TESTS|CORRELATION;EXPERIMENT|TESTS|HYPOTHESIS;EXPERIMENT|TESTS|PROCEDURE;FACT|REFUTES|HYPOTHESIS;FACT|REFUTES|INFERENCE;FACT|SUPPORTS|DECISION;FACT|SUPPORTS|HYPOTHESIS;FACT|SUPPORTS|INFERENCE;FACT|SUPPORTS|PROCEDURE;INFERENCE|DERIVED_FROM|EVIDENCE;INFERENCE|DERIVED_FROM|FACT;INFERENCE|DERIVED_FROM|OBSERVATION;INTERVENTION|ADVANCES|OBJECTIVE;INTERVENTION|BASED_ON|CONSTRAINT;INTERVENTION|BASED_ON|DECISION;INTERVENTION|BASED_ON|OBJECTIVE;INTERVENTION|BASED_ON|PROCEDURE;INTERVENTION|IMPLEMENTS|DECISION;INTERVENTION|IMPLEMENTS|PROCEDURE;INTERVENTION|PRODUCES|OBSERVATION;INTERVENTION|PRODUCES|OUTCOME;LEARNING|ADVANCES|OBJECTIVE;LEARNING|DERIVED_FROM|EVIDENCE;LEARNING|DERIVED_FROM|EXPERIMENT;LEARNING|DERIVED_FROM|FACT;LEARNING|DERIVED_FROM|OUTCOME;LEARNING|SUPPORTS|DECISION;LEARNING|SUPPORTS|EXPERIMENT;LEARNING|SUPPORTS|PROCEDURE;OBSERVATION|REFUTES|CORRELATION;OBSERVATION|REFUTES|HYPOTHESIS;OBSERVATION|REFUTES|INFERENCE;OBSERVATION|SUPPORTS|CORRELATION;OBSERVATION|SUPPORTS|HYPOTHESIS;OBSERVATION|SUPPORTS|INFERENCE;OUTCOME|REFUTES|CAUSE;OUTCOME|REFUTES|HYPOTHESIS;OUTCOME|REFUTES|PROCEDURE;OUTCOME|SUPPORTS|LEARNING;OUTCOME|SUPPORTS|PROCEDURE;PROCEDURE|ADVANCES|OBJECTIVE;PROCEDURE|BASED_ON|CONSTRAINT;PROCEDURE|BASED_ON|EVIDENCE;PROCEDURE|BASED_ON|FACT;PROCEDURE|BASED_ON|LEARNING;PROCEDURE|DERIVED_FROM|EVIDENCE;PROCEDURE|DERIVED_FROM|LEARNING;PROCEDURE|PRODUCES|OUTCOME',';'))
)
INSERT INTO ontology_relation_rules(source_category,relation_type,target_category)
SELECT split_part(rule,'|',1),split_part(rule,'|',2),split_part(rule,'|',3) FROM raw
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS ontology_transition_rules(
  from_category text NOT NULL,
  to_category text NOT NULL,
  ontology_version text NOT NULL DEFAULT 'KO-1.0.0',
  PRIMARY KEY(from_category,to_category),
  CHECK(from_category IN ('FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE')),
  CHECK(to_category IN ('FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE'))
);
INSERT INTO ontology_transition_rules(from_category,to_category) VALUES
('OBSERVATION','EVIDENCE'),('EVIDENCE','FACT'),('HYPOTHESIS','INFERENCE'),('HYPOTHESIS','FACT'),('INFERENCE','FACT'),('CORRELATION','CAUSE'),('OUTCOME','LEARNING')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS memory_knowledge_relations(
  relation_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  from_item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  from_version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  relation_type text NOT NULL CHECK(relation_type IN ('SUPPORTS','REFUTES','DERIVED_FROM','CORRELATES_WITH','CAUSES','TESTS','PRODUCES','IMPLEMENTS','CONSTRAINS','ADVANCES','BASED_ON')),
  to_item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  to_version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  confidence double precision NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','STALE')),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  staled_at timestamptz,
  stale_reason text,
  CHECK(from_item_id <> to_item_id)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_relations_from ON memory_knowledge_relations(tenant_id,from_item_id,status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_relations_to ON memory_knowledge_relations(tenant_id,to_item_id,status,created_at DESC);

CREATE TABLE IF NOT EXISTS memory_knowledge_relation_events(
  seq bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  relation_id text NOT NULL REFERENCES memory_knowledge_relations(relation_id) ON DELETE RESTRICT,
  old_status text,
  new_status text NOT NULL CHECK(new_status IN ('ACTIVE','STALE')),
  reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_ontology_transitions(
  transition_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  from_category text NOT NULL,
  to_category text NOT NULL,
  actor_id text NOT NULL,
  reason text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(from_category IN ('FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE')),
  CHECK(to_category IN ('FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE'))
);
CREATE INDEX IF NOT EXISTS idx_ontology_transitions_item ON memory_ontology_transitions(tenant_id,item_id,created_at DESC);

CREATE OR REPLACE FUNCTION memory_validate_knowledge_relation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE from_tenant text; DECLARE to_tenant text; DECLARE from_category text; DECLARE to_category text;
DECLARE current_from_version text; DECLARE current_to_version text;
BEGIN
  SELECT tenant_id,category INTO from_tenant,from_category FROM memory_items WHERE item_id=NEW.from_item_id;
  SELECT tenant_id,category INTO to_tenant,to_category FROM memory_items WHERE item_id=NEW.to_item_id;
  IF from_tenant IS NULL OR to_tenant IS NULL THEN RAISE EXCEPTION 'knowledge relation endpoint memory not found'; END IF;
  IF from_tenant <> to_tenant THEN RAISE EXCEPTION 'cross-tenant knowledge relation forbidden' USING ERRCODE='42501'; END IF;
  SELECT version_id INTO current_from_version FROM memory_versions WHERE item_id=NEW.from_item_id ORDER BY version_no DESC LIMIT 1;
  SELECT version_id INTO current_to_version FROM memory_versions WHERE item_id=NEW.to_item_id ORDER BY version_no DESC LIMIT 1;
  IF NEW.from_version_id <> current_from_version OR NEW.to_version_id <> current_to_version THEN RAISE EXCEPTION 'knowledge relation must bind current versions'; END IF;
  IF NOT EXISTS(SELECT 1 FROM ontology_relation_rules r WHERE r.source_category=from_category AND r.relation_type=NEW.relation_type AND r.target_category=to_category) THEN
    RAISE EXCEPTION 'invalid ontology relation: % % %',from_category,NEW.relation_type,to_category USING ERRCODE='23514';
  END IF;
  NEW.tenant_id := from_tenant;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_record_knowledge_relation_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO memory_knowledge_relation_events(tenant_id,relation_id,old_status,new_status,reason)
  VALUES(NEW.tenant_id,NEW.relation_id,NULL,NEW.status,'CREATED');
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_record_knowledge_relation_status() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IS DISTINCT FROM NEW.status THEN
    INSERT INTO memory_knowledge_relation_events(tenant_id,relation_id,old_status,new_status,reason)
    VALUES(NEW.tenant_id,NEW.relation_id,OLD.status,NEW.status,NEW.stale_reason);
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_stale_knowledge_relations_on_new_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.previous_version_id IS NULL THEN RETURN NEW; END IF;
  PERFORM set_config('app.ontology_relation_state_authorized','1',true);
  UPDATE memory_knowledge_relations
  SET status='STALE',staled_at=COALESCE(staled_at,now()),stale_reason='SOURCE_VERSION_SUPERSEDED'
  WHERE status='ACTIVE' AND (from_version_id=NEW.previous_version_id OR to_version_id=NEW.previous_version_id);
  PERFORM set_config('app.ontology_relation_state_authorized','0',true);
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_guard_knowledge_relation_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF ROW(OLD.relation_id,OLD.tenant_id,OLD.from_item_id,OLD.from_version_id,OLD.relation_type,OLD.to_item_id,OLD.to_version_id,OLD.provenance,OLD.confidence,OLD.created_by,OLD.created_at)
     IS DISTINCT FROM ROW(NEW.relation_id,NEW.tenant_id,NEW.from_item_id,NEW.from_version_id,NEW.relation_type,NEW.to_item_id,NEW.to_version_id,NEW.provenance,NEW.confidence,NEW.created_by,NEW.created_at) THEN
    RAISE EXCEPTION 'knowledge relation assertions are immutable' USING ERRCODE='42501';
  END IF;
  IF OLD.status IS DISTINCT FROM NEW.status THEN
    IF NEW.status <> 'STALE' OR COALESCE(current_setting('app.ontology_relation_state_authorized',true),'') <> '1' THEN
      RAISE EXCEPTION 'knowledge relation status transition forbidden' USING ERRCODE='42501';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_guard_ontology_category_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.category IS DISTINCT FROM NEW.category AND COALESCE(current_setting('app.ontology_transition_authorized',true),'') <> '1' THEN
    RAISE EXCEPTION 'direct knowledge category update forbidden; use ontology transition' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_apply_ontology_transition(
  p_transition_id text,p_item_id text,p_to_category text,p_actor text,p_reason text,p_evidence jsonb
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE from_category text; DECLARE item_tenant text; DECLARE current_version text;
BEGIN
  SELECT category,tenant_id INTO from_category,item_tenant FROM memory_items WHERE item_id=p_item_id FOR UPDATE;
  IF from_category IS NULL THEN RAISE EXCEPTION 'memory not found for ontology transition'; END IF;
  IF NOT EXISTS(SELECT 1 FROM ontology_transition_rules r WHERE r.from_category=from_category AND r.to_category=p_to_category) THEN
    RAISE EXCEPTION 'invalid ontology transition: % -> %',from_category,p_to_category USING ERRCODE='23514';
  END IF;
  SELECT version_id INTO current_version FROM memory_versions WHERE item_id=p_item_id ORDER BY version_no DESC LIMIT 1;
  PERFORM set_config('app.ontology_transition_authorized','1',true);
  UPDATE memory_items SET category=p_to_category,validation_status='UNVALIDATED',governor_eligible=false WHERE item_id=p_item_id;
  PERFORM set_config('app.ontology_transition_authorized','0',true);
  INSERT INTO memory_ontology_transitions(transition_id,tenant_id,item_id,version_id,from_category,to_category,actor_id,reason,evidence)
  VALUES(p_transition_id,item_tenant,p_item_id,current_version,from_category,p_to_category,p_actor,p_reason,COALESCE(p_evidence,'{}'::jsonb));
  PERFORM set_config('app.ontology_relation_state_authorized','1',true);
  UPDATE memory_knowledge_relations
  SET status='STALE',staled_at=COALESCE(staled_at,now()),stale_reason='ONTOLOGY_CATEGORY_TRANSITION'
  WHERE status='ACTIVE' AND (from_item_id=p_item_id OR to_item_id=p_item_id);
  PERFORM set_config('app.ontology_relation_state_authorized','0',true);
  UPDATE memory_derived_artifacts a SET status='STALE',updated_at=now(),staled_at=COALESCE(staled_at,now()),
      invalidation_reason='SOURCE_ONTOLOGY_TRANSITION',stale_source_version_id=current_version
  WHERE a.status='READY' AND EXISTS(SELECT 1 FROM memory_artifact_dependencies d WHERE d.artifact_id=a.artifact_id AND d.source_item_id=p_item_id);
  RETURN p_transition_id;
END;
$$;

CREATE OR REPLACE FUNCTION forbid_ontology_rule_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'ontology rules are immutable; change through a versioned migration' USING ERRCODE='42501'; END;
$$;

DROP TRIGGER IF EXISTS trg_validate_knowledge_relation ON memory_knowledge_relations;
CREATE TRIGGER trg_validate_knowledge_relation BEFORE INSERT ON memory_knowledge_relations FOR EACH ROW EXECUTE FUNCTION memory_validate_knowledge_relation();
DROP TRIGGER IF EXISTS trg_guard_knowledge_relation_update ON memory_knowledge_relations;
CREATE TRIGGER trg_guard_knowledge_relation_update BEFORE UPDATE ON memory_knowledge_relations FOR EACH ROW EXECUTE FUNCTION memory_guard_knowledge_relation_update();
DROP TRIGGER IF EXISTS trg_knowledge_relation_insert_event ON memory_knowledge_relations;
CREATE TRIGGER trg_knowledge_relation_insert_event AFTER INSERT ON memory_knowledge_relations FOR EACH ROW EXECUTE FUNCTION memory_record_knowledge_relation_insert();
DROP TRIGGER IF EXISTS trg_knowledge_relation_status_event ON memory_knowledge_relations;
CREATE TRIGGER trg_knowledge_relation_status_event AFTER UPDATE OF status ON memory_knowledge_relations FOR EACH ROW EXECUTE FUNCTION memory_record_knowledge_relation_status();
DROP TRIGGER IF EXISTS trg_stale_knowledge_relations_on_new_version ON memory_versions;
CREATE TRIGGER trg_stale_knowledge_relations_on_new_version AFTER INSERT ON memory_versions FOR EACH ROW EXECUTE FUNCTION memory_stale_knowledge_relations_on_new_version();
DROP TRIGGER IF EXISTS trg_guard_ontology_category_update ON memory_items;
CREATE TRIGGER trg_guard_ontology_category_update BEFORE UPDATE OF category ON memory_items FOR EACH ROW EXECUTE FUNCTION memory_guard_ontology_category_update();

DROP TRIGGER IF EXISTS trg_ontology_legacy_category_migrations_append_only ON ontology_legacy_category_migrations;
CREATE TRIGGER trg_ontology_legacy_category_migrations_append_only BEFORE UPDATE OR DELETE ON ontology_legacy_category_migrations FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_knowledge_relation_events_append_only ON memory_knowledge_relation_events;
CREATE TRIGGER trg_knowledge_relation_events_append_only BEFORE UPDATE OR DELETE ON memory_knowledge_relation_events FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_ontology_transitions_append_only ON memory_ontology_transitions;
CREATE TRIGGER trg_ontology_transitions_append_only BEFORE UPDATE OR DELETE ON memory_ontology_transitions FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_ontology_relation_rules_immutable ON ontology_relation_rules;
CREATE TRIGGER trg_ontology_relation_rules_immutable BEFORE INSERT OR UPDATE OR DELETE ON ontology_relation_rules FOR EACH ROW EXECUTE FUNCTION forbid_ontology_rule_mutation();
DROP TRIGGER IF EXISTS trg_ontology_transition_rules_immutable ON ontology_transition_rules;
CREATE TRIGGER trg_ontology_transition_rules_immutable BEFORE INSERT OR UPDATE OR DELETE ON ontology_transition_rules FOR EACH ROW EXECUTE FUNCTION forbid_ontology_rule_mutation();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ontology_legacy_category_migrations','memory_knowledge_relations','memory_knowledge_relation_events','memory_ontology_transitions'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (memory_rls_visible(tenant_id)) WITH CHECK (memory_rls_visible(tenant_id))',t);
  END LOOP;
END $$;

INSERT INTO schema_meta(key,value) VALUES('ontology_version','KO-1.0.0') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.15.0') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
