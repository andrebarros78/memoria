-- F04 Offline Cognitive Consolidation. Background-only, SHADOW and recoverable.
-- The worker may write derived control/evidence state only; canonical memory truth is immutable here.

CREATE TABLE IF NOT EXISTS cognitive_consolidation_runs(
  run_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  scope_key text NOT NULL CHECK(length(btrim(scope_key)) BETWEEN 1 AND 512),
  project_id text,
  mission_id text,
  session_id text,
  mode text NOT NULL CHECK(mode IN (
    'MICRO_CONSOLIDATION','IDLE_CONSOLIDATION','DAILY_CONSOLIDATION',
    'DEEP_CONSOLIDATION','MANUAL_CONSOLIDATION','RECOVERY_CONSOLIDATION'
  )),
  trigger_kind text NOT NULL CHECK(trigger_kind IN (
    'IDLE','TIME_WINDOW','EVENT_THRESHOLD','MEMORY_PRESSURE','MANUAL','RECOVERY'
  )),
  status text NOT NULL CHECK(status IN ('RUNNING','RECOVERING','COMPLETED','FAILED')),
  lease_key text NOT NULL CHECK(length(btrim(lease_key)) BETWEEN 1 AND 240),
  fencing_token bigint NOT NULL CHECK(fencing_token > 0),
  source_count integer NOT NULL DEFAULT 0 CHECK(source_count BETWEEN 0 AND 512),
  candidate_count integer NOT NULL DEFAULT 0 CHECK(candidate_count BETWEEN 0 AND 128),
  validated_candidate_count integer NOT NULL DEFAULT 0 CHECK(validated_candidate_count BETWEEN 0 AND 128),
  replay_digest text CHECK(replay_digest IS NULL OR replay_digest ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL CHECK(length(btrim(policy_version)) BETWEEN 1 AND 80),
  checkpoint_sequence integer NOT NULL DEFAULT 0 CHECK(checkpoint_sequence BETWEEN 0 AND 64),
  recovered_from_interrupt boolean NOT NULL DEFAULT false,
  failure_type text,
  started_at timestamptz NOT NULL DEFAULT now(),
  heartbeat_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CHECK(project_id IS NULL OR length(project_id) <= 128),
  CHECK(mission_id IS NULL OR length(mission_id) <= 128),
  CHECK(session_id IS NULL OR length(session_id) <= 128)
);
CREATE INDEX IF NOT EXISTS idx_cognitive_consolidation_runs_scope
  ON cognitive_consolidation_runs(tenant_id,scope_key,status,started_at DESC,run_id);
CREATE INDEX IF NOT EXISTS idx_cognitive_consolidation_runs_heartbeat
  ON cognitive_consolidation_runs(tenant_id,status,heartbeat_at);

CREATE TABLE IF NOT EXISTS cognitive_consolidation_checkpoints(
  checkpoint_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  run_id text NOT NULL REFERENCES cognitive_consolidation_runs(run_id) ON DELETE RESTRICT,
  sequence_no integer NOT NULL CHECK(sequence_no BETWEEN 1 AND 64),
  stage text NOT NULL CHECK(stage IN (
    'SELECT','REPLAY','COMPARE','CLUSTER','ASSOCIATE','DETECT_PATTERN',
    'GENERATE_CANDIDATE','VALIDATE','CONSOLIDATE','RECORD_PROVENANCE'
  )),
  state_jsonb jsonb NOT NULL CHECK(jsonb_typeof(state_jsonb)='object'),
  state_sha256 text NOT NULL CHECK(state_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(run_id,sequence_no)
);
CREATE INDEX IF NOT EXISTS idx_cognitive_consolidation_checkpoints_run
  ON cognitive_consolidation_checkpoints(tenant_id,run_id,sequence_no,created_at);

CREATE TABLE IF NOT EXISTS cognitive_consolidation_candidates(
  candidate_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  run_id text NOT NULL REFERENCES cognitive_consolidation_runs(run_id) ON DELETE RESTRICT,
  candidate_kind text NOT NULL CHECK(candidate_kind IN (
    'REPEATED_PATTERN','HIGH_SALIENCE_CLUSTER','OUTCOME_CLUSTER','ASSOCIATION_CLUSTER','CONFLICT_CLUSTER'
  )),
  source_memory_ids text[] NOT NULL,
  sample_count integer NOT NULL CHECK(sample_count BETWEEN 2 AND 64),
  status text NOT NULL CHECK(status IN ('CANDIDATE','VALIDATED_SHADOW','REJECTED')),
  confidence double precision NOT NULL CHECK(confidence BETWEEN 0.0 AND 1.0),
  conflict boolean NOT NULL DEFAULT false,
  proof_jsonb jsonb NOT NULL CHECK(jsonb_typeof(proof_jsonb)='object'),
  candidate_digest text NOT NULL CHECK(candidate_digest ~ '^[0-9a-f]{64}$'),
  validation_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(validation_jsonb)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(cardinality(source_memory_ids)=sample_count)
);
CREATE INDEX IF NOT EXISTS idx_cognitive_consolidation_candidates_run
  ON cognitive_consolidation_candidates(tenant_id,run_id,status,confidence DESC,candidate_id);

CREATE TABLE IF NOT EXISTS cognitive_consolidation_events(
  event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  run_id text NOT NULL REFERENCES cognitive_consolidation_runs(run_id) ON DELETE RESTRICT,
  event_type text NOT NULL CHECK(event_type IN (
    'STARTED','RESUMED','CHECKPOINTED','CANDIDATE_CREATED','FINISHED','FAILED'
  )),
  payload_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(payload_jsonb)='object'),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cognitive_consolidation_events_run
  ON cognitive_consolidation_events(tenant_id,run_id,created_at,event_id);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'cognitive_consolidation_runs','cognitive_consolidation_checkpoints',
    'cognitive_consolidation_candidates','cognitive_consolidation_events'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id))',t
    );
  END LOOP;
