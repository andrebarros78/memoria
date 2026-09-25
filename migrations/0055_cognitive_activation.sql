-- F02 cognitive activation/priming persistence. Additive and shadow-only.
-- Cognitive state is separated from canonical memory truth; event history is append-only.

CREATE TABLE IF NOT EXISTS memory_activation_state(
  memory_id text PRIMARY KEY REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  tenant_id text NOT NULL,
  base_strength double precision NOT NULL CHECK(base_strength BETWEEN 0 AND 1),
  activation_level double precision NOT NULL CHECK(activation_level BETWEEN 0 AND 1),
  activation_updated_at timestamptz NOT NULL,
  access_count bigint NOT NULL CHECK(access_count >= 0),
  recent_access_weight double precision NOT NULL CHECK(recent_access_weight BETWEEN 0 AND 1),
  priming_weight double precision NOT NULL CHECK(priming_weight BETWEEN 0 AND 1),
  association_activation double precision NOT NULL CHECK(association_activation BETWEEN 0 AND 1),
  goal_activation double precision NOT NULL CHECK(goal_activation BETWEEN 0 AND 1),
  context_activation double precision NOT NULL CHECK(context_activation BETWEEN 0 AND 1),
  interference_penalty double precision NOT NULL CHECK(interference_penalty BETWEEN 0 AND 1),
  habituation_penalty double precision NOT NULL CHECK(habituation_penalty BETWEEN 0 AND 1),
  decay_policy_version text NOT NULL CHECK(length(btrim(decay_policy_version)) BETWEEN 1 AND 80),
  trace_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(trace_jsonb)='object'),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_activation_state_tenant_level
  ON memory_activation_state(tenant_id,activation_level DESC,updated_at DESC);

CREATE TABLE IF NOT EXISTS memory_activation_events(
  event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  event_type text NOT NULL CHECK(event_type IN ('ACTIVATION','DECAY','ACCESS')),
  activation_level double precision NOT NULL CHECK(activation_level BETWEEN 0 AND 1),
  components_jsonb jsonb NOT NULL CHECK(jsonb_typeof(components_jsonb)='object'),
  policy_version text NOT NULL,
  retrieval_trace_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_activation_events_memory
  ON memory_activation_events(tenant_id,memory_id,created_at DESC);

CREATE TABLE IF NOT EXISTS memory_priming_edges(
  edge_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  source_memory_id text REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  target_memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  weight double precision NOT NULL CHECK(weight > 0 AND weight <= 0.20),
  source_trust double precision NOT NULL CHECK(source_trust BETWEEN 0 AND 1),
  evidence_refs_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(evidence_refs_jsonb)='array'),
  retrieval_trace_id text,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  policy_version text NOT NULL DEFAULT 'PRM-1.0.0'
);
CREATE INDEX IF NOT EXISTS idx_memory_priming_edges_target
  ON memory_priming_edges(tenant_id,target_memory_id,valid_until,valid_from DESC);

CREATE TABLE IF NOT EXISTS memory_interference_events(
  interference_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  interference_penalty double precision NOT NULL CHECK(interference_penalty BETWEEN 0 AND 0.25),
  habituation_penalty double precision NOT NULL CHECK(habituation_penalty BETWEEN 0 AND 0.10),
  trace_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(trace_jsonb)='object'),
  retrieval_trace_id text,
  policy_version text NOT NULL DEFAULT 'INT-1.0.0',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_interference_events_memory
  ON memory_interference_events(tenant_id,memory_id,created_at DESC);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'memory_activation_state','memory_activation_events','memory_priming_edges','memory_interference_events'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id))',t);
  END LOOP;
END $$;

DO $$
DECLARE t text; trg text;
BEGIN
  FOREACH t IN ARRAY ARRAY['memory_activation_events','memory_priming_edges','memory_interference_events'] LOOP
    trg:=left('trg_'||t||'_append_only',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,t);
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()',trg,t);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION memory_record_activation_shadow(
  p_event_id text,
  p_memory_id text,
  p_base_strength double precision,
  p_activation_level double precision,
  p_access_count bigint,
  p_recent_access_weight double precision,
  p_priming_weight double precision,
  p_association_activation double precision,
  p_goal_activation double precision,
  p_context_activation double precision,
  p_interference_penalty double precision,
  p_habituation_penalty double precision,
  p_decay_policy_version text,
  p_trace jsonb,
  p_retrieval_trace_id text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_ctx text;
  v_tenant text;
