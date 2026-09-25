-- F03 Associative Memory / Spreading Activation shadow persistence.
-- Inferred associations never become canonical memory truth in this phase.

CREATE TABLE IF NOT EXISTS memory_association_traversals(
  traversal_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  retrieval_trace_id text,
  seed_memory_ids text[] NOT NULL,
  candidate_count integer NOT NULL CHECK(candidate_count BETWEEN 0 AND 128),
  visited_count integer NOT NULL CHECK(visited_count BETWEEN 1 AND 272),
  max_depth integer NOT NULL CHECK(max_depth BETWEEN 1 AND 4),
  node_budget integer NOT NULL CHECK(node_budget BETWEEN 1 AND 256),
  time_budget_ms integer NOT NULL CHECK(time_budget_ms BETWEEN 1 AND 1000),
  elapsed_ms double precision NOT NULL CHECK(elapsed_ms >= 0.0),
  policy_version text NOT NULL CHECK(length(btrim(policy_version)) BETWEEN 1 AND 80),
  deterministic_trace jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(cardinality(seed_memory_ids) BETWEEN 1 AND 16)
);

CREATE INDEX IF NOT EXISTS idx_memory_association_traversals_tenant_created
ON memory_association_traversals(tenant_id,created_at DESC,traversal_id);

CREATE INDEX IF NOT EXISTS idx_memory_association_traversals_trace
ON memory_association_traversals(tenant_id,retrieval_trace_id)
WHERE retrieval_trace_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS memory_association_candidates(
  association_candidate_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  traversal_id text NOT NULL REFERENCES memory_association_traversals(traversal_id) ON DELETE RESTRICT,
  seed_memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  relation_type text NOT NULL CHECK(relation_type IN (
    'SEMANTIC_SIMILARITY','TEMPORAL_PROXIMITY','CAUSAL_RELATION','SHARED_ENTITY','SHARED_PERSON',
    'SHARED_OBJECTIVE','SHARED_CONTEXT','SHARED_OUTCOME','CO_OCCURRENCE','PROCEDURAL_DEPENDENCY',
    'DECISION_DEPENDENCY','CONTRADICTION','SUPPORT'
  )),
  activation_score double precision NOT NULL CHECK(activation_score BETWEEN 0.0 AND 1.0),
  hop_depth integer NOT NULL CHECK(hop_depth BETWEEN 1 AND 4),
  path_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence_strength double precision NOT NULL CHECK(evidence_strength BETWEEN 0.0 AND 1.0),
  evidence_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_kind text NOT NULL CHECK(length(btrim(source_kind)) BETWEEN 1 AND 80),
  source_ref text NOT NULL CHECK(length(btrim(source_ref)) BETWEEN 1 AND 512),
  conflict boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(seed_memory_id <> memory_id),
  CHECK(jsonb_typeof(path_jsonb)='array'),
  CHECK(jsonb_array_length(path_jsonb) BETWEEN 2 AND 5)
);

