-- V5.3 least-privilege correction for derived-artifact runtime upserts.
-- Historical migrations remain immutable. memory_app keeps no direct UPDATE
-- privilege on memory_derived_artifacts; this narrowly-scoped function derives
-- tenant authority from the referenced source versions and runs as memory_admin.

CREATE OR REPLACE FUNCTION memory_upsert_derived_artifact(
  p_artifact_id text,
  p_artifact_type text,
  p_artifact_ref text,
  p_artifact_sha256 text,
  p_status text,
  p_metadata jsonb,
  p_invalidation_reason text,
  p_source_version_ids text[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
DECLARE
  v_ctx text;
  v_source_tenant text;
  v_source_count integer;
  v_expected_count integer;
  v_tenant_count integer;
BEGIN
  v_ctx := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_ctx IS NULL THEN
    RAISE EXCEPTION 'runtime tenant context is required' USING ERRCODE='42501';
  END IF;
  IF session_user = 'memory_app' AND v_ctx = '__SYSTEM__' THEN
    RAISE EXCEPTION 'memory_app may not use system tenant in derived artifact boundary' USING ERRCODE='42501';
  END IF;

  IF p_artifact_id IS NULL OR p_artifact_id !~ '^art-[0-9a-f]{40}$' THEN
    RAISE EXCEPTION 'invalid derived artifact id' USING ERRCODE='22023';
  END IF;
  IF p_artifact_type NOT IN ('EMBEDDING','CHECKPOINT','RETRIEVAL_TRACE','SESSION_CHECKPOINT','CONTEXT_PACK') THEN
    RAISE EXCEPTION 'invalid derived artifact type: %', p_artifact_type USING ERRCODE='22023';
  END IF;
  IF p_status NOT IN ('READY','STALE','INVALID') THEN
    RAISE EXCEPTION 'invalid derived artifact status: %', p_status USING ERRCODE='22023';
  END IF;
  IF p_artifact_ref IS NULL OR btrim(p_artifact_ref) = '' OR length(p_artifact_ref) > 1000 THEN
    RAISE EXCEPTION 'invalid derived artifact reference' USING ERRCODE='22023';
  END IF;
  IF p_artifact_sha256 IS NOT NULL AND p_artifact_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid derived artifact sha256' USING ERRCODE='22023';
  END IF;
  IF p_metadata IS NULL OR octet_length(p_metadata::text) > 1048576 THEN
    RAISE EXCEPTION 'invalid derived artifact metadata' USING ERRCODE='22023';
  END IF;
  IF p_source_version_ids IS NULL OR cardinality(p_source_version_ids) = 0 OR array_position(p_source_version_ids, NULL) IS NOT NULL THEN
    RAISE EXCEPTION 'at least one source version is required' USING ERRCODE='22023';
  END IF;

  SELECT count(DISTINCT source_id)
    INTO v_expected_count
    FROM unnest(p_source_version_ids) AS ids(source_id);

  SELECT count(*), count(DISTINCT v.tenant_id), min(v.tenant_id)
    INTO v_source_count, v_tenant_count, v_source_tenant
    FROM public.memory_versions AS v
   WHERE v.version_id = ANY(p_source_version_ids);

  IF v_source_count <> v_expected_count THEN
    RAISE EXCEPTION 'one or more source versions are missing or not visible' USING ERRCODE='42501';
  END IF;
  IF v_tenant_count <> 1 OR v_source_tenant IS NULL THEN
    RAISE EXCEPTION 'cross-tenant derived artifact sources are forbidden' USING ERRCODE='42501';
  END IF;
  IF v_ctx <> '__SYSTEM__' AND v_ctx <> v_source_tenant THEN
    RAISE EXCEPTION 'derived artifact tenant mismatch' USING ERRCODE='42501';
  END IF;

  INSERT INTO public.memory_derived_artifacts(
    artifact_id,tenant_id,artifact_type,artifact_ref,artifact_sha256,status,
    metadata,invalidation_reason,staled_at,invalidated_at
  ) VALUES(
    p_artifact_id,v_source_tenant,p_artifact_type,p_artifact_ref,p_artifact_sha256,p_status,
    p_metadata,p_invalidation_reason,
    CASE WHEN p_status='STALE' THEN now() END,
    CASE WHEN p_status='INVALID' THEN now() END
  )
  ON CONFLICT(artifact_id) DO UPDATE SET
    artifact_sha256=EXCLUDED.artifact_sha256,
    status=EXCLUDED.status,
    metadata=EXCLUDED.metadata,
    invalidation_reason=EXCLUDED.invalidation_reason,
    stale_source_version_id=NULL,
    staled_at=CASE WHEN EXCLUDED.status='STALE' THEN COALESCE(memory_derived_artifacts.staled_at,now()) ELSE NULL END,
    invalidated_at=CASE WHEN EXCLUDED.status='INVALID' THEN COALESCE(memory_derived_artifacts.invalidated_at,now()) ELSE NULL END,
    updated_at=now();
END;
$$;

ALTER FUNCTION memory_upsert_derived_artifact(text,text,text,text,text,jsonb,text,text[]) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION memory_upsert_derived_artifact(text,text,text,text,text,jsonb,text,text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_upsert_derived_artifact(text,text,text,text,text,jsonb,text,text[]) TO memory_app;

-- Preserve the direct-table least-privilege invariant explicitly.
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE memory_derived_artifacts FROM memory_app;
GRANT SELECT, INSERT ON TABLE memory_derived_artifacts TO memory_app;

INSERT INTO schema_meta(key,value) VALUES('derived_artifact_runtime_boundary_version','DARB-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
