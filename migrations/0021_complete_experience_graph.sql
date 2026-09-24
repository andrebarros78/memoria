-- MEMORIA PLUS P08: complete first-class mission experience graph.

CREATE TABLE IF NOT EXISTS experience_graph_relation_rules(
  source_type text NOT NULL,
  relation_type text NOT NULL,
  target_type text NOT NULL,
  PRIMARY KEY(source_type,relation_type,target_type),
  CHECK(source_type IN ('HYPOTHESIS','EVIDENCE','DECISION','INTERVENTION','RESULT','LEARNING','KNOWLEDGE')),
  CHECK(target_type IN ('HYPOTHESIS','EVIDENCE','DECISION','INTERVENTION','RESULT','LEARNING','KNOWLEDGE')),
  CHECK(relation_type IN ('EVALUATED_BY','INFORMS','IMPLEMENTED_BY','PRODUCES','DERIVES','CONSOLIDATES'))
);

INSERT INTO experience_graph_relation_rules(source_type,relation_type,target_type) VALUES
 ('HYPOTHESIS','EVALUATED_BY','EVIDENCE'),
 ('EVIDENCE','INFORMS','DECISION'),
 ('DECISION','IMPLEMENTED_BY','INTERVENTION'),
 ('INTERVENTION','PRODUCES','RESULT'),
 ('RESULT','DERIVES','LEARNING'),
 ('RESULT','CONSOLIDATES','KNOWLEDGE'),
 ('LEARNING','CONSOLIDATES','KNOWLEDGE')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS experience_graph_nodes(
  node_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  mission_id text NOT NULL,
  node_type text NOT NULL CHECK(node_type IN ('HYPOTHESIS','EVIDENCE','DECISION','INTERVENTION','RESULT','LEARNING','KNOWLEDGE')),
  entity_ref text NOT NULL,
  memory_item_id text REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  memory_version_id text REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  memory_content_sha256 text,
  memory_category_snapshot text CHECK(memory_category_snapshot IS NULL OR memory_category_snapshot IN ('FACT','HYPOTHESIS','EVIDENCE','OBSERVATION','INFERENCE','CORRELATION','CAUSE','PROCEDURE','DECISION','INTERVENTION','OUTCOME','EXPERIMENT','LEARNING','CONSTRAINT','OBJECTIVE')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(mission_id)) BETWEEN 1 AND 240),
  CHECK(length(trim(entity_ref)) BETWEEN 1 AND 300),
  CHECK(observed_at >= occurred_at),
  CHECK(
    (memory_item_id IS NULL AND memory_version_id IS NULL AND memory_content_sha256 IS NULL AND memory_category_snapshot IS NULL)
    OR
    (memory_item_id IS NOT NULL AND memory_version_id IS NOT NULL AND memory_content_sha256 IS NOT NULL AND memory_category_snapshot IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_experience_graph_entity_ref ON experience_graph_nodes(tenant_id,mission_id,node_type,entity_ref);
CREATE INDEX IF NOT EXISTS idx_experience_graph_nodes_mission_time ON experience_graph_nodes(tenant_id,mission_id,occurred_at,node_id);
CREATE INDEX IF NOT EXISTS idx_experience_graph_nodes_memory ON experience_graph_nodes(tenant_id,memory_item_id,memory_version_id) WHERE memory_item_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS experience_graph_edges(
  graph_edge_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  mission_id text NOT NULL,
  from_node_id text NOT NULL REFERENCES experience_graph_nodes(node_id) ON DELETE RESTRICT,
  relation_type text NOT NULL CHECK(relation_type IN ('EVALUATED_BY','INFORMS','IMPLEMENTED_BY','PRODUCES','DERIVES','CONSOLIDATES')),
  to_node_id text NOT NULL REFERENCES experience_graph_nodes(node_id) ON DELETE RESTRICT,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(from_node_id <> to_node_id),
  CHECK(observed_at >= occurred_at),
  UNIQUE(tenant_id,mission_id,from_node_id,relation_type,to_node_id)
);
CREATE INDEX IF NOT EXISTS idx_experience_graph_edges_mission_time ON experience_graph_edges(tenant_id,mission_id,occurred_at,graph_edge_id);
CREATE INDEX IF NOT EXISTS idx_experience_graph_edges_from ON experience_graph_edges(tenant_id,mission_id,from_node_id);
CREATE INDEX IF NOT EXISTS idx_experience_graph_edges_to ON experience_graph_edges(tenant_id,mission_id,to_node_id);

CREATE OR REPLACE FUNCTION memory_validate_experience_graph_node() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE item_tenant text;
DECLARE item_category text;
DECLARE version_item text;
DECLARE version_hash text;
BEGIN
  IF NEW.memory_item_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT tenant_id,category INTO item_tenant,item_category FROM memory_items WHERE item_id=NEW.memory_item_id;
  IF item_tenant IS NULL THEN
    RAISE EXCEPTION 'experience graph memory item is not visible' USING ERRCODE='23503';
  END IF;
  IF item_tenant <> NEW.tenant_id THEN
    RAISE EXCEPTION 'experience graph memory binding tenant mismatch' USING ERRCODE='42501';
  END IF;

  SELECT item_id,content_sha256 INTO version_item,version_hash FROM memory_versions WHERE version_id=NEW.memory_version_id;
  IF version_item IS NULL OR version_item <> NEW.memory_item_id THEN
    RAISE EXCEPTION 'experience graph memory version does not belong to item' USING ERRCODE='23514';
  END IF;
  IF version_hash <> NEW.memory_content_sha256 THEN
    RAISE EXCEPTION 'experience graph memory hash mismatch' USING ERRCODE='23514';
  END IF;
  IF item_category <> NEW.memory_category_snapshot THEN
    RAISE EXCEPTION 'experience graph memory category snapshot mismatch' USING ERRCODE='23514';
  END IF;

  IF NEW.node_type='HYPOTHESIS' AND item_category<>'HYPOTHESIS' THEN
    RAISE EXCEPTION 'HYPOTHESIS node requires HYPOTHESIS memory' USING ERRCODE='23514';
  ELSIF NEW.node_type='EVIDENCE' AND item_category<>'EVIDENCE' THEN
    RAISE EXCEPTION 'EVIDENCE node requires EVIDENCE memory' USING ERRCODE='23514';
  ELSIF NEW.node_type='DECISION' AND item_category<>'DECISION' THEN
    RAISE EXCEPTION 'DECISION node requires DECISION memory' USING ERRCODE='23514';
  ELSIF NEW.node_type='INTERVENTION' AND item_category<>'INTERVENTION' THEN
    RAISE EXCEPTION 'INTERVENTION node requires INTERVENTION memory' USING ERRCODE='23514';
  ELSIF NEW.node_type='RESULT' AND item_category<>'OUTCOME' THEN
    RAISE EXCEPTION 'RESULT node requires OUTCOME memory' USING ERRCODE='23514';
  ELSIF NEW.node_type='LEARNING' AND item_category<>'LEARNING' THEN
    RAISE EXCEPTION 'LEARNING node requires LEARNING memory' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_validate_experience_graph_edge() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_tenant text;
DECLARE source_mission text;
DECLARE source_type text;
DECLARE source_time timestamptz;
DECLARE target_tenant text;
DECLARE target_mission text;
DECLARE target_type text;
DECLARE target_time timestamptz;
DECLARE creates_cycle boolean;
BEGIN
  SELECT tenant_id,mission_id,node_type,occurred_at INTO source_tenant,source_mission,source_type,source_time
  FROM experience_graph_nodes WHERE node_id=NEW.from_node_id;
  SELECT tenant_id,mission_id,node_type,occurred_at INTO target_tenant,target_mission,target_type,target_time
  FROM experience_graph_nodes WHERE node_id=NEW.to_node_id;

  IF source_tenant IS NULL OR target_tenant IS NULL THEN
    RAISE EXCEPTION 'experience graph edge references missing node' USING ERRCODE='23503';
  END IF;
  IF source_tenant<>target_tenant OR source_mission<>target_mission THEN
    RAISE EXCEPTION 'cross-mission or cross-tenant experience graph edge forbidden' USING ERRCODE='42501';
  END IF;
  IF NEW.tenant_id<>source_tenant OR NEW.mission_id<>source_mission THEN
    RAISE EXCEPTION 'experience graph edge scope mismatch' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS(
    SELECT 1 FROM experience_graph_relation_rules r
    WHERE r.source_type=source_type AND r.relation_type=NEW.relation_type AND r.target_type=target_type
  ) THEN
    RAISE EXCEPTION 'invalid experience graph relation: % % %',source_type,NEW.relation_type,target_type USING ERRCODE='23514';
  END IF;
  IF target_time < source_time THEN
    RAISE EXCEPTION 'experience graph causal target occurs before source' USING ERRCODE='23514';
  END IF;
  IF NEW.occurred_at < target_time THEN
    RAISE EXCEPTION 'experience graph edge occurs before target entity' USING ERRCODE='23514';
  END IF;

  WITH RECURSIVE reach(node_id) AS (
    SELECT e.to_node_id FROM experience_graph_edges e
    WHERE e.tenant_id=NEW.tenant_id AND e.mission_id=NEW.mission_id AND e.from_node_id=NEW.to_node_id
    UNION
    SELECT e.to_node_id FROM experience_graph_edges e JOIN reach r ON e.from_node_id=r.node_id
    WHERE e.tenant_id=NEW.tenant_id AND e.mission_id=NEW.mission_id
  )
  SELECT EXISTS(SELECT 1 FROM reach WHERE node_id=NEW.from_node_id) INTO creates_cycle;
  IF creates_cycle THEN
    RAISE EXCEPTION 'experience graph causal cycle forbidden' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_experience_graph_nodes_set_tenant ON experience_graph_nodes;
CREATE TRIGGER trg_experience_graph_nodes_set_tenant BEFORE INSERT ON experience_graph_nodes
FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();
DROP TRIGGER IF EXISTS trg_experience_graph_nodes_validate ON experience_graph_nodes;
CREATE TRIGGER trg_experience_graph_nodes_validate BEFORE INSERT ON experience_graph_nodes
FOR EACH ROW EXECUTE FUNCTION memory_validate_experience_graph_node();
DROP TRIGGER IF EXISTS trg_experience_graph_nodes_append_only ON experience_graph_nodes;
CREATE TRIGGER trg_experience_graph_nodes_append_only BEFORE UPDATE OR DELETE ON experience_graph_nodes
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_experience_graph_edges_set_tenant ON experience_graph_edges;
CREATE TRIGGER trg_experience_graph_edges_set_tenant BEFORE INSERT ON experience_graph_edges
FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();
DROP TRIGGER IF EXISTS trg_experience_graph_edges_validate ON experience_graph_edges;
CREATE TRIGGER trg_experience_graph_edges_validate BEFORE INSERT ON experience_graph_edges
FOR EACH ROW EXECUTE FUNCTION memory_validate_experience_graph_edge();
DROP TRIGGER IF EXISTS trg_experience_graph_edges_append_only ON experience_graph_edges;
CREATE TRIGGER trg_experience_graph_edges_append_only BEFORE UPDATE OR DELETE ON experience_graph_edges
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_experience_graph_relation_rules_immutable ON experience_graph_relation_rules;
CREATE TRIGGER trg_experience_graph_relation_rules_immutable BEFORE INSERT OR UPDATE OR DELETE ON experience_graph_relation_rules
FOR EACH ROW EXECUTE FUNCTION forbid_ontology_rule_mutation();

ALTER TABLE experience_graph_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE experience_graph_nodes FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON experience_graph_nodes;
CREATE POLICY tenant_isolation ON experience_graph_nodes
USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

ALTER TABLE experience_graph_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE experience_graph_edges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON experience_graph_edges;
CREATE POLICY tenant_isolation ON experience_graph_edges
USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

GRANT SELECT ON experience_graph_relation_rules TO memory_app;
GRANT SELECT,INSERT ON experience_graph_nodes TO memory_app;
GRANT SELECT,INSERT ON experience_graph_edges TO memory_app;

INSERT INTO schema_meta(key,value) VALUES('experience_graph_version','EG-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.16.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
