-- P09: explicit causal-memory policy. CAUSE can only be reached from a current-version
-- CORRELATION with a policy-eligible causal assessment.

CREATE OR REPLACE FUNCTION memory_causal_independent_ref_count(p_evidence jsonb) RETURNS integer
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_count integer;
BEGIN
  IF jsonb_typeof(COALESCE(p_evidence,'{}'::jsonb)->'independent_refs') <> 'array' THEN
    RETURN 0;
  END IF;
  SELECT count(DISTINCT btrim(value))::integer INTO v_count
  FROM jsonb_array_elements_text(COALESCE(p_evidence,'{}'::jsonb)->'independent_refs')
  WHERE btrim(value) <> '';
  RETURN COALESCE(v_count,0);
END;
$$;

CREATE OR REPLACE FUNCTION memory_causal_policy_eligible(
  p_source_category text,
  p_hypothesis jsonb,
  p_intervention jsonb,
  p_comparator jsonb,
  p_confounders jsonb,
  p_confounder_control jsonb,
  p_mechanism jsonb,
  p_counterfactual jsonb,
  p_attribution_confidence double precision,
  p_sample_size integer,
  p_repetition_count integer,
  p_evidence jsonb
) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT
    p_source_category='CORRELATION'
    AND jsonb_typeof(p_hypothesis)='object' AND p_hypothesis<>'{}'::jsonb
    AND jsonb_typeof(p_intervention)='object' AND p_intervention<>'{}'::jsonb
    AND jsonb_typeof(p_comparator)='object' AND p_comparator<>'{}'::jsonb
    AND jsonb_typeof(p_confounders)='array'
    AND jsonb_typeof(p_confounder_control)='object' AND p_confounder_control<>'{}'::jsonb
    AND p_confounder_control->'addressed'='true'::jsonb
    AND jsonb_typeof(p_mechanism)='object' AND p_mechanism<>'{}'::jsonb
    AND p_mechanism->'supported'='true'::jsonb
    AND jsonb_typeof(p_counterfactual)='object' AND p_counterfactual<>'{}'::jsonb
    AND p_counterfactual->'supported'='true'::jsonb
    AND p_attribution_confidence>=0.80
    AND p_sample_size>=30
    AND p_repetition_count>=2
    AND memory_causal_independent_ref_count(p_evidence)>=2
    AND p_evidence->'replications_consistent'='true'::jsonb;
$$;

