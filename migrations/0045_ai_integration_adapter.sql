-- V5.3 AI Integration Adapter.
CREATE TABLE IF NOT EXISTS ai_integration_suggestions(
  suggestion_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT current_setting('app.current_tenant',true),
  external_system_id text NOT NULL,
  external_trace_id text NOT NULL,
  suggestion_type text NOT NULL CHECK(suggestion_type IN ('MEMORY_CREATE','MEMORY_REVISE','MEMORY_CLASSIFY','MEMORY_ARCHIVE','DUPLICATE_REVIEW','CONFLICT_REVIEW','SUMMARY')),
  target_item_id text NULL,
  raw_payload jsonb NOT NULL,
  normalized_payload jsonb NOT NULL,
  risk_level text NOT NULL CHECK(risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, external_system_id, external_trace_id)
);

CREATE TABLE IF NOT EXISTS ai_integration_decisions(
  decision_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT current_setting('app.current_tenant',true),
  suggestion_id text NOT NULL REFERENCES ai_integration_suggestions(suggestion_id),
  decision text NOT NULL CHECK(decision IN ('ACCEPTED','REJECTED','PROMOTED')),
  rationale text NOT NULL DEFAULT '',
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  promoted_item_id text NULL,
  evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION ai_integration_evidence_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'AI integration evidence is append-only' USING ERRCODE='55000';
END;
$$;
DROP TRIGGER IF EXISTS trg_ai_integration_suggestions_append_only ON ai_integration_suggestions;
CREATE TRIGGER trg_ai_integration_suggestions_append_only BEFORE UPDATE OR DELETE ON ai_integration_suggestions FOR EACH ROW EXECUTE FUNCTION ai_integration_evidence_append_only();
DROP TRIGGER IF EXISTS trg_ai_integration_decisions_append_only ON ai_integration_decisions;
CREATE TRIGGER trg_ai_integration_decisions_append_only BEFORE UPDATE OR DELETE ON ai_integration_decisions FOR EACH ROW EXECUTE FUNCTION ai_integration_evidence_append_only();

ALTER TABLE ai_integration_suggestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_integration_suggestions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ai_integration_suggestions;
CREATE POLICY tenant_isolation ON ai_integration_suggestions USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
ALTER TABLE ai_integration_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_integration_decisions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ai_integration_decisions;
CREATE POLICY tenant_isolation ON ai_integration_decisions USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

CREATE INDEX IF NOT EXISTS idx_ai_integration_suggestions_created ON ai_integration_suggestions(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_integration_suggestions_type ON ai_integration_suggestions(tenant_id, suggestion_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_integration_decisions_suggestion ON ai_integration_decisions(tenant_id, suggestion_id, created_at DESC);
INSERT INTO schema_meta(key,value) VALUES('ai_integration_adapter_contract','V5.3_AI_INTEGRATION_ADAPTER') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