END $$;

DO $$
DECLARE t text; trg text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'cognitive_consolidation_checkpoints','cognitive_consolidation_candidates','cognitive_consolidation_events'
  ] LOOP
    trg:=left('trg_'||t||'_append_only',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,t);
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()',trg,t
    );
  END LOOP;
END $$;

GRANT SELECT ON agent_leases TO memory_admin;

GRANT SELECT ON memory_items,memory_operator_state,memory_outcomes,memory_knowledge_relations,
  memory_activation_state,memory_salience,memory_association_candidates TO memory_admin;

CREATE OR REPLACE FUNCTION memory_consolidation_source_snapshot(
  p_memory_ids text[],
  p_limit integer,
  p_project_id text,
  p_mission_id text,
  p_session_id text
) RETURNS TABLE(
  item_id text,
  namespace text,
  category text,
  content_sha256 text,
  confidence double precision,
  salience double precision,
  activation double precision,
  outcome_signal double precision,
  association_signal double precision,
  conflict boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_ctx text;
  v_agent text;
  v_limit integer;
BEGIN
  v_ctx:=NULLIF(current_setting('app.current_tenant',true),'');
  v_agent:=NULLIF(current_setting('app.current_agent',true),'');
  IF v_ctx IS NULL OR v_agent IS NULL OR v_agent='__SYSTEM__' OR (session_user='memory_app' AND v_ctx='__SYSTEM__') THEN
    RAISE EXCEPTION 'dedicated tenant/agent context required for consolidation source snapshot' USING ERRCODE='42501';
  END IF;
  v_limit:=LEAST(GREATEST(COALESCE(p_limit,64),2),512);
  IF p_memory_ids IS NOT NULL AND cardinality(p_memory_ids)>512 THEN
    RAISE EXCEPTION 'consolidation source request exceeds bound' USING ERRCODE='22023';
  END IF;
  RETURN QUERY
  WITH latest_salience AS (
    SELECT DISTINCT ON (s.memory_id) s.memory_id,s.score
    FROM memory_salience s
    WHERE s.tenant_id=v_ctx
    ORDER BY s.memory_id,s.computed_at DESC,s.salience_id DESC
  ),
  outcome_signal AS (
    SELECT o.item_id,LEAST(1.0,count(*)::double precision/3.0) AS score
    FROM memory_outcomes o WHERE o.tenant_id=v_ctx GROUP BY o.item_id
  ),
  association_signal AS (
    SELECT a.memory_id,LEAST(1.0,count(*)::double precision/4.0) AS score
    FROM memory_association_candidates a WHERE a.tenant_id=v_ctx GROUP BY a.memory_id
  ),
  conflict_signal AS (
    SELECT r.from_item_id AS conflict_item_id
    FROM memory_knowledge_relations r WHERE r.tenant_id=v_ctx AND r.status='ACTIVE' AND r.relation_type='REFUTES'
    UNION
    SELECT r.to_item_id AS conflict_item_id
    FROM memory_knowledge_relations r WHERE r.tenant_id=v_ctx AND r.status='ACTIVE' AND r.relation_type='REFUTES'
  ),
  ranked AS (
    SELECT m.item_id,m.namespace,m.category,m.content_sha256,m.confidence,
           COALESCE(sal.score,0.0)::double precision AS salience,
           COALESCE(act.activation_level,0.0)::double precision AS activation,
           COALESCE(outc.score,0.0)::double precision AS outcome_signal,
           COALESCE(assoc.score,0.0)::double precision AS association_signal,
           (conf.conflict_item_id IS NOT NULL) AS conflict,
           (m.confidence*0.35 + COALESCE(sal.score,0.0)*0.25 +
            COALESCE(act.activation_level,0.0)*0.15 + COALESCE(outc.score,0.0)*0.15 +
            COALESCE(assoc.score,0.0)*0.10) AS source_rank
    FROM memory_items m
    JOIN memory_operator_state op ON op.item_id=m.item_id
    LEFT JOIN latest_salience sal ON sal.memory_id=m.item_id
    LEFT JOIN memory_activation_state act ON act.memory_id=m.item_id AND act.tenant_id=v_ctx
    LEFT JOIN outcome_signal outc ON outc.item_id=m.item_id
    LEFT JOIN association_signal assoc ON assoc.memory_id=m.item_id
    LEFT JOIN conflict_signal conf ON conf.conflict_item_id=m.item_id
    WHERE m.tenant_id=v_ctx
      AND (p_memory_ids IS NULL OR m.item_id=ANY(p_memory_ids))
      AND op.lifecycle_state NOT IN ('PURGED','QUARANTINED')
      AND memory_scope_matches_context(
        m.memory_scope,m.memory_scope_ref,COALESCE(p_project_id,''),COALESCE(p_mission_id,''),COALESCE(p_session_id,'')
      )
  )
  SELECT r.item_id,r.namespace,r.category,r.content_sha256,r.confidence,
         r.salience,r.activation,r.outcome_signal,r.association_signal,r.conflict
  FROM ranked r
  ORDER BY
    CASE WHEN p_memory_ids IS NULL THEN 0 ELSE COALESCE(array_position(p_memory_ids,r.item_id),2147483647) END,
    CASE WHEN p_memory_ids IS NULL THEN r.source_rank ELSE 0.0 END DESC,
    r.item_id
  LIMIT v_limit;
END;
$$;
ALTER FUNCTION memory_consolidation_source_snapshot(text[],integer,text,text,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_consolidation_source_snapshot(text[],integer,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_consolidation_source_snapshot(text[],integer,text,text,text) TO memory_app;

CREATE OR REPLACE FUNCTION memory_consolidation_assert_lease(
  p_tenant_id text,
  p_lease_key text,
  p_fencing_token bigint
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_ctx text;
  v_agent text;
  v_ok boolean;
BEGIN
  v_ctx:=NULLIF(current_setting('app.current_tenant',true),'');
  v_agent:=NULLIF(current_setting('app.current_agent',true),'');
  IF v_ctx IS NULL OR v_agent IS NULL OR v_agent='__SYSTEM__' THEN
    RAISE EXCEPTION 'dedicated tenant/agent context required for consolidation' USING ERRCODE='42501';
  END IF;
  IF session_user='memory_app' AND v_ctx='__SYSTEM__' THEN
    RAISE EXCEPTION 'memory_app may not use system tenant for consolidation' USING ERRCODE='42501';
  END IF;
  IF v_ctx<>p_tenant_id THEN
    RAISE EXCEPTION 'consolidation tenant mismatch' USING ERRCODE='42501';
  END IF;
  SELECT EXISTS(
    SELECT 1 FROM agent_leases l
    WHERE l.tenant_id=p_tenant_id AND l.lease_key=p_lease_key
      AND l.owner_agent_id=v_agent AND l.fencing_token=p_fencing_token
      AND l.expires_at>now()
  ) INTO v_ok;
  IF NOT v_ok THEN
    RAISE EXCEPTION 'stale, expired or foreign consolidation lease' USING ERRCODE='40001';
  END IF;
END;
$$;
ALTER FUNCTION memory_consolidation_assert_lease(text,text,bigint) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_consolidation_assert_lease(text,text,bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION memory_start_consolidation_shadow(
  p_run_id text,
  p_scope_key text,
  p_mode text,
  p_trigger_kind text,
  p_lease_key text,
  p_fencing_token bigint,
  p_policy_version text,
  p_project_id text,
  p_mission_id text,
  p_session_id text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_tenant text;
BEGIN
  v_tenant:=NULLIF(current_setting('app.current_tenant',true),'');
  IF v_tenant IS NULL THEN
    RAISE EXCEPTION 'runtime tenant context required for consolidation' USING ERRCODE='42501';
  END IF;
  PERFORM memory_consolidation_assert_lease(v_tenant,p_lease_key,p_fencing_token);
  IF p_run_id IS NULL OR p_run_id !~ '^conrun-[0-9a-f]{32}$' THEN
    RAISE EXCEPTION 'invalid consolidation run id' USING ERRCODE='22023';
  END IF;
  IF p_scope_key IS NULL OR length(btrim(p_scope_key)) NOT BETWEEN 1 AND 512 THEN
    RAISE EXCEPTION 'invalid consolidation scope key' USING ERRCODE='22023';
  END IF;
  IF p_mode NOT IN (
    'MICRO_CONSOLIDATION','IDLE_CONSOLIDATION','DAILY_CONSOLIDATION',
    'DEEP_CONSOLIDATION','MANUAL_CONSOLIDATION','RECOVERY_CONSOLIDATION'
  ) OR p_trigger_kind NOT IN ('IDLE','TIME_WINDOW','EVENT_THRESHOLD','MEMORY_PRESSURE','MANUAL','RECOVERY') THEN
    RAISE EXCEPTION 'invalid consolidation mode/trigger' USING ERRCODE='22023';
  END IF;
  IF p_policy_version IS NULL OR length(btrim(p_policy_version)) NOT BETWEEN 1 AND 80 THEN
    RAISE EXCEPTION 'invalid consolidation policy version' USING ERRCODE='22023';
  END IF;
  INSERT INTO cognitive_consolidation_runs(
    run_id,tenant_id,scope_key,project_id,mission_id,session_id,mode,trigger_kind,status,
    lease_key,fencing_token,policy_version
  ) VALUES(
    p_run_id,v_tenant,p_scope_key,NULLIF(p_project_id,''),NULLIF(p_mission_id,''),NULLIF(p_session_id,''),
    p_mode,p_trigger_kind,'RUNNING',p_lease_key,p_fencing_token,p_policy_version
  );
  INSERT INTO cognitive_consolidation_events(event_id,tenant_id,run_id,event_type,payload_jsonb)
  VALUES(
    'conevt-'||substr(md5(p_run_id||':STARTED'),1,32),v_tenant,p_run_id,'STARTED',
    jsonb_build_object('mode',p_mode,'trigger',p_trigger_kind,'policy_version',p_policy_version)
  );
  RETURN p_run_id;
END;
$$;
ALTER FUNCTION memory_start_consolidation_shadow(text,text,text,text,text,bigint,text,text,text,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_start_consolidation_shadow(text,text,text,text,text,bigint,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_start_consolidation_shadow(text,text,text,text,text,bigint,text,text,text,text) TO memory_app;

CREATE OR REPLACE FUNCTION memory_resume_consolidation_shadow(
  p_run_id text,
  p_lease_key text,
  p_fencing_token bigint
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_run cognitive_consolidation_runs%ROWTYPE;
BEGIN
  SELECT * INTO v_run FROM cognitive_consolidation_runs WHERE run_id=p_run_id FOR UPDATE;
  IF v_run.run_id IS NULL THEN
    RAISE EXCEPTION 'consolidation run not found' USING ERRCODE='02000';
  END IF;
  IF v_run.status NOT IN ('RUNNING','RECOVERING','FAILED') THEN
    RAISE EXCEPTION 'consolidation run is not recoverable from current status' USING ERRCODE='22023';
  END IF;
  PERFORM memory_consolidation_assert_lease(v_run.tenant_id,p_lease_key,p_fencing_token);
  UPDATE cognitive_consolidation_runs
  SET status='RECOVERING',lease_key=p_lease_key,fencing_token=p_fencing_token,
      recovered_from_interrupt=true,heartbeat_at=now(),failure_type=NULL
  WHERE run_id=p_run_id;
  INSERT INTO cognitive_consolidation_events(event_id,tenant_id,run_id,event_type,payload_jsonb)
  VALUES(
    'conevt-'||substr(md5(p_run_id||':RESUMED:'||p_fencing_token::text),1,32),
    v_run.tenant_id,p_run_id,'RESUMED',jsonb_build_object('fencing_token',p_fencing_token)
  ) ON CONFLICT(event_id) DO NOTHING;
  RETURN p_run_id;
END;
$$;
ALTER FUNCTION memory_resume_consolidation_shadow(text,text,bigint) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_resume_consolidation_shadow(text,text,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_resume_consolidation_shadow(text,text,bigint) TO memory_app;

CREATE OR REPLACE FUNCTION memory_checkpoint_consolidation_shadow(
  p_run_id text,
  p_checkpoint_id text,
  p_sequence_no integer,
  p_stage text,
  p_state jsonb,
  p_state_sha256 text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_run cognitive_consolidation_runs%ROWTYPE;
BEGIN
  SELECT * INTO v_run FROM cognitive_consolidation_runs WHERE run_id=p_run_id FOR UPDATE;
  IF v_run.run_id IS NULL OR v_run.status NOT IN ('RUNNING','RECOVERING') THEN
    RAISE EXCEPTION 'active consolidation run required for checkpoint' USING ERRCODE='22023';
  END IF;
  PERFORM memory_consolidation_assert_lease(v_run.tenant_id,v_run.lease_key,v_run.fencing_token);
  IF p_checkpoint_id IS NULL OR p_checkpoint_id !~ '^concp-[0-9a-f]{32}$' OR p_sequence_no<=v_run.checkpoint_sequence THEN
    RAISE EXCEPTION 'invalid or stale consolidation checkpoint' USING ERRCODE='22023';
  END IF;
  IF p_stage NOT IN (
    'SELECT','REPLAY','COMPARE','CLUSTER','ASSOCIATE','DETECT_PATTERN',
    'GENERATE_CANDIDATE','VALIDATE','CONSOLIDATE','RECORD_PROVENANCE'
  ) THEN
    RAISE EXCEPTION 'invalid consolidation stage' USING ERRCODE='22023';
  END IF;
  IF p_state IS NULL OR jsonb_typeof(p_state)<>'object' OR octet_length(p_state::text)>131072
     OR p_state_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid consolidation checkpoint state' USING ERRCODE='22023';
  END IF;
  INSERT INTO cognitive_consolidation_checkpoints(
    checkpoint_id,tenant_id,run_id,sequence_no,stage,state_jsonb,state_sha256
  ) VALUES(p_checkpoint_id,v_run.tenant_id,p_run_id,p_sequence_no,p_stage,p_state,p_state_sha256);
  UPDATE cognitive_consolidation_runs
  SET checkpoint_sequence=p_sequence_no,heartbeat_at=now()
  WHERE run_id=p_run_id;
  INSERT INTO cognitive_consolidation_events(event_id,tenant_id,run_id,event_type,payload_jsonb)
  VALUES(
    'conevt-'||substr(md5(p_run_id||':CHECKPOINT:'||p_sequence_no::text),1,32),
    v_run.tenant_id,p_run_id,'CHECKPOINTED',jsonb_build_object('sequence_no',p_sequence_no,'stage',p_stage,'state_sha256',p_state_sha256)
  );
  RETURN p_checkpoint_id;
END;
$$;
ALTER FUNCTION memory_checkpoint_consolidation_shadow(text,text,integer,text,jsonb,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_checkpoint_consolidation_shadow(text,text,integer,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_checkpoint_consolidation_shadow(text,text,integer,text,jsonb,text) TO memory_app;

CREATE OR REPLACE FUNCTION memory_record_consolidation_candidate_shadow(
  p_run_id text,
  p_candidate_id text,
  p_candidate_kind text,
  p_source_memory_ids text[],
  p_status text,
  p_confidence double precision,
  p_conflict boolean,
  p_proof jsonb,
  p_candidate_digest text,
  p_validation jsonb
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_run cognitive_consolidation_runs%ROWTYPE;
  v_source text;
  v_tenant text;
  v_rows integer;
  v_existing cognitive_consolidation_candidates%ROWTYPE;
BEGIN
  SELECT * INTO v_run FROM cognitive_consolidation_runs WHERE run_id=p_run_id FOR UPDATE;
  IF v_run.run_id IS NULL OR v_run.status NOT IN ('RUNNING','RECOVERING') THEN
    RAISE EXCEPTION 'active consolidation run required for candidate' USING ERRCODE='22023';
  END IF;
  PERFORM memory_consolidation_assert_lease(v_run.tenant_id,v_run.lease_key,v_run.fencing_token);
  IF p_candidate_id IS NULL OR p_candidate_id !~ '^concand-[0-9a-f]{32}$'
     OR p_candidate_kind NOT IN ('REPEATED_PATTERN','HIGH_SALIENCE_CLUSTER','OUTCOME_CLUSTER','ASSOCIATION_CLUSTER','CONFLICT_CLUSTER')
     OR p_status NOT IN ('CANDIDATE','VALIDATED_SHADOW','REJECTED')
     OR p_confidence NOT BETWEEN 0.0 AND 1.0
     OR p_candidate_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid consolidation candidate' USING ERRCODE='22023';
  END IF;
  IF cardinality(p_source_memory_ids) NOT BETWEEN 2 AND 64 THEN
    RAISE EXCEPTION 'consolidation candidate sample out of bounds' USING ERRCODE='22023';
  END IF;
  IF p_proof IS NULL OR jsonb_typeof(p_proof)<>'object' OR octet_length(p_proof::text)>131072
     OR p_validation IS NULL OR jsonb_typeof(p_validation)<>'object' OR octet_length(p_validation::text)>65536 THEN
    RAISE EXCEPTION 'invalid consolidation candidate proof' USING ERRCODE='22023';
  END IF;
  FOREACH v_source IN ARRAY p_source_memory_ids LOOP
    SELECT m.tenant_id INTO v_tenant
    FROM memory_items m
    WHERE m.item_id=v_source
      AND memory_rls_visible(m.tenant_id)
      AND memory_scope_matches_context(
        m.memory_scope,m.memory_scope_ref,COALESCE(v_run.project_id,''),COALESCE(v_run.mission_id,''),COALESCE(v_run.session_id,'')
      );
    IF v_tenant IS NULL OR v_tenant<>v_run.tenant_id THEN
      RAISE EXCEPTION 'consolidation candidate source outside scope' USING ERRCODE='42501';
    END IF;
  END LOOP;
  INSERT INTO cognitive_consolidation_candidates(
    candidate_id,tenant_id,run_id,candidate_kind,source_memory_ids,sample_count,status,
    confidence,conflict,proof_jsonb,candidate_digest,validation_jsonb
  ) VALUES(
    p_candidate_id,v_run.tenant_id,p_run_id,p_candidate_kind,p_source_memory_ids,cardinality(p_source_memory_ids),p_status,
    p_confidence,p_conflict,p_proof,p_candidate_digest,p_validation
  ) ON CONFLICT(candidate_id) DO NOTHING;
  GET DIAGNOSTICS v_rows=ROW_COUNT;
  IF v_rows=0 THEN
    SELECT * INTO v_existing FROM cognitive_consolidation_candidates WHERE candidate_id=p_candidate_id;
    IF v_existing.candidate_id IS NULL OR v_existing.run_id<>p_run_id OR v_existing.candidate_digest<>p_candidate_digest THEN
      RAISE EXCEPTION 'consolidation candidate idempotency conflict' USING ERRCODE='40001';
    END IF;
    RETURN p_candidate_id;
  END IF;
  INSERT INTO cognitive_consolidation_events(event_id,tenant_id,run_id,event_type,payload_jsonb)
  VALUES(
    'conevt-'||substr(md5(p_run_id||':CANDIDATE:'||p_candidate_id),1,32),
    v_run.tenant_id,p_run_id,'CANDIDATE_CREATED',jsonb_build_object('candidate_id',p_candidate_id,'status',p_status)
  );
  RETURN p_candidate_id;
END;
$$;
ALTER FUNCTION memory_record_consolidation_candidate_shadow(text,text,text,text[],text,double precision,boolean,jsonb,text,jsonb) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_record_consolidation_candidate_shadow(text,text,text,text[],text,double precision,boolean,jsonb,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_record_consolidation_candidate_shadow(text,text,text,text[],text,double precision,boolean,jsonb,text,jsonb) TO memory_app;

CREATE OR REPLACE FUNCTION memory_finish_consolidation_shadow(
  p_run_id text,
  p_source_count integer,
  p_replay_digest text
) RETURNS TABLE(status text,candidate_count integer,validated_candidate_count integer,recovered_from_interrupt boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_run cognitive_consolidation_runs%ROWTYPE;
  v_candidates integer;
  v_validated integer;
BEGIN
  SELECT * INTO v_run FROM cognitive_consolidation_runs WHERE run_id=p_run_id FOR UPDATE;
  IF v_run.run_id IS NULL OR v_run.status NOT IN ('RUNNING','RECOVERING') THEN
    RAISE EXCEPTION 'active consolidation run required for finish' USING ERRCODE='22023';
  END IF;
  PERFORM memory_consolidation_assert_lease(v_run.tenant_id,v_run.lease_key,v_run.fencing_token);
  IF p_source_count NOT BETWEEN 0 AND 512 OR p_replay_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid consolidation completion evidence' USING ERRCODE='22023';
  END IF;
  SELECT count(*)::integer,count(*) FILTER(WHERE c.status='VALIDATED_SHADOW')::integer
  INTO v_candidates,v_validated
  FROM cognitive_consolidation_candidates c WHERE c.run_id=p_run_id;
  UPDATE cognitive_consolidation_runs
  SET status='COMPLETED',source_count=p_source_count,candidate_count=v_candidates,
      validated_candidate_count=v_validated,replay_digest=p_replay_digest,
      heartbeat_at=now(),completed_at=now(),failure_type=NULL
  WHERE run_id=p_run_id;
  INSERT INTO cognitive_consolidation_events(event_id,tenant_id,run_id,event_type,payload_jsonb)
  VALUES(
    'conevt-'||substr(md5(p_run_id||':FINISHED'),1,32),v_run.tenant_id,p_run_id,'FINISHED',
    jsonb_build_object('source_count',p_source_count,'candidate_count',v_candidates,'validated_candidate_count',v_validated,'replay_digest',p_replay_digest)
  ) ON CONFLICT(event_id) DO NOTHING;
  RETURN QUERY SELECT 'COMPLETED'::text,v_candidates,v_validated,v_run.recovered_from_interrupt;
END;
$$;
ALTER FUNCTION memory_finish_consolidation_shadow(text,integer,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_finish_consolidation_shadow(text,integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_finish_consolidation_shadow(text,integer,text) TO memory_app;

CREATE OR REPLACE FUNCTION memory_fail_consolidation_shadow(
  p_run_id text,
  p_failure_type text
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_run cognitive_consolidation_runs%ROWTYPE;
BEGIN
  SELECT * INTO v_run FROM cognitive_consolidation_runs WHERE run_id=p_run_id FOR UPDATE;
  IF v_run.run_id IS NULL THEN
    RAISE EXCEPTION 'consolidation run not found' USING ERRCODE='02000';
  END IF;
  PERFORM memory_consolidation_assert_lease(v_run.tenant_id,v_run.lease_key,v_run.fencing_token);
  UPDATE cognitive_consolidation_runs
  SET status='FAILED',failure_type=left(COALESCE(NULLIF(btrim(p_failure_type),''),'UNSPECIFIED'),160),heartbeat_at=now()
  WHERE run_id=p_run_id;
  INSERT INTO cognitive_consolidation_events(event_id,tenant_id,run_id,event_type,payload_jsonb)
  VALUES(
    'conevt-'||substr(md5(p_run_id||':FAILED:'||COALESCE(p_failure_type,'')),1,32),
    v_run.tenant_id,p_run_id,'FAILED',jsonb_build_object('failure_type',left(COALESCE(p_failure_type,'UNSPECIFIED'),160))
  ) ON CONFLICT(event_id) DO NOTHING;
  RETURN p_run_id;
END;
$$;
ALTER FUNCTION memory_fail_consolidation_shadow(text,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_fail_consolidation_shadow(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_fail_consolidation_shadow(text,text) TO memory_app;

GRANT SELECT,INSERT,UPDATE ON cognitive_consolidation_runs TO memory_admin;
GRANT SELECT,INSERT ON cognitive_consolidation_checkpoints,cognitive_consolidation_candidates,cognitive_consolidation_events TO memory_admin;
GRANT SELECT ON cognitive_consolidation_runs,cognitive_consolidation_checkpoints,cognitive_consolidation_candidates,cognitive_consolidation_events TO memory_app;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON cognitive_consolidation_runs,cognitive_consolidation_checkpoints,cognitive_consolidation_candidates,cognitive_consolidation_events FROM memory_app;

ALTER TABLE temporal_entity_contracts DISABLE TRIGGER trg_temporal_contract_immutable;
INSERT INTO temporal_entity_contracts(entity_name,temporal_kind,rationale,storage_mode,storage_entity) VALUES
  ('cognitive_consolidation_runs','OPERATIONAL','background consolidation control state and heartbeat','INLINE',NULL),
  ('cognitive_consolidation_checkpoints','OPERATIONAL','durable worker recovery checkpoint','INLINE',NULL),
  ('cognitive_consolidation_candidates','OPERATIONAL','derived SHADOW candidate; never canonical truth','INLINE',NULL),
  ('cognitive_consolidation_events','OPERATIONAL','append-only worker execution evidence','INLINE',NULL)
ON CONFLICT(entity_name) DO NOTHING;
ALTER TABLE temporal_entity_contracts ENABLE TRIGGER trg_temporal_contract_immutable;

INSERT INTO schema_meta(key,value) VALUES
  ('cognitive_consolidation_version','CON-1.0.0'),
  ('cognitive_consolidation_engine_version','OCC-1.0.0'),
  ('cognitive_consolidation_mode','SHADOW'),
  ('gate_c4_status','PENDING')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
