-- Fix PL/pgSQL variable ambiguity found by MEMORIA PLUS P08 end-to-end proof.

CREATE OR REPLACE FUNCTION memory_validate_experience_graph_edge() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_source_tenant text;
DECLARE v_source_mission text;
DECLARE v_source_type text;
DECLARE v_source_time timestamptz;
DECLARE v_target_tenant text;
DECLARE v_target_mission text;
DECLARE v_target_type text;
DECLARE v_target_time timestamptz;
DECLARE v_creates_cycle boolean;
BEGIN
  SELECT n.tenant_id,n.mission_id,n.node_type,n.occurred_at
  INTO v_source_tenant,v_source_mission,v_source_type,v_source_time
  FROM experience_graph_nodes n WHERE n.node_id=NEW.from_node_id;

  SELECT n.tenant_id,n.mission_id,n.node_type,n.occurred_at
  INTO v_target_tenant,v_target_mission,v_target_type,v_target_time
  FROM experience_graph_nodes n WHERE n.node_id=NEW.to_node_id;

  IF v_source_tenant IS NULL OR v_target_tenant IS NULL THEN
    RAISE EXCEPTION 'experience graph edge references missing node' USING ERRCODE='23503';
  END IF;
  IF v_source_tenant<>v_target_tenant OR v_source_mission<>v_target_mission THEN
    RAISE EXCEPTION 'cross-mission or cross-tenant experience graph edge forbidden' USING ERRCODE='42501';
  END IF;
  IF NEW.tenant_id<>v_source_tenant OR NEW.mission_id<>v_source_mission THEN
    RAISE EXCEPTION 'experience graph edge scope mismatch' USING ERRCODE='42501';
  END IF;
  IF NOT EXISTS(
    SELECT 1 FROM experience_graph_relation_rules r
    WHERE r.source_type=v_source_type AND r.relation_type=NEW.relation_type AND r.target_type=v_target_type
  ) THEN
    RAISE EXCEPTION 'invalid experience graph relation: % % %',v_source_type,NEW.relation_type,v_target_type USING ERRCODE='23514';
  END IF;
  IF v_target_time < v_source_time THEN
    RAISE EXCEPTION 'experience graph causal target occurs before source' USING ERRCODE='23514';
  END IF;
  IF NEW.occurred_at < v_target_time THEN
    RAISE EXCEPTION 'experience graph edge occurs before target entity' USING ERRCODE='23514';
  END IF;

  WITH RECURSIVE reach(node_id) AS (
    SELECT e.to_node_id FROM experience_graph_edges e
    WHERE e.tenant_id=NEW.tenant_id AND e.mission_id=NEW.mission_id AND e.from_node_id=NEW.to_node_id
    UNION
    SELECT e.to_node_id FROM experience_graph_edges e JOIN reach r ON e.from_node_id=r.node_id
    WHERE e.tenant_id=NEW.tenant_id AND e.mission_id=NEW.mission_id
  )
  SELECT EXISTS(SELECT 1 FROM reach WHERE node_id=NEW.from_node_id) INTO v_creates_cycle;
  IF v_creates_cycle THEN
    RAISE EXCEPTION 'experience graph causal cycle forbidden' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.16.1')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