BEGIN
  v_ctx := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_ctx IS NULL THEN
    RAISE EXCEPTION 'runtime tenant context is required' USING ERRCODE='42501';
  END IF;
  IF session_user='memory_app' AND v_ctx='__SYSTEM__' THEN
    RAISE EXCEPTION 'memory_app may not use system tenant for cognitive activation' USING ERRCODE='42501';
  END IF;
  IF p_event_id IS NULL OR p_event_id !~ '^actevt-[0-9a-f]{32}$' THEN
    RAISE EXCEPTION 'invalid activation event id' USING ERRCODE='22023';
  END IF;
  IF p_memory_id IS NULL OR btrim(p_memory_id)='' OR length(p_memory_id)>160 THEN
    RAISE EXCEPTION 'invalid memory id' USING ERRCODE='22023';
  END IF;
  IF p_base_strength NOT BETWEEN 0 AND 1 OR p_activation_level NOT BETWEEN 0 AND 1
     OR p_recent_access_weight NOT BETWEEN 0 AND 1 OR p_priming_weight NOT BETWEEN 0 AND 1
     OR p_association_activation NOT BETWEEN 0 AND 1 OR p_goal_activation NOT BETWEEN 0 AND 1
     OR p_context_activation NOT BETWEEN 0 AND 1 OR p_interference_penalty NOT BETWEEN 0 AND 0.25
     OR p_habituation_penalty NOT BETWEEN 0 AND 0.10 OR p_access_count < 0 THEN
    RAISE EXCEPTION 'activation values out of bounds' USING ERRCODE='22023';
  END IF;
  IF p_trace IS NULL OR jsonb_typeof(p_trace)<>'object' OR octet_length(p_trace::text)>65536 THEN
    RAISE EXCEPTION 'invalid activation trace' USING ERRCODE='22023';
  END IF;

  SELECT tenant_id INTO v_tenant FROM memory_items
   WHERE item_id=p_memory_id AND memory_rls_visible(tenant_id);
  IF v_tenant IS NULL THEN
    RAISE EXCEPTION 'memory not visible in cognitive activation scope' USING ERRCODE='42501';
  END IF;
  IF v_ctx<>'__SYSTEM__' AND v_ctx<>v_tenant THEN
    RAISE EXCEPTION 'cognitive activation tenant mismatch' USING ERRCODE='42501';
  END IF;

  INSERT INTO memory_activation_state(
    memory_id,tenant_id,base_strength,activation_level,activation_updated_at,access_count,
    recent_access_weight,priming_weight,association_activation,goal_activation,context_activation,
    interference_penalty,habituation_penalty,decay_policy_version,trace_jsonb,updated_at
  ) VALUES(
    p_memory_id,v_tenant,p_base_strength,p_activation_level,now(),p_access_count,
    p_recent_access_weight,p_priming_weight,p_association_activation,p_goal_activation,p_context_activation,
    p_interference_penalty,p_habituation_penalty,p_decay_policy_version,p_trace,now()
  )
  ON CONFLICT(memory_id) DO UPDATE SET
    base_strength=EXCLUDED.base_strength,
    activation_level=EXCLUDED.activation_level,
    activation_updated_at=EXCLUDED.activation_updated_at,
    access_count=GREATEST(memory_activation_state.access_count,EXCLUDED.access_count),
    recent_access_weight=EXCLUDED.recent_access_weight,
    priming_weight=EXCLUDED.priming_weight,
    association_activation=EXCLUDED.association_activation,
    goal_activation=EXCLUDED.goal_activation,
    context_activation=EXCLUDED.context_activation,
    interference_penalty=EXCLUDED.interference_penalty,
    habituation_penalty=EXCLUDED.habituation_penalty,
    decay_policy_version=EXCLUDED.decay_policy_version,
    trace_jsonb=EXCLUDED.trace_jsonb,
    updated_at=now();

  INSERT INTO memory_activation_events(
    event_id,tenant_id,memory_id,event_type,activation_level,components_jsonb,
    policy_version,retrieval_trace_id
  ) VALUES(
    p_event_id,v_tenant,p_memory_id,'ACTIVATION',p_activation_level,
    COALESCE(p_trace->'components','{}'::jsonb),p_decay_policy_version,p_retrieval_trace_id
  );

  IF p_interference_penalty>0 OR p_habituation_penalty>0 THEN
    INSERT INTO memory_interference_events(
      interference_id,tenant_id,memory_id,interference_penalty,habituation_penalty,
      trace_jsonb,retrieval_trace_id
    ) VALUES(
      'intevt-'||substr(p_event_id,8),v_tenant,p_memory_id,p_interference_penalty,
      p_habituation_penalty,p_trace,p_retrieval_trace_id
    );
  END IF;
