-- MEMORIA PLUS P12: complete bitemporal contract
CREATE TABLE IF NOT EXISTS temporal_entity_contracts(
  entity_name text PRIMARY KEY,
  temporal_kind text NOT NULL CHECK(temporal_kind IN ('BITEMPORAL','OPERATIONAL')),
  rationale text NOT NULL,
  storage_mode text NOT NULL DEFAULT 'INLINE' CHECK(storage_mode IN ('INLINE','SIDECAR')),
  storage_entity text,
  contract_version text NOT NULL DEFAULT 'BT-1.0.0',
  registered_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO temporal_entity_contracts(entity_name,temporal_kind,rationale,storage_mode,storage_entity) VALUES
('agent_leases','OPERATIONAL','lease expiry/update state, not a remembered fact','INLINE',NULL),
('audit_events','OPERATIONAL','tamper-evident persistence ledger; created_at is ledger transaction time','INLINE',NULL),
('checkpoints','BITEMPORAL','mission state snapshot has fact, knowledge and validity time','INLINE',NULL),
('context_packs','BITEMPORAL','materialized mission context snapshot','INLINE',NULL),
('conversation_ingestion_events','BITEMPORAL','external conversation event may arrive late','SIDECAR','conversation_ingestion_event_temporal'),
('experience_graph_edges','BITEMPORAL','causal/temporal mission relation','INLINE',NULL),
('experience_graph_nodes','BITEMPORAL','mission fact/event node','INLINE',NULL),
('external_session_bindings','BITEMPORAL','external identity binding has effective validity','INLINE',NULL),
('governor_project_bindings','OPERATIONAL','current authorization binding state','INLINE',NULL),
('idempotency_records','OPERATIONAL','request deduplication state','INLINE',NULL),
('learning_policy_versions','OPERATIONAL','immutable policy metadata','INLINE',NULL),
('legacy_security_audit','OPERATIONAL','legacy technical audit record','INLINE',NULL),
('memory_applications','BITEMPORAL','memory application event','INLINE',NULL),
('memory_artifact_dependencies','BITEMPORAL','dependency assertion validity','INLINE',NULL),
('memory_artifact_state_events','BITEMPORAL','derived artifact state event','INLINE',NULL),
('memory_causal_assessments','BITEMPORAL','causal assessment event','INLINE',NULL),
('memory_derived_artifacts','BITEMPORAL','derived assertion validity interval','INLINE',NULL),
('memory_embeddings','OPERATIONAL','replaceable derived index state','INLINE',NULL),
('memory_events','BITEMPORAL','memory domain event','INLINE',NULL),
('memory_experience_edges','BITEMPORAL','legacy experience relation event','INLINE',NULL),
('memory_items','BITEMPORAL','memory assertion validity','INLINE',NULL),
('memory_knowledge_relation_events','BITEMPORAL','knowledge relation state event','INLINE',NULL),
('memory_knowledge_relations','BITEMPORAL','knowledge relation validity','INLINE',NULL),
('memory_learning_events','BITEMPORAL','learning event','INLINE',NULL),
('memory_ontology_transitions','BITEMPORAL','ontology transition event','INLINE',NULL),
('memory_outbox','OPERATIONAL','delivery queue state','INLINE',NULL),
('memory_outcomes','BITEMPORAL','observed application outcome','INLINE',NULL),
('memory_validations','BITEMPORAL','validation assertion event','INLINE',NULL),
('memory_version_learning','OPERATIONAL','current aggregate learning state','INLINE',NULL),
('memory_versions','BITEMPORAL','versioned assertion validity','INLINE',NULL),
('ontology_legacy_category_migrations','OPERATIONAL','one-time migration ledger','INLINE',NULL),
('provider_invocations','BITEMPORAL','provider invocation event and observation','INLINE',NULL),
('retention_holds','OPERATIONAL','current retention control state','INLINE',NULL),
('retrieval_traces','BITEMPORAL','retrieval decision event','INLINE',NULL),
('schema_meta','OPERATIONAL','schema metadata state','INLINE',NULL),
('session_checkpoints','BITEMPORAL','session state snapshot','INLINE',NULL),
('session_rotations','OPERATIONAL','current rotation control state','INLINE',NULL),
('sovereign_decision_evidence','BITEMPORAL','evidence binding validity','INLINE',NULL),
('sovereign_decision_outcomes','BITEMPORAL','decision outcome event','INLINE',NULL),
('sovereign_decision_replays','BITEMPORAL','replay materialization event','INLINE',NULL),
('sovereign_decisions','BITEMPORAL','sovereign decision event','INLINE',NULL),
('sovereign_sessions','BITEMPORAL','sovereign session state validity','INLINE',NULL)
ON CONFLICT(entity_name) DO UPDATE SET
  temporal_kind=EXCLUDED.temporal_kind,
  rationale=EXCLUDED.rationale,
  storage_mode=EXCLUDED.storage_mode,
  storage_entity=EXCLUDED.storage_entity,
  contract_version='BT-1.0.0';

CREATE TABLE IF NOT EXISTS conversation_ingestion_event_temporal(
  event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS idx_conversation_ingestion_event_temporal_bt
  ON conversation_ingestion_event_temporal(valid_from,valid_to,observed_at);
ALTER TABLE conversation_ingestion_event_temporal ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_ingestion_event_temporal FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON conversation_ingestion_event_temporal;
CREATE POLICY tenant_isolation ON conversation_ingestion_event_temporal
USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
INSERT INTO conversation_ingestion_event_temporal(event_id,tenant_id,occurred_at,observed_at,valid_from,created_at)
SELECT event_id,tenant_id,created_at,created_at,created_at,created_at FROM conversation_ingestion_events
ON CONFLICT(event_id) DO NOTHING;
INSERT INTO temporal_entity_contracts(entity_name,temporal_kind,rationale,storage_mode,storage_entity)
VALUES('conversation_ingestion_event_temporal','BITEMPORAL','bitemporal sidecar for memory_admin-owned ingestion events','INLINE',NULL)
ON CONFLICT(entity_name) DO UPDATE SET temporal_kind=EXCLUDED.temporal_kind,rationale=EXCLUDED.rationale,storage_mode=EXCLUDED.storage_mode,storage_entity=EXCLUDED.storage_entity,contract_version='BT-1.0.0';

CREATE TABLE IF NOT EXISTS bitemporal_legacy_repairs(
  repair_id bigserial PRIMARY KEY,
  entity_name text NOT NULL,
  row_identity jsonb NOT NULL,
  original_occurred_at timestamptz NOT NULL,
  original_observed_at timestamptz NOT NULL,
  repaired_observed_at timestamptz NOT NULL,
  reason text NOT NULL,
  repaired_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO bitemporal_legacy_repairs(entity_name,row_identity,original_occurred_at,original_observed_at,repaired_observed_at,reason)
SELECT 'memory_experience_edges',jsonb_build_object('edge_id',edge_id),occurred_at,observed_at,occurred_at,'LEGACY_OBSERVED_BEFORE_OCCURRED'
FROM memory_experience_edges WHERE observed_at < occurred_at;
INSERT INTO bitemporal_legacy_repairs(entity_name,row_identity,original_occurred_at,original_observed_at,repaired_observed_at,reason)
SELECT 'sovereign_decisions',jsonb_build_object('decision_id',decision_id),occurred_at,observed_at,occurred_at,'LEGACY_OBSERVED_BEFORE_OCCURRED'
FROM sovereign_decisions WHERE observed_at < occurred_at;
INSERT INTO bitemporal_legacy_repairs(entity_name,row_identity,original_occurred_at,original_observed_at,repaired_observed_at,reason)
SELECT 'sovereign_decision_outcomes',jsonb_build_object('decision_outcome_id',decision_outcome_id),occurred_at,observed_at,occurred_at,'LEGACY_OBSERVED_BEFORE_OCCURRED'
FROM sovereign_decision_outcomes WHERE observed_at < occurred_at;

DO $$
DECLARE
  r record;
  has_valid_until boolean;
  has_staled_at boolean;
  has_invalidated_at boolean;
  valid_to_expr text;
  cname text;
BEGIN
  FOR r IN SELECT entity_name FROM temporal_entity_contracts WHERE temporal_kind='BITEMPORAL' AND storage_mode='INLINE' ORDER BY entity_name LOOP
    EXECUTE format('ALTER TABLE %I DISABLE TRIGGER USER', r.entity_name);
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS occurred_at timestamptz', r.entity_name);
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS observed_at timestamptz', r.entity_name);
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS valid_from timestamptz', r.entity_name);
    EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS valid_to timestamptz', r.entity_name);

    SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=r.entity_name AND column_name='valid_until') INTO has_valid_until;
    SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=r.entity_name AND column_name='staled_at') INTO has_staled_at;
    SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=r.entity_name AND column_name='invalidated_at') INTO has_invalidated_at;

    IF r.entity_name='memory_items' THEN
      EXECUTE 'UPDATE memory_items SET occurred_at=COALESCE(occurred_at,valid_from,created_at), observed_at=GREATEST(COALESCE(observed_at,created_at,occurred_at,valid_from),COALESCE(occurred_at,valid_from,created_at)), valid_from=COALESCE(valid_from,occurred_at,created_at), valid_to=COALESCE(valid_to,valid_until)';
    ELSE
      valid_to_expr := 'valid_to';
      IF has_valid_until THEN valid_to_expr := 'COALESCE(valid_to,valid_until)'; END IF;
      IF has_staled_at THEN valid_to_expr := format('COALESCE(%s,staled_at)',valid_to_expr); END IF;
      IF has_invalidated_at THEN valid_to_expr := format('COALESCE(%s,invalidated_at)',valid_to_expr); END IF;
      EXECUTE format('UPDATE %I SET occurred_at=COALESCE(occurred_at,created_at), observed_at=GREATEST(COALESCE(observed_at,created_at,occurred_at),COALESCE(occurred_at,created_at)), valid_from=COALESCE(valid_from,occurred_at,created_at), valid_to=%s', r.entity_name, valid_to_expr);
    END IF;

    EXECUTE format('ALTER TABLE %I ALTER COLUMN occurred_at SET NOT NULL', r.entity_name);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN observed_at SET NOT NULL', r.entity_name);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN valid_from SET NOT NULL', r.entity_name);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN occurred_at DROP DEFAULT', r.entity_name);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN observed_at DROP DEFAULT', r.entity_name);
    EXECUTE format('ALTER TABLE %I ALTER COLUMN valid_from DROP DEFAULT', r.entity_name);

    cname := left(r.entity_name || '_bt_observed_ck',63);
    IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname=cname) THEN
      EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK(observed_at >= occurred_at)',r.entity_name,cname);
    END IF;
    cname := left(r.entity_name || '_bt_validity_ck',63);
    IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname=cname) THEN
      EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK(valid_to IS NULL OR valid_to > valid_from)',r.entity_name,cname);
    END IF;
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I(valid_from,valid_to,observed_at)',left('idx_'||r.entity_name||'_bitemporal',63),r.entity_name);
    EXECUTE format('ALTER TABLE %I ENABLE TRIGGER USER', r.entity_name);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION normalize_bitemporal_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.occurred_at := COALESCE(NEW.occurred_at, now());
  NEW.observed_at := COALESCE(NEW.observed_at, now());
  NEW.valid_from := COALESCE(NEW.valid_from, NEW.occurred_at);
  IF NEW.observed_at < NEW.occurred_at THEN
    RAISE EXCEPTION 'observed_at cannot precede occurred_at' USING ERRCODE='23514';
  END IF;
  IF NEW.valid_to IS NOT NULL AND NEW.valid_to <= NEW.valid_from THEN
    RAISE EXCEPTION 'valid_to must be greater than valid_from' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

