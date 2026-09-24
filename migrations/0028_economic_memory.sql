-- MEMORIA PLUS P13: formal economic memory ontology integrated with Experience Graph and bitemporality.

CREATE TABLE IF NOT EXISTS economic_entities(
  economic_entity_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  entity_type text NOT NULL CHECK(entity_type IN ('PRODUCT','SKU','CAMPAIGN','AD')),
  external_ref text NOT NULL,
  parent_entity_id text REFERENCES economic_entities(economic_entity_id) ON DELETE RESTRICT,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(external_ref)) BETWEEN 1 AND 300),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from),
  UNIQUE(tenant_id,entity_type,external_ref)
);
CREATE INDEX IF NOT EXISTS idx_economic_entities_temporal ON economic_entities(tenant_id,entity_type,valid_from,valid_to,observed_at);
CREATE INDEX IF NOT EXISTS idx_economic_entities_parent ON economic_entities(tenant_id,parent_entity_id) WHERE parent_entity_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS economic_states(
  economic_state_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  economic_entity_id text NOT NULL REFERENCES economic_entities(economic_entity_id) ON DELETE RESTRICT,
  mission_id text,
  state_type text NOT NULL CHECK(state_type IN ('INVENTORY','MARGIN','CAPITAL')),
  value numeric NOT NULL,
  unit text NOT NULL,
  currency text,
  state_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(unit)) BETWEEN 1 AND 40),
  CHECK(currency IS NULL OR currency ~ '^[A-Z]{3}$'),
  CHECK(state_type NOT IN ('INVENTORY','CAPITAL') OR value >= 0),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS idx_economic_states_entity_time ON economic_states(tenant_id,economic_entity_id,state_type,valid_from,valid_to,observed_at);
CREATE INDEX IF NOT EXISTS idx_economic_states_mission ON economic_states(tenant_id,mission_id,occurred_at) WHERE mission_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS economic_results(
  economic_result_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  mission_id text NOT NULL,
  economic_entity_id text REFERENCES economic_entities(economic_entity_id) ON DELETE RESTRICT,
  metric_type text NOT NULL CHECK(metric_type IN ('REVENUE','COST','PROFIT','ROI','ROAS','CONTRIBUTION_MARGIN','INVENTORY_VALUE','CAPITAL_RETURN','CUSTOM')),
  value numeric NOT NULL,
  unit text NOT NULL,
  currency text,
  experience_result_node_id text REFERENCES experience_graph_nodes(node_id) ON DELETE RESTRICT,
  proof jsonb NOT NULL,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(mission_id)) BETWEEN 1 AND 240),
  CHECK(length(trim(unit)) BETWEEN 1 AND 40),
  CHECK(currency IS NULL OR currency ~ '^[A-Z]{3}$'),
  CHECK(jsonb_typeof(proof)='object' AND proof <> '{}'::jsonb),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS idx_economic_results_mission_time ON economic_results(tenant_id,mission_id,valid_from,valid_to,observed_at);
CREATE INDEX IF NOT EXISTS idx_economic_results_entity ON economic_results(tenant_id,economic_entity_id,metric_type,occurred_at) WHERE economic_entity_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS economic_attributions(
  economic_attribution_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  economic_result_id text NOT NULL REFERENCES economic_results(economic_result_id) ON DELETE RESTRICT,
  source_kind text NOT NULL CHECK(source_kind IN ('SOVEREIGN_DECISION','EXPERIENCE_INTERVENTION','EXPERIENCE_EVIDENCE','ECONOMIC_ENTITY','ECONOMIC_STATE')),
  source_id text NOT NULL,
  weight numeric NOT NULL CHECK(weight > 0 AND weight <= 1),
  rationale text NOT NULL DEFAULT '',
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_snapshot jsonb NOT NULL,
  source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(source_id)) BETWEEN 1 AND 240),
  CHECK(jsonb_typeof(source_snapshot)='object' AND source_snapshot <> '{}'::jsonb),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from),
  UNIQUE(economic_result_id,source_kind,source_id)
);
CREATE INDEX IF NOT EXISTS idx_economic_attributions_result ON economic_attributions(tenant_id,economic_result_id,source_kind);
CREATE INDEX IF NOT EXISTS idx_economic_attributions_source ON economic_attributions(tenant_id,source_kind,source_id);

