-- F02 functional affective salience persistence. Additive, append-only and shadow-only.

CREATE TABLE IF NOT EXISTS memory_salience(
  salience_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  score double precision NOT NULL CHECK(score BETWEEN 0 AND 1),
  dimensions_jsonb jsonb NOT NULL CHECK(jsonb_typeof(dimensions_jsonb)='object'),
  policy_version text NOT NULL CHECK(length(btrim(policy_version)) BETWEEN 1 AND 80),
  explanation_jsonb jsonb NOT NULL CHECK(jsonb_typeof(explanation_jsonb)='object'),
  evidence_refs_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(evidence_refs_jsonb)='array'),
  retrieval_trace_id text,
  mode text NOT NULL DEFAULT 'SHADOW' CHECK(mode='SHADOW'),
  computed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_salience_memory
  ON memory_salience(tenant_id,memory_id,computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_salience_score
  ON memory_salience(tenant_id,score DESC,computed_at DESC);

ALTER TABLE memory_salience ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_salience FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON memory_salience;
CREATE POLICY tenant_isolation ON memory_salience
  USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

DROP TRIGGER IF EXISTS trg_memory_salience_append_only ON memory_salience;
CREATE TRIGGER trg_memory_salience_append_only
BEFORE UPDATE OR DELETE ON memory_salience FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

CREATE OR REPLACE FUNCTION memory_record_salience_shadow(
  p_salience_id text,
  p_memory_id text,
  p_score double precision,
  p_dimensions jsonb,
  p_policy_version text,
  p_explanation jsonb,
  p_evidence_refs jsonb,
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
  v_key text;
  v_value jsonb;
BEGIN
  v_ctx := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_ctx IS NULL OR (session_user='memory_app' AND v_ctx='__SYSTEM__') THEN
    RAISE EXCEPTION 'runtime tenant context is required for salience' USING ERRCODE='42501';
  END IF;
  IF p_salience_id IS NULL OR p_salience_id !~ '^sal-[0-9a-f]{32}$' OR p_score<0 OR p_score>1 THEN
    RAISE EXCEPTION 'invalid salience request' USING ERRCODE='22023';
  END IF;
  IF p_dimensions IS NULL OR jsonb_typeof(p_dimensions)<>'object' OR octet_length(p_dimensions::text)>32768 THEN
    RAISE EXCEPTION 'invalid salience dimensions' USING ERRCODE='22023';
  END IF;
  IF p_explanation IS NULL OR jsonb_typeof(p_explanation)<>'object' OR octet_length(p_explanation::text)>65536 THEN
    RAISE EXCEPTION 'invalid salience explanation' USING ERRCODE='22023';
  END IF;
  IF p_evidence_refs IS NULL OR jsonb_typeof(p_evidence_refs)<>'array' OR jsonb_array_length(p_evidence_refs)>64
     OR octet_length(p_evidence_refs::text)>32768 THEN
    RAISE EXCEPTION 'invalid salience evidence' USING ERRCODE='22023';
  END IF;
  IF p_policy_version IS NULL OR btrim(p_policy_version)='' OR length(p_policy_version)>80 THEN
    RAISE EXCEPTION 'invalid salience policy version' USING ERRCODE='22023';
  END IF;

  FOR v_key,v_value IN SELECT key,value FROM jsonb_each(p_dimensions) LOOP
    IF v_key NOT IN (
      'novelty','surprise','risk','reward','loss','urgency','goal_relevance','social_relevance',
      'operational_impact','financial_impact','safety_impact','rarity','irreversibility','uncertainty'
    ) THEN
      RAISE EXCEPTION 'unknown salience dimension: %',v_key USING ERRCODE='22023';
    END IF;
    IF jsonb_typeof(v_value)<>'number' OR (v_value::text)::double precision<0 OR (v_value::text)::double precision>1 THEN
      RAISE EXCEPTION 'salience dimension out of bounds: %',v_key USING ERRCODE='22023';
    END IF;
  END LOOP;

  SELECT tenant_id INTO v_tenant FROM memory_items
   WHERE item_id=p_memory_id AND memory_rls_visible(tenant_id);
  IF v_tenant IS NULL OR (v_ctx<>'__SYSTEM__' AND v_ctx<>v_tenant) THEN
    RAISE EXCEPTION 'memory not visible in salience scope' USING ERRCODE='42501';
  END IF;

  INSERT INTO memory_salience(
    salience_id,tenant_id,memory_id,score,dimensions_jsonb,policy_version,
    explanation_jsonb,evidence_refs_jsonb,retrieval_trace_id,mode
  ) VALUES(
    p_salience_id,v_tenant,p_memory_id,p_score,p_dimensions,p_policy_version,
    p_explanation,p_evidence_refs,p_retrieval_trace_id,'SHADOW'
  );
END;
$$;
ALTER FUNCTION memory_record_salience_shadow(text,text,double precision,jsonb,text,jsonb,jsonb,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_record_salience_shadow(text,text,double precision,jsonb,text,jsonb,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_record_salience_shadow(text,text,double precision,jsonb,text,jsonb,jsonb,text) TO memory_app;

GRANT SELECT,INSERT ON memory_salience TO memory_admin;
GRANT SELECT ON memory_salience TO memory_app;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON memory_salience FROM memory_app;

INSERT INTO schema_meta(key,value) VALUES
('cognitive_salience_contract_version','SAL-1.0.0'),
('cognitive_salience_mode','SHADOW'),
('gate_c2_status','PENDING')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