CREATE TABLE IF NOT EXISTS memory_causal_assessments(
  assessment_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  version_no integer NOT NULL CHECK(version_no>=1),
  content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[0-9a-f]{64}$'),
  source_category text NOT NULL CHECK(source_category='CORRELATION'),
  hypothesis jsonb NOT NULL CHECK(jsonb_typeof(hypothesis)='object'),
  intervention jsonb NOT NULL CHECK(jsonb_typeof(intervention)='object'),
  comparator jsonb NOT NULL CHECK(jsonb_typeof(comparator)='object'),
  confounders jsonb NOT NULL CHECK(jsonb_typeof(confounders)='array'),
  confounder_control jsonb NOT NULL CHECK(jsonb_typeof(confounder_control)='object'),
  mechanism jsonb NOT NULL CHECK(jsonb_typeof(mechanism)='object'),
  counterfactual jsonb NOT NULL CHECK(jsonb_typeof(counterfactual)='object'),
  attribution_confidence double precision NOT NULL CHECK(attribution_confidence>=0 AND attribution_confidence<=1),
  sample_size integer NOT NULL CHECK(sample_size>=1),
  repetition_count integer NOT NULL CHECK(repetition_count>=1),
  evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
  policy_version text NOT NULL DEFAULT 'CP-1.0.0' CHECK(policy_version='CP-1.0.0'),
  decision_criteria jsonb NOT NULL CHECK(jsonb_typeof(decision_criteria)='object'),
  failure_reasons jsonb NOT NULL CHECK(jsonb_typeof(failure_reasons)='array'),
  eligible boolean GENERATED ALWAYS AS (
    memory_causal_policy_eligible(
      source_category,hypothesis,intervention,comparator,confounders,confounder_control,
      mechanism,counterfactual,attribution_confidence,sample_size,repetition_count,evidence
    )
  ) STORED,
  created_by text NOT NULL,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_causal_assessments_item ON memory_causal_assessments(item_id,observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_causal_assessments_eligible ON memory_causal_assessments(item_id,eligible,observed_at DESC);

CREATE TABLE IF NOT EXISTS memory_causal_promotions(
  promotion_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  assessment_id text NOT NULL UNIQUE REFERENCES memory_causal_assessments(assessment_id) ON DELETE RESTRICT,
  transition_id text NOT NULL UNIQUE REFERENCES memory_ontology_transitions(transition_id) ON DELETE RESTRICT,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[0-9a-f]{64}$'),
  from_category text NOT NULL CHECK(from_category='CORRELATION'),
  to_category text NOT NULL CHECK(to_category='CAUSE'),
  policy_version text NOT NULL CHECK(policy_version='CP-1.0.0'),
  actor_id text NOT NULL,
  reason text NOT NULL CHECK(length(btrim(reason))>0),
  promoted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_causal_promotions_item ON memory_causal_promotions(item_id,promoted_at DESC);

CREATE OR REPLACE FUNCTION memory_validate_causal_assessment() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_tenant text; DECLARE v_category text; DECLARE v_version_id text; DECLARE v_version_no integer; DECLARE v_sha text;
BEGIN
  SELECT m.tenant_id,m.category INTO v_tenant,v_category FROM memory_items m WHERE m.item_id=NEW.item_id;
  IF v_tenant IS NULL THEN RAISE EXCEPTION 'causal assessment memory not found' USING ERRCODE='23503'; END IF;
  IF NEW.tenant_id IS NULL OR NEW.tenant_id='' THEN NEW.tenant_id:=v_tenant;
  ELSIF NEW.tenant_id<>v_tenant THEN RAISE EXCEPTION 'causal assessment tenant mismatch' USING ERRCODE='42501'; END IF;
  IF v_category<>'CORRELATION' OR NEW.source_category<>v_category THEN
    RAISE EXCEPTION 'causal assessment requires current CORRELATION memory' USING ERRCODE='23514';
  END IF;
  SELECT v.version_id,v.version_no,v.content_sha256 INTO v_version_id,v_version_no,v_sha
  FROM memory_versions v WHERE v.item_id=NEW.item_id ORDER BY v.version_no DESC LIMIT 1;
  IF v_version_id IS NULL OR NEW.version_id<>v_version_id OR NEW.version_no<>v_version_no OR NEW.content_sha256<>v_sha THEN
    RAISE EXCEPTION 'causal assessment must bind the current exact memory version/hash' USING ERRCODE='40001';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_guard_cause_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.category='CAUSE' THEN
    RAISE EXCEPTION 'direct CAUSE creation forbidden; create CORRELATION and use causal promotion' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_guard_ontology_category_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_assessment_id text; DECLARE v_ok boolean;
BEGIN
  IF OLD.category IS DISTINCT FROM NEW.category THEN
    IF COALESCE(current_setting('app.ontology_transition_authorized',true),'') <> '1' THEN
      RAISE EXCEPTION 'direct knowledge category update forbidden; use ontology transition' USING ERRCODE='42501';
    END IF;
    IF NEW.category='CAUSE' THEN
      v_assessment_id:=NULLIF(current_setting('app.causal_assessment_id',true),'');
      SELECT EXISTS(
        SELECT 1 FROM memory_causal_assessments a
        WHERE a.assessment_id=v_assessment_id AND a.item_id=OLD.item_id AND a.eligible
          AND a.version_id=(SELECT v.version_id FROM memory_versions v WHERE v.item_id=OLD.item_id ORDER BY v.version_no DESC LIMIT 1)
          AND a.content_sha256=OLD.content_sha256
      ) INTO v_ok;
      IF NOT COALESCE(v_ok,false) THEN
        RAISE EXCEPTION 'CAUSE promotion requires eligible current-version causal assessment' USING ERRCODE='23514';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_cause_insert ON memory_items;
CREATE TRIGGER trg_guard_cause_insert BEFORE INSERT ON memory_items FOR EACH ROW EXECUTE FUNCTION memory_guard_cause_insert();
DROP TRIGGER IF EXISTS trg_validate_causal_assessment ON memory_causal_assessments;
CREATE TRIGGER trg_validate_causal_assessment BEFORE INSERT ON memory_causal_assessments FOR EACH ROW EXECUTE FUNCTION memory_validate_causal_assessment();
DROP TRIGGER IF EXISTS trg_causal_assessments_append_only ON memory_causal_assessments;
CREATE TRIGGER trg_causal_assessments_append_only BEFORE UPDATE OR DELETE ON memory_causal_assessments FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_causal_promotions_append_only ON memory_causal_promotions;
CREATE TRIGGER trg_causal_promotions_append_only BEFORE UPDATE OR DELETE ON memory_causal_promotions FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['memory_causal_assessments','memory_causal_promotions'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (memory_rls_visible(tenant_id)) WITH CHECK (memory_rls_visible(tenant_id))',t);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION memory_apply_ontology_transition(
  p_transition_id text,p_item_id text,p_to_category text,p_actor text,p_reason text,p_evidence jsonb
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE v_from_category text; DECLARE v_item_tenant text; DECLARE v_current_version text; DECLARE v_current_sha text;
DECLARE v_assessment_id text; DECLARE v_assessment_ok boolean; DECLARE v_promotion_id text;
BEGIN
  SELECT m.category,m.tenant_id,m.content_sha256 INTO v_from_category,v_item_tenant,v_current_sha FROM memory_items m WHERE m.item_id=p_item_id FOR UPDATE;
  IF v_from_category IS NULL THEN RAISE EXCEPTION 'memory not found for ontology transition'; END IF;
  IF NOT EXISTS(
    SELECT 1 FROM ontology_transition_rules r
    WHERE r.from_category=v_from_category AND r.to_category=p_to_category
  ) THEN
    RAISE EXCEPTION 'invalid ontology transition: % -> %',v_from_category,p_to_category USING ERRCODE='23514';
  END IF;
  SELECT v.version_id INTO v_current_version FROM memory_versions v WHERE v.item_id=p_item_id ORDER BY v.version_no DESC LIMIT 1;

  IF p_to_category='CAUSE' THEN
    v_assessment_id:=NULLIF(COALESCE(p_evidence,'{}'::jsonb)->>'causal_assessment_id','');
    SELECT EXISTS(
      SELECT 1 FROM memory_causal_assessments a
      WHERE a.assessment_id=v_assessment_id AND a.item_id=p_item_id AND a.eligible
        AND a.version_id=v_current_version AND a.content_sha256=v_current_sha AND a.source_category='CORRELATION'
    ) INTO v_assessment_ok;
    IF NOT COALESCE(v_assessment_ok,false) THEN
      RAISE EXCEPTION 'CAUSE promotion requires eligible current-version causal assessment' USING ERRCODE='23514';
    END IF;
    PERFORM set_config('app.causal_assessment_id',v_assessment_id,true);
  ELSE
    PERFORM set_config('app.causal_assessment_id','',true);
  END IF;

  PERFORM set_config('app.ontology_transition_authorized','1',true);
  UPDATE memory_items SET category=p_to_category,validation_status='UNVALIDATED',governor_eligible=false WHERE item_id=p_item_id;
  PERFORM set_config('app.ontology_transition_authorized','0',true);
  PERFORM set_config('app.causal_assessment_id','',true);

  INSERT INTO memory_ontology_transitions(transition_id,tenant_id,item_id,version_id,from_category,to_category,actor_id,reason,evidence)
  VALUES(p_transition_id,v_item_tenant,p_item_id,v_current_version,v_from_category,p_to_category,p_actor,p_reason,COALESCE(p_evidence,'{}'::jsonb));

  IF p_to_category='CAUSE' THEN
    v_promotion_id:='prom-'||substr(md5(p_transition_id||':'||v_assessment_id),1,32);
    INSERT INTO memory_causal_promotions(
      promotion_id,tenant_id,assessment_id,transition_id,item_id,version_id,content_sha256,
      from_category,to_category,policy_version,actor_id,reason
    ) VALUES(
      v_promotion_id,v_item_tenant,v_assessment_id,p_transition_id,p_item_id,v_current_version,v_current_sha,
      v_from_category,p_to_category,'CP-1.0.0',p_actor,p_reason
    );
  END IF;

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

INSERT INTO schema_meta(key,value) VALUES('causal_policy_version','CP-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.17.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