DO $$
DECLARE r record; trg text;
BEGIN
  FOR r IN SELECT entity_name FROM temporal_entity_contracts WHERE temporal_kind='BITEMPORAL' AND storage_mode='INLINE' ORDER BY entity_name LOOP
    trg := left('trg_' || r.entity_name || '_bitemporal_insert',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,r.entity_name);
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION normalize_bitemporal_insert()',trg,r.entity_name);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION sync_memory_item_validity_alias() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.valid_to IS NOT NULL AND NEW.valid_until IS NOT NULL AND NEW.valid_to IS DISTINCT FROM NEW.valid_until THEN
      RAISE EXCEPTION 'valid_to and deprecated valid_until must match' USING ERRCODE='23514';
    END IF;
    NEW.valid_to := COALESCE(NEW.valid_to,NEW.valid_until);
    NEW.valid_until := COALESCE(NEW.valid_until,NEW.valid_to);
  ELSE
    IF NEW.valid_to IS DISTINCT FROM OLD.valid_to AND NEW.valid_until IS NOT DISTINCT FROM OLD.valid_until THEN
      NEW.valid_until := NEW.valid_to;
    ELSIF NEW.valid_until IS DISTINCT FROM OLD.valid_until AND NEW.valid_to IS NOT DISTINCT FROM OLD.valid_to THEN
      NEW.valid_to := NEW.valid_until;
    ELSIF NEW.valid_to IS DISTINCT FROM NEW.valid_until THEN
      RAISE EXCEPTION 'valid_to and deprecated valid_until must match' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_memory_items_validity_alias ON memory_items;
