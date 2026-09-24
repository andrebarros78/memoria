CREATE TABLE IF NOT EXISTS learning_policy_versions(
  policy_version text PRIMARY KEY,
  algorithm text NOT NULL,
  parameters jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO learning_policy_versions(policy_version,algorithm,parameters)
VALUES(
  'LP-1.0.0',
  'BOUNDED_VERSION_OUTCOME_V1',
  '{"success_base_delta":0.04,"failure_base_delta":-0.06,"max_positive_delta":0.05,"max_negative_delta":-0.08,"authenticated_authority_weight":0.75,"attested_authority_weight":1.0,"internal_authority_weight":0.9,"default_evidence_weight":0.5,"default_repeatability_weight":0.75,"default_recency_weight":1.0,"default_sample_weight":0.8,"default_independence_weight":0.8,"default_causality_weight":0.8}'::jsonb
)
ON CONFLICT(policy_version) DO NOTHING;

DROP TRIGGER IF EXISTS trg_learning_policy_versions_append_only ON learning_policy_versions;
CREATE TRIGGER trg_learning_policy_versions_append_only
BEFORE UPDATE OR DELETE ON learning_policy_versions
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

CREATE TABLE IF NOT EXISTS memory_version_learning(
  tenant_id text NOT NULL,
  version_id text PRIMARY KEY REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_no integer NOT NULL CHECK(version_no > 0),
  content_sha256 text NOT NULL,
  base_confidence double precision NOT NULL CHECK(base_confidence >= 0 AND base_confidence <= 1),
  learned_confidence double precision NOT NULL CHECK(learned_confidence >= 0 AND learned_confidence <= 1),
  application_count bigint NOT NULL DEFAULT 0 CHECK(application_count >= 0),
  success_count bigint NOT NULL DEFAULT 0 CHECK(success_count >= 0),
  failure_count bigint NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
  evidence_weight double precision NOT NULL DEFAULT 0 CHECK(evidence_weight >= 0),
  current_policy_version text NOT NULL REFERENCES learning_policy_versions(policy_version) ON DELETE RESTRICT,
  last_outcome_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_version_learning_item ON memory_version_learning(tenant_id,item_id,version_no DESC);

CREATE TABLE IF NOT EXISTS memory_learning_events(
  learning_event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  outcome_id text NOT NULL UNIQUE REFERENCES memory_outcomes(outcome_id) ON DELETE RESTRICT,
  application_id text NOT NULL UNIQUE REFERENCES memory_applications(application_id) ON DELETE RESTRICT,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  version_no integer NOT NULL CHECK(version_no > 0),
  content_sha256 text NOT NULL,
  policy_version text NOT NULL REFERENCES learning_policy_versions(policy_version) ON DELETE RESTRICT,
  success boolean NOT NULL,
  authority_tier text NOT NULL CHECK(authority_tier IN ('AUTHENTICATED','ATTESTED','INTERNAL')),
  components jsonb NOT NULL,
  computed_delta double precision NOT NULL CHECK(computed_delta >= -1 AND computed_delta <= 1),
  confidence_before double precision NOT NULL CHECK(confidence_before >= 0 AND confidence_before <= 1),
  confidence_after double precision NOT NULL CHECK(confidence_after >= 0 AND confidence_after <= 1),
  applied_to_current_item boolean NOT NULL DEFAULT false,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_learning_events_version ON memory_learning_events(tenant_id,version_id,observed_at DESC);

ALTER TABLE memory_outcomes ADD COLUMN IF NOT EXISTS policy_version text;
ALTER TABLE memory_outcomes ADD COLUMN IF NOT EXISTS computed_confidence_delta double precision;
ALTER TABLE memory_outcomes ADD COLUMN IF NOT EXISTS learning_event_id text;

INSERT INTO memory_version_learning(
  tenant_id,version_id,item_id,version_no,content_sha256,base_confidence,learned_confidence,
  application_count,success_count,failure_count,evidence_weight,current_policy_version,last_outcome_at
)
SELECT
  v.tenant_id,v.version_id,v.item_id,v.version_no,v.content_sha256,v.confidence,v.confidence,
  COALESCE(a.application_count,0),COALESCE(a.success_count,0),COALESCE(a.failure_count,0),0,
  'LP-1.0.0',a.last_outcome_at
FROM memory_versions v
LEFT JOIN (
  SELECT ma.version_id,
         count(*) AS application_count,
         count(*) FILTER (WHERE mo.success IS TRUE) AS success_count,
         count(*) FILTER (WHERE mo.success IS FALSE) AS failure_count,
         max(mo.observed_at) AS last_outcome_at
  FROM memory_applications ma
  LEFT JOIN memory_outcomes mo ON mo.application_id=ma.application_id
  GROUP BY ma.version_id
) a ON a.version_id=v.version_id
ON CONFLICT(version_id) DO NOTHING;

DROP TRIGGER IF EXISTS trg_set_tenant ON memory_version_learning;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON memory_version_learning
FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_item();
DROP TRIGGER IF EXISTS trg_set_tenant ON memory_learning_events;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON memory_learning_events
FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_item();

DROP TRIGGER IF EXISTS trg_memory_learning_events_append_only ON memory_learning_events;
CREATE TRIGGER trg_memory_learning_events_append_only
BEFORE UPDATE OR DELETE ON memory_learning_events
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['memory_version_learning','memory_learning_events'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (memory_rls_visible(tenant_id)) WITH CHECK (memory_rls_visible(tenant_id))', t);
  END LOOP;
END $$;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.13.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