CREATE OR REPLACE FUNCTION memory_validate_economic_entity() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE p_tenant text;
DECLARE p_type text;
BEGIN
  IF NEW.entity_type IN ('PRODUCT','CAMPAIGN') AND NEW.parent_entity_id IS NOT NULL THEN
    RAISE EXCEPTION '% economic entity cannot have parent',NEW.entity_type USING ERRCODE='23514';
  END IF;
  IF NEW.entity_type IN ('SKU','AD') AND NEW.parent_entity_id IS NULL THEN
    RAISE EXCEPTION '% economic entity requires parent',NEW.entity_type USING ERRCODE='23514';
  END IF;
  IF NEW.parent_entity_id IS NOT NULL THEN
    SELECT tenant_id,entity_type INTO p_tenant,p_type FROM economic_entities WHERE economic_entity_id=NEW.parent_entity_id;
    IF p_tenant IS NULL THEN RAISE EXCEPTION 'economic parent entity not found' USING ERRCODE='23503'; END IF;
    IF p_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant economic parent forbidden' USING ERRCODE='42501'; END IF;
    IF NEW.entity_type='SKU' AND p_type<>'PRODUCT' THEN RAISE EXCEPTION 'SKU parent must be PRODUCT' USING ERRCODE='23514'; END IF;
    IF NEW.entity_type='AD' AND p_type<>'CAMPAIGN' THEN RAISE EXCEPTION 'AD parent must be CAMPAIGN' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_economic_state() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e_tenant text;
BEGIN
  SELECT tenant_id INTO e_tenant FROM economic_entities WHERE economic_entity_id=NEW.economic_entity_id;
  IF e_tenant IS NULL THEN RAISE EXCEPTION 'economic state entity not found' USING ERRCODE='23503'; END IF;
  IF e_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant economic state forbidden' USING ERRCODE='42501'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_economic_result() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE e_tenant text;
DECLARE n_tenant text;
DECLARE n_mission text;
DECLARE n_type text;
BEGIN
  IF NEW.economic_entity_id IS NOT NULL THEN
    SELECT tenant_id INTO e_tenant FROM economic_entities WHERE economic_entity_id=NEW.economic_entity_id;
    IF e_tenant IS NULL THEN RAISE EXCEPTION 'economic result entity not found' USING ERRCODE='23503'; END IF;
    IF e_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant economic result entity forbidden' USING ERRCODE='42501'; END IF;
  END IF;
  IF NEW.experience_result_node_id IS NOT NULL THEN
    SELECT tenant_id,mission_id,node_type INTO n_tenant,n_mission,n_type FROM experience_graph_nodes WHERE node_id=NEW.experience_result_node_id;
    IF n_tenant IS NULL THEN RAISE EXCEPTION 'economic result experience node not found' USING ERRCODE='23503'; END IF;
    IF n_tenant<>NEW.tenant_id OR n_mission<>NEW.mission_id THEN RAISE EXCEPTION 'economic result experience node scope mismatch' USING ERRCODE='42501'; END IF;
    IF n_type<>'RESULT' THEN RAISE EXCEPTION 'economic result experience node must be RESULT' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_economic_attribution() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE r_tenant text;