CREATE TRIGGER trg_memory_items_validity_alias
BEFORE INSERT OR UPDATE OF valid_to,valid_until ON memory_items
FOR EACH ROW EXECUTE FUNCTION sync_memory_item_validity_alias();

CREATE OR REPLACE FUNCTION memory_bitemporal_visible(
  row_valid_from timestamptz,
  row_valid_to timestamptz,
  row_observed_at timestamptz,
  row_created_at timestamptz,
  at_valid timestamptz,
  at_known timestamptz
) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT row_valid_from <= at_valid
     AND (row_valid_to IS NULL OR row_valid_to > at_valid)
     AND row_observed_at <= at_known
     AND row_created_at <= at_known
$$;

CREATE OR REPLACE FUNCTION temporal_contract_unclassified_count() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT count(*) FROM (
    SELECT c.table_name
    FROM information_schema.columns c
    WHERE c.table_schema='public'
    GROUP BY c.table_name
    HAVING count(*) FILTER(WHERE c.column_name IN ('occurred_at','observed_at','valid_from','valid_to','valid_until','created_at','updated_at','staled_at','invalidated_at','closed_at')) > 0
  ) x
  LEFT JOIN temporal_entity_contracts t ON t.entity_name=x.table_name
  WHERE t.entity_name IS NULL AND x.table_name <> 'temporal_entity_contracts'
$$;

CREATE OR REPLACE FUNCTION reject_temporal_contract_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'temporal entity contracts are immutable after migration' USING ERRCODE='55000';
END $$;
DROP TRIGGER IF EXISTS trg_temporal_contract_immutable ON temporal_entity_contracts;
CREATE TRIGGER trg_temporal_contract_immutable BEFORE INSERT OR UPDATE OR DELETE ON temporal_entity_contracts
FOR EACH ROW EXECUTE FUNCTION reject_temporal_contract_mutation();

INSERT INTO schema_meta(key,value) VALUES
('schema_version','memory-0.20.0'),
('bitemporal_version','BT-1.0.0'),
('bitemporal_contract_entities',(SELECT count(*)::text FROM temporal_entity_contracts)),
('bitemporal_fact_entities',(SELECT count(*)::text FROM temporal_entity_contracts WHERE temporal_kind='BITEMPORAL')),
('bitemporal_legacy_memory_backfill_count',(SELECT count(*)::text FROM memory_items))
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