CREATE INDEX IF NOT EXISTS idx_memory_association_candidates_target
ON memory_association_candidates(tenant_id,memory_id,activation_score DESC,created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_association_candidates_traversal
ON memory_association_candidates(tenant_id,traversal_id,activation_score DESC,hop_depth,memory_id);

ALTER TABLE memory_association_traversals ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_association_traversals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON memory_association_traversals;
CREATE POLICY tenant_isolation ON memory_association_traversals
USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

ALTER TABLE memory_association_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_association_candidates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON memory_association_candidates;
CREATE POLICY tenant_isolation ON memory_association_candidates
USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

DROP TRIGGER IF EXISTS trg_memory_association_traversals_append_only ON memory_association_traversals;
CREATE TRIGGER trg_memory_association_traversals_append_only
BEFORE UPDATE OR DELETE ON memory_association_traversals
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_memory_association_candidates_append_only ON memory_association_candidates;
CREATE TRIGGER trg_memory_association_candidates_append_only
BEFORE UPDATE OR DELETE ON memory_association_candidates
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

CREATE OR REPLACE FUNCTION memory_record_association_traversal_shadow(
  p_traversal_id text,
  p_retrieval_trace_id text,
  p_seed_memory_ids text[],
  p_candidates jsonb,
  p_deterministic_trace jsonb,
  p_policy_version text,
  p_max_depth integer,
  p_node_budget integer,
  p_time_budget_ms integer,
  p_elapsed_ms double precision,
  p_project_id text,
  p_mission_id text,
  p_session_id text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public
AS $$
DECLARE
  v_ctx text;
  v_tenant text;
  v_seed text;
  v_candidate jsonb;
  v_memory_id text;
  v_seed_id text;
  v_relation text;
  v_score double precision;
  v_hop integer;
  v_evidence_strength double precision;
  v_source_kind text;
  v_source_ref text;
  v_conflict boolean;
  v_path jsonb;
  v_candidate_tenant text;
  v_inserted integer := 0;
  v_candidate_count integer;
BEGIN
  v_ctx := NULLIF(current_setting('app.current_tenant',true),'');
  IF v_ctx IS NULL THEN
    RAISE EXCEPTION 'runtime tenant context is required for association traversal' USING ERRCODE='42501';
  END IF;
  IF v_ctx='__SYSTEM__' AND current_user='memory_app' THEN
    RAISE EXCEPTION 'memory_app may not use system tenant for association traversal' USING ERRCODE='42501';
  END IF;
  IF p_traversal_id IS NULL OR btrim(p_traversal_id)='' OR length(p_traversal_id)>160 THEN
    RAISE EXCEPTION 'invalid association traversal id' USING ERRCODE='22023';
  END IF;
  IF p_policy_version IS NULL OR btrim(p_policy_version)='' OR length(p_policy_version)>80 THEN
    RAISE EXCEPTION 'invalid association policy version' USING ERRCODE='22023';
  END IF;
  IF cardinality(p_seed_memory_ids) IS NULL OR cardinality(p_seed_memory_ids) NOT BETWEEN 1 AND 16 THEN
    RAISE EXCEPTION 'association seed count out of bounds' USING ERRCODE='22023';
  END IF;
  IF jsonb_typeof(COALESCE(p_candidates,'[]'::jsonb)) <> 'array' THEN
    RAISE EXCEPTION 'association candidates must be an array' USING ERRCODE='22023';
  END IF;
  v_candidate_count := jsonb_array_length(COALESCE(p_candidates,'[]'::jsonb));
  IF v_candidate_count > 128 THEN
    RAISE EXCEPTION 'association candidate count out of bounds' USING ERRCODE='22023';
  END IF;
  IF p_max_depth NOT BETWEEN 1 AND 4 OR p_node_budget NOT BETWEEN 1 AND 256 OR p_time_budget_ms NOT BETWEEN 1 AND 1000 OR p_elapsed_ms < 0 THEN
    RAISE EXCEPTION 'association traversal limits out of bounds' USING ERRCODE='22023';
  END IF;

  FOREACH v_seed IN ARRAY p_seed_memory_ids LOOP
    SELECT m.tenant_id INTO v_tenant
    FROM memory_items m
    WHERE m.item_id=v_seed
      AND memory_rls_visible(m.tenant_id)
      AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,COALESCE(p_project_id,''),COALESCE(p_mission_id,''),COALESCE(p_session_id,''));
    IF v_tenant IS NULL THEN
      RAISE EXCEPTION 'association seed memory not visible in scope' USING ERRCODE='42501';
    END IF;
    IF v_ctx<>'__SYSTEM__' AND v_ctx<>v_tenant THEN
      RAISE EXCEPTION 'association seed tenant mismatch' USING ERRCODE='42501';
    END IF;
  END LOOP;

  INSERT INTO memory_association_traversals(
    traversal_id,tenant_id,retrieval_trace_id,seed_memory_ids,candidate_count,visited_count,
    max_depth,node_budget,time_budget_ms,elapsed_ms,policy_version,deterministic_trace
  ) VALUES(
    p_traversal_id,v_tenant,NULLIF(p_retrieval_trace_id,''),p_seed_memory_ids,v_candidate_count,
    GREATEST(cardinality(p_seed_memory_ids),LEAST(272,COALESCE((p_deterministic_trace->>'visited_count')::integer,cardinality(p_seed_memory_ids)))),
    p_max_depth,p_node_budget,p_time_budget_ms,p_elapsed_ms,p_policy_version,COALESCE(p_deterministic_trace,'{}'::jsonb)
  );

  FOR v_candidate IN SELECT value FROM jsonb_array_elements(COALESCE(p_candidates,'[]'::jsonb)) LOOP
    v_memory_id := NULLIF(btrim(v_candidate->>'memory_id'),'');
    v_seed_id := NULLIF(btrim(v_candidate->>'seed_memory_id'),'');
    v_relation := NULLIF(btrim(v_candidate->>'relation_type'),'');
    v_score := COALESCE((v_candidate->>'activation_score')::double precision,-1.0);
    v_hop := COALESCE((v_candidate->>'hop_depth')::integer,0);
    v_evidence_strength := COALESCE((v_candidate->>'evidence_strength')::double precision,-1.0);
    v_source_kind := NULLIF(btrim(v_candidate->>'source_kind'),'');
    v_source_ref := NULLIF(btrim(v_candidate->>'source_ref'),'');
    v_conflict := COALESCE((v_candidate->>'conflict')::boolean,false);
    v_path := COALESCE(v_candidate->'path','[]'::jsonb);

    IF v_memory_id IS NULL OR v_seed_id IS NULL OR v_memory_id=v_seed_id THEN
      RAISE EXCEPTION 'invalid association candidate endpoint' USING ERRCODE='22023';
    END IF;
    IF NOT (v_seed_id=ANY(p_seed_memory_ids)) THEN
      RAISE EXCEPTION 'association candidate references non-seed origin' USING ERRCODE='22023';
    END IF;
    IF v_relation NOT IN (
      'SEMANTIC_SIMILARITY','TEMPORAL_PROXIMITY','CAUSAL_RELATION','SHARED_ENTITY','SHARED_PERSON',
      'SHARED_OBJECTIVE','SHARED_CONTEXT','SHARED_OUTCOME','CO_OCCURRENCE','PROCEDURAL_DEPENDENCY',
      'DECISION_DEPENDENCY','CONTRADICTION','SUPPORT'
    ) THEN
      RAISE EXCEPTION 'invalid association relation type' USING ERRCODE='22023';
    END IF;
    IF v_score NOT BETWEEN 0.0 AND 1.0 OR v_hop NOT BETWEEN 1 AND p_max_depth OR v_evidence_strength NOT BETWEEN 0.0 AND 1.0 THEN
      RAISE EXCEPTION 'association candidate score/depth out of bounds' USING ERRCODE='22023';
    END IF;
    IF v_source_kind IS NULL OR length(v_source_kind)>80 OR v_source_ref IS NULL OR length(v_source_ref)>512 THEN
      RAISE EXCEPTION 'invalid association candidate source' USING ERRCODE='22023';
    END IF;
    IF jsonb_typeof(v_path)<>'array' OR jsonb_array_length(v_path) NOT BETWEEN 2 AND 5 THEN
      RAISE EXCEPTION 'invalid association candidate path' USING ERRCODE='22023';
    END IF;

    SELECT m.tenant_id INTO v_candidate_tenant
    FROM memory_items m
    WHERE m.item_id=v_memory_id
      AND memory_rls_visible(m.tenant_id)
      AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,COALESCE(p_project_id,''),COALESCE(p_mission_id,''),COALESCE(p_session_id,''));
    IF v_candidate_tenant IS NULL OR v_candidate_tenant<>v_tenant THEN
      RAISE EXCEPTION 'association candidate outside traversal scope' USING ERRCODE='42501';
    END IF;

    INSERT INTO memory_association_candidates(
      association_candidate_id,tenant_id,traversal_id,seed_memory_id,memory_id,relation_type,
      activation_score,hop_depth,path_jsonb,evidence_strength,evidence_jsonb,source_kind,source_ref,conflict
    ) VALUES(
      'asc-'||substr(md5(p_traversal_id||':'||v_seed_id||':'||v_memory_id||':'||v_relation||':'||v_source_ref),1,32),
      v_tenant,p_traversal_id,v_seed_id,v_memory_id,v_relation,v_score,v_hop,v_path,v_evidence_strength,
      COALESCE(v_candidate->'evidence','{}'::jsonb),v_source_kind,v_source_ref,v_conflict
    );
    v_inserted := v_inserted + 1;
  END LOOP;

  IF v_inserted<>v_candidate_count THEN
    RAISE EXCEPTION 'association candidate persistence count mismatch';
  END IF;
  RETURN p_traversal_id;
END;
$$;

REVOKE ALL ON FUNCTION memory_record_association_traversal_shadow(text,text,text[],jsonb,jsonb,text,integer,integer,integer,double precision,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_record_association_traversal_shadow(text,text,text[],jsonb,jsonb,text,integer,integer,integer,double precision,text,text,text) TO memory_app;

GRANT SELECT,INSERT ON memory_association_traversals,memory_association_candidates TO memory_admin;
GRANT SELECT ON memory_association_traversals,memory_association_candidates TO memory_app;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON memory_association_traversals,memory_association_candidates FROM memory_app;

INSERT INTO schema_meta(key,value) VALUES('cognitive_association_version','ASP-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