DECLARE r_mission text;
DECLARE s_tenant text;
DECLARE s_mission text;
DECLARE s_type text;
DECLARE current_weight numeric;
BEGIN
  SELECT tenant_id,mission_id INTO r_tenant,r_mission FROM economic_results WHERE economic_result_id=NEW.economic_result_id;
  IF r_tenant IS NULL THEN RAISE EXCEPTION 'economic attribution result not found' USING ERRCODE='23503'; END IF;
  IF r_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'economic attribution result tenant mismatch' USING ERRCODE='42501'; END IF;

  IF NEW.source_kind='SOVEREIGN_DECISION' THEN
    SELECT tenant_id,mission_id INTO s_tenant,s_mission FROM sovereign_decisions WHERE decision_id=NEW.source_id;
    IF s_tenant IS NULL THEN RAISE EXCEPTION 'economic attribution decision not found' USING ERRCODE='23503'; END IF;
    IF s_tenant<>r_tenant OR s_mission<>r_mission THEN RAISE EXCEPTION 'economic attribution decision scope mismatch' USING ERRCODE='42501'; END IF;
  ELSIF NEW.source_kind IN ('EXPERIENCE_INTERVENTION','EXPERIENCE_EVIDENCE') THEN
    SELECT tenant_id,mission_id,node_type INTO s_tenant,s_mission,s_type FROM experience_graph_nodes WHERE node_id=NEW.source_id;
    IF s_tenant IS NULL THEN RAISE EXCEPTION 'economic attribution experience node not found' USING ERRCODE='23503'; END IF;
    IF s_tenant<>r_tenant OR s_mission<>r_mission THEN RAISE EXCEPTION 'economic attribution experience scope mismatch' USING ERRCODE='42501'; END IF;
    IF NEW.source_kind='EXPERIENCE_INTERVENTION' AND s_type<>'INTERVENTION' THEN RAISE EXCEPTION 'economic attribution requires INTERVENTION node' USING ERRCODE='23514'; END IF;
    IF NEW.source_kind='EXPERIENCE_EVIDENCE' AND s_type<>'EVIDENCE' THEN RAISE EXCEPTION 'economic attribution requires EVIDENCE node' USING ERRCODE='23514'; END IF;
  ELSIF NEW.source_kind='ECONOMIC_ENTITY' THEN
    SELECT tenant_id INTO s_tenant FROM economic_entities WHERE economic_entity_id=NEW.source_id;
    IF s_tenant IS NULL THEN RAISE EXCEPTION 'economic attribution entity not found' USING ERRCODE='23503'; END IF;
    IF s_tenant<>r_tenant THEN RAISE EXCEPTION 'economic attribution entity tenant mismatch' USING ERRCODE='42501'; END IF;
  ELSIF NEW.source_kind='ECONOMIC_STATE' THEN
    SELECT tenant_id,mission_id INTO s_tenant,s_mission FROM economic_states WHERE economic_state_id=NEW.source_id;
    IF s_tenant IS NULL THEN RAISE EXCEPTION 'economic attribution state not found' USING ERRCODE='23503'; END IF;
    IF s_tenant<>r_tenant THEN RAISE EXCEPTION 'economic attribution state tenant mismatch' USING ERRCODE='42501'; END IF;
    IF s_mission IS NOT NULL AND s_mission<>r_mission THEN RAISE EXCEPTION 'economic attribution state mission mismatch' USING ERRCODE='42501'; END IF;
  END IF;

  SELECT COALESCE(sum(weight),0) INTO current_weight FROM economic_attributions WHERE economic_result_id=NEW.economic_result_id;
  IF current_weight + NEW.weight > 1 THEN RAISE EXCEPTION 'economic attribution weights exceed 1.0' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_require_economic_result_attribution() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM economic_attributions WHERE economic_result_id=NEW.economic_result_id) THEN
    RAISE EXCEPTION 'economic result requires at least one attribution' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION memory_require_economic_mutation_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF COALESCE(current_setting('app.economic_mutation_authorized',true),'0') <> '1' THEN
    RAISE EXCEPTION 'economic memory mutation requires canonical API/store boundary' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_economic_entities_set_tenant ON economic_entities;
CREATE TRIGGER trg_economic_entities_set_tenant BEFORE INSERT ON economic_entities FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();
DROP TRIGGER IF EXISTS trg_economic_entities_context ON economic_entities;
CREATE TRIGGER trg_economic_entities_context BEFORE INSERT ON economic_entities FOR EACH ROW EXECUTE FUNCTION memory_require_economic_mutation_context();
DROP TRIGGER IF EXISTS trg_economic_entities_validate ON economic_entities;
CREATE TRIGGER trg_economic_entities_validate BEFORE INSERT ON economic_entities FOR EACH ROW EXECUTE FUNCTION memory_validate_economic_entity();
DROP TRIGGER IF EXISTS trg_economic_entities_append_only ON economic_entities;
CREATE TRIGGER trg_economic_entities_append_only BEFORE UPDATE OR DELETE ON economic_entities FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_economic_states_set_tenant ON economic_states;
CREATE TRIGGER trg_economic_states_set_tenant BEFORE INSERT ON economic_states FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();
DROP TRIGGER IF EXISTS trg_economic_states_context ON economic_states;
CREATE TRIGGER trg_economic_states_context BEFORE INSERT ON economic_states FOR EACH ROW EXECUTE FUNCTION memory_require_economic_mutation_context();
DROP TRIGGER IF EXISTS trg_economic_states_validate ON economic_states;
CREATE TRIGGER trg_economic_states_validate BEFORE INSERT ON economic_states FOR EACH ROW EXECUTE FUNCTION memory_validate_economic_state();
DROP TRIGGER IF EXISTS trg_economic_states_append_only ON economic_states;
CREATE TRIGGER trg_economic_states_append_only BEFORE UPDATE OR DELETE ON economic_states FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_economic_results_set_tenant ON economic_results;
CREATE TRIGGER trg_economic_results_set_tenant BEFORE INSERT ON economic_results FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();
DROP TRIGGER IF EXISTS trg_economic_results_context ON economic_results;
CREATE TRIGGER trg_economic_results_context BEFORE INSERT ON economic_results FOR EACH ROW EXECUTE FUNCTION memory_require_economic_mutation_context();
DROP TRIGGER IF EXISTS trg_economic_results_validate ON economic_results;
CREATE TRIGGER trg_economic_results_validate BEFORE INSERT ON economic_results FOR EACH ROW EXECUTE FUNCTION memory_validate_economic_result();
DROP TRIGGER IF EXISTS trg_economic_results_append_only ON economic_results;
CREATE TRIGGER trg_economic_results_append_only BEFORE UPDATE OR DELETE ON economic_results FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_economic_results_require_attribution ON economic_results;
CREATE CONSTRAINT TRIGGER trg_economic_results_require_attribution AFTER INSERT ON economic_results DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION memory_require_economic_result_attribution();