END;
$$;
ALTER FUNCTION memory_record_activation_shadow(text,text,double precision,double precision,bigint,double precision,double precision,double precision,double precision,double precision,double precision,double precision,text,jsonb,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_record_activation_shadow(text,text,double precision,double precision,bigint,double precision,double precision,double precision,double precision,double precision,double precision,double precision,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_record_activation_shadow(text,text,double precision,double precision,bigint,double precision,double precision,double precision,double precision,double precision,double precision,double precision,text,jsonb,text) TO memory_app;

CREATE OR REPLACE FUNCTION memory_record_priming_shadow(
  p_edge_id text,
  p_target_memory_id text,
  p_source_memory_id text,
  p_weight double precision,
  p_source_trust double precision,
  p_evidence_refs jsonb,
  p_retrieval_trace_id text,
  p_ttl_seconds integer
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_ctx text;
  v_target_tenant text;
  v_source_tenant text;
BEGIN
  v_ctx := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_ctx IS NULL OR (session_user='memory_app' AND v_ctx='__SYSTEM__') THEN
    RAISE EXCEPTION 'runtime tenant context is required for priming' USING ERRCODE='42501';
  END IF;
  IF p_edge_id IS NULL OR p_edge_id !~ '^prime-[0-9a-f]{32}$' OR p_weight<=0 OR p_weight>0.20
     OR p_source_trust<0 OR p_source_trust>1 OR p_ttl_seconds<1 OR p_ttl_seconds>86400 THEN
    RAISE EXCEPTION 'invalid priming request' USING ERRCODE='22023';
  END IF;
  IF p_evidence_refs IS NULL OR jsonb_typeof(p_evidence_refs)<>'array' OR jsonb_array_length(p_evidence_refs)>64
     OR octet_length(p_evidence_refs::text)>32768 THEN
    RAISE EXCEPTION 'invalid priming evidence' USING ERRCODE='22023';
  END IF;

  SELECT tenant_id INTO v_target_tenant FROM memory_items
   WHERE item_id=p_target_memory_id AND memory_rls_visible(tenant_id);
  IF v_target_tenant IS NULL OR (v_ctx<>'__SYSTEM__' AND v_ctx<>v_target_tenant) THEN
    RAISE EXCEPTION 'target memory not visible in priming scope' USING ERRCODE='42501';
  END IF;
  IF p_source_memory_id IS NOT NULL THEN
    SELECT tenant_id INTO v_source_tenant FROM memory_items
     WHERE item_id=p_source_memory_id AND memory_rls_visible(tenant_id);
    IF v_source_tenant IS NULL OR v_source_tenant<>v_target_tenant THEN
      RAISE EXCEPTION 'cross-tenant priming is forbidden' USING ERRCODE='42501';
    END IF;
  END IF;

  INSERT INTO memory_priming_edges(
    edge_id,tenant_id,source_memory_id,target_memory_id,weight,source_trust,
    evidence_refs_jsonb,retrieval_trace_id,valid_until
  ) VALUES(
    p_edge_id,v_target_tenant,p_source_memory_id,p_target_memory_id,p_weight,p_source_trust,
    p_evidence_refs,p_retrieval_trace_id,now()+make_interval(secs=>p_ttl_seconds)
  );
END;
$$;
ALTER FUNCTION memory_record_priming_shadow(text,text,text,double precision,double precision,jsonb,text,integer) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_record_priming_shadow(text,text,text,double precision,double precision,jsonb,text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_record_priming_shadow(text,text,text,double precision,double precision,jsonb,text,integer) TO memory_app;

GRANT SELECT,INSERT,UPDATE ON memory_activation_state TO memory_admin;
GRANT SELECT,INSERT ON memory_activation_events,memory_priming_edges,memory_interference_events TO memory_admin;
GRANT SELECT ON memory_activation_state,memory_activation_events,memory_priming_edges,memory_interference_events TO memory_app;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON memory_activation_state,memory_activation_events,memory_priming_edges,memory_interference_events FROM memory_app;

INSERT INTO schema_meta(key,value) VALUES
('cognitive_activation_contract_version','ACT-1.0.0'),
('cognitive_priming_contract_version','PRM-1.0.0'),
('cognitive_activation_mode','SHADOW'),
('gate_c1_status','PENDING')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
