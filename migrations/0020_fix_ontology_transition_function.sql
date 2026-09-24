-- P07 correction after live proof: remove PL/pgSQL name ambiguity in transition rule lookup.

CREATE OR REPLACE FUNCTION memory_apply_ontology_transition(
  p_transition_id text,p_item_id text,p_to_category text,p_actor text,p_reason text,p_evidence jsonb
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE v_from_category text; DECLARE v_item_tenant text; DECLARE v_current_version text;
BEGIN
  SELECT m.category,m.tenant_id INTO v_from_category,v_item_tenant FROM memory_items m WHERE m.item_id=p_item_id FOR UPDATE;
  IF v_from_category IS NULL THEN RAISE EXCEPTION 'memory not found for ontology transition'; END IF;
  IF NOT EXISTS(
    SELECT 1 FROM ontology_transition_rules r
    WHERE r.from_category=v_from_category AND r.to_category=p_to_category
  ) THEN
    RAISE EXCEPTION 'invalid ontology transition: % -> %',v_from_category,p_to_category USING ERRCODE='23514';
  END IF;
  SELECT v.version_id INTO v_current_version FROM memory_versions v WHERE v.item_id=p_item_id ORDER BY v.version_no DESC LIMIT 1;
  PERFORM set_config('app.ontology_transition_authorized','1',true);
  UPDATE memory_items SET category=p_to_category,validation_status='UNVALIDATED',governor_eligible=false WHERE item_id=p_item_id;
  PERFORM set_config('app.ontology_transition_authorized','0',true);
  INSERT INTO memory_ontology_transitions(transition_id,tenant_id,item_id,version_id,from_category,to_category,actor_id,reason,evidence)
  VALUES(p_transition_id,v_item_tenant,p_item_id,v_current_version,v_from_category,p_to_category,p_actor,p_reason,COALESCE(p_evidence,'{}'::jsonb));
  PERFORM set_config('app.ontology_relation_state_authorized','1',true);
  UPDATE memory_knowledge_relations
  SET status='STALE',staled_at=COALESCE(staled_at,now()),stale_reason='ONTOLOGY_CATEGORY_TRANSITION'
  WHERE status='ACTIVE' AND (from_item_id=p_item_id OR to_item_id=p_item_id);
  PERFORM set_config('app.ontology_relation_state_authorized','0',true);
  UPDATE memory_derived_artifacts a SET status='STALE',updated_at=now(),staled_at=COALESCE(staled_at,now()),
      invalidation_reason='SOURCE_ONTOLOGY_TRANSITION',stale_source_version_id=v_current_version
  WHERE a.status='READY' AND EXISTS(SELECT 1 FROM memory_artifact_dependencies d WHERE d.artifact_id=a.artifact_id AND d.source_item_id=p_item_id);
  RETURN p_transition_id;
END;
$$;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.15.2')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