DROP TRIGGER IF EXISTS trg_economic_attributions_set_tenant ON economic_attributions;
CREATE TRIGGER trg_economic_attributions_set_tenant BEFORE INSERT ON economic_attributions FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();
DROP TRIGGER IF EXISTS trg_economic_attributions_context ON economic_attributions;
CREATE TRIGGER trg_economic_attributions_context BEFORE INSERT ON economic_attributions FOR EACH ROW EXECUTE FUNCTION memory_require_economic_mutation_context();
DROP TRIGGER IF EXISTS trg_economic_attributions_validate ON economic_attributions;
CREATE TRIGGER trg_economic_attributions_validate BEFORE INSERT ON economic_attributions FOR EACH ROW EXECUTE FUNCTION memory_validate_economic_attribution();
DROP TRIGGER IF EXISTS trg_economic_attributions_append_only ON economic_attributions;
CREATE TRIGGER trg_economic_attributions_append_only BEFORE UPDATE OR DELETE ON economic_attributions FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

ALTER TABLE economic_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE economic_entities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON economic_entities;
CREATE POLICY tenant_isolation ON economic_entities USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
ALTER TABLE economic_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE economic_states FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON economic_states;
CREATE POLICY tenant_isolation ON economic_states USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
ALTER TABLE economic_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE economic_results FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON economic_results;
CREATE POLICY tenant_isolation ON economic_results USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
ALTER TABLE economic_attributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE economic_attributions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON economic_attributions;
CREATE POLICY tenant_isolation ON economic_attributions USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

GRANT SELECT,INSERT ON economic_entities,economic_states,economic_results,economic_attributions TO memory_app;

ALTER TABLE temporal_entity_contracts DISABLE TRIGGER trg_temporal_contract_immutable;
INSERT INTO temporal_entity_contracts(entity_name,temporal_kind,rationale,storage_mode,storage_entity,contract_version) VALUES
 ('economic_entities','BITEMPORAL','economic product/SKU/campaign/ad identity and validity','INLINE',NULL,'BT-1.0.0'),
 ('economic_states','BITEMPORAL','inventory/margin/capital economic state history','INLINE',NULL,'BT-1.0.0'),
 ('economic_results','BITEMPORAL','economic outcome history attributable to governed causes','INLINE',NULL,'BT-1.0.0'),
 ('economic_attributions','BITEMPORAL','economic result attribution history with sovereign source snapshots','INLINE',NULL,'BT-1.0.0')
ON CONFLICT(entity_name) DO NOTHING;
ALTER TABLE temporal_entity_contracts ENABLE TRIGGER trg_temporal_contract_immutable;

INSERT INTO schema_meta(key,value) VALUES
 ('schema_version','memory-0.21.0'),
 ('economic_memory_version','EM-1.0.0'),
 ('economic_entity_types','PRODUCT,SKU,CAMPAIGN,AD'),
 ('economic_state_types','INVENTORY,MARGIN,CAPITAL')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
