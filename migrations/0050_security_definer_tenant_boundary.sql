-- V5.3 audit hardening: constrain legacy SECURITY DEFINER runtime entrypoints.
-- Historical functions are preserved by rename; runtime receives non-superuser guard wrappers.

-- Base erasure primitive is internal-only. It remains owned by postgres but is not callable by runtime.
ALTER FUNCTION public.memory_apply_legal_erasure(text,text,text,text)
  SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.memory_apply_legal_erasure(text,text,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.memory_apply_legal_erasure(text,text,text,text) FROM memory_app;

-- Legal-erasure entrypoint: rename legacy superuser implementation and expose a guarded wrapper.
ALTER FUNCTION public.memory_apply_legal_erasure_extended(text,text,text,text)
  RENAME TO memory_apply_legal_erasure_extended_internal_0049;
ALTER FUNCTION public.memory_apply_legal_erasure_extended_internal_0049(text,text,text,text)
  SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.memory_apply_legal_erasure_extended_internal_0049(text,text,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.memory_apply_legal_erasure_extended_internal_0049(text,text,text,text) FROM memory_app;
GRANT EXECUTE ON FUNCTION public.memory_apply_legal_erasure_extended_internal_0049(text,text,text,text) TO memory_admin;

GRANT SELECT ON public.memory_items TO memory_admin;

CREATE FUNCTION public.memory_apply_legal_erasure_extended(
  p_item_id text,
  p_erasure_id text,
  p_blinded_fingerprint text,
  p_tombstone_sha text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_current_tenant text;
  v_target_tenant text;
BEGIN
  v_current_tenant := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_current_tenant IS NULL OR v_current_tenant = '__SYSTEM__' THEN
    RAISE EXCEPTION 'legal erasure requires a concrete tenant boundary' USING ERRCODE='42501';
  END IF;

  SELECT tenant_id INTO v_target_tenant
  FROM public.memory_items
  WHERE item_id = p_item_id;

  IF v_target_tenant IS NULL OR v_target_tenant <> v_current_tenant THEN
    RAISE EXCEPTION 'cross-tenant legal erasure is forbidden' USING ERRCODE='42501';
  END IF;

  PERFORM public.memory_apply_legal_erasure_extended_internal_0049(
    p_item_id, p_erasure_id, p_blinded_fingerprint, p_tombstone_sha
  );
END;
$$;
ALTER FUNCTION public.memory_apply_legal_erasure_extended(text,text,text,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION public.memory_apply_legal_erasure_extended(text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memory_apply_legal_erasure_extended(text,text,text,text) TO memory_app;

-- Ontology transition entrypoint: guard item tenant before invoking the historical implementation.
ALTER FUNCTION public.memory_apply_ontology_transition(text,text,text,text,text,jsonb)
  RENAME TO memory_apply_ontology_transition_internal_0049;
ALTER FUNCTION public.memory_apply_ontology_transition_internal_0049(text,text,text,text,text,jsonb)
  SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.memory_apply_ontology_transition_internal_0049(text,text,text,text,text,jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.memory_apply_ontology_transition_internal_0049(text,text,text,text,text,jsonb) FROM memory_app;
GRANT EXECUTE ON FUNCTION public.memory_apply_ontology_transition_internal_0049(text,text,text,text,text,jsonb) TO memory_admin;

CREATE FUNCTION public.memory_apply_ontology_transition(
  p_transition_id text,
  p_item_id text,
  p_to_category text,
  p_actor text,
  p_reason text,
  p_evidence jsonb
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_current_tenant text;
  v_target_tenant text;
BEGIN
  v_current_tenant := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_current_tenant IS NULL OR v_current_tenant = '__SYSTEM__' THEN
    RAISE EXCEPTION 'ontology transition requires a concrete tenant boundary' USING ERRCODE='42501';
  END IF;

  SELECT tenant_id INTO v_target_tenant
  FROM public.memory_items
  WHERE item_id = p_item_id;

  IF v_target_tenant IS NULL OR v_target_tenant <> v_current_tenant THEN
    RAISE EXCEPTION 'cross-tenant ontology transition is forbidden' USING ERRCODE='42501';
  END IF;

  RETURN public.memory_apply_ontology_transition_internal_0049(
    p_transition_id, p_item_id, p_to_category, p_actor, p_reason, p_evidence
  );
END;
$$;
ALTER FUNCTION public.memory_apply_ontology_transition(text,text,text,text,text,jsonb) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION public.memory_apply_ontology_transition(text,text,text,text,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memory_apply_ontology_transition(text,text,text,text,text,jsonb) TO memory_app;

-- Lifecycle finalization entrypoint: bind request + item + tenant before privileged finalization.
ALTER FUNCTION public.memory_lifecycle_finalize_payload(text,text,text)
  RENAME TO memory_lifecycle_finalize_payload_internal_0049;
ALTER FUNCTION public.memory_lifecycle_finalize_payload_internal_0049(text,text,text)
  SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.memory_lifecycle_finalize_payload_internal_0049(text,text,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.memory_lifecycle_finalize_payload_internal_0049(text,text,text) FROM memory_app;
GRANT EXECUTE ON FUNCTION public.memory_lifecycle_finalize_payload_internal_0049(text,text,text) TO memory_admin;

GRANT SELECT ON public.lifecycle_requests TO memory_admin;

CREATE FUNCTION public.memory_lifecycle_finalize_payload(
  p_request_id text,
  p_item_id text,
  p_final_hash text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_current_tenant text;
  v_request_tenant text;
  v_request_item text;
BEGIN
  v_current_tenant := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_current_tenant IS NULL OR v_current_tenant = '__SYSTEM__' THEN
    RAISE EXCEPTION 'lifecycle finalization requires a concrete tenant boundary' USING ERRCODE='42501';
  END IF;

  SELECT tenant_id, item_id INTO v_request_tenant, v_request_item
  FROM public.lifecycle_requests
  WHERE request_id = p_request_id;

  IF v_request_tenant IS NULL OR v_request_tenant <> v_current_tenant OR v_request_item <> p_item_id THEN
    RAISE EXCEPTION 'cross-tenant lifecycle finalization is forbidden' USING ERRCODE='42501';
  END IF;

  PERFORM public.memory_lifecycle_finalize_payload_internal_0049(p_request_id, p_item_id, p_final_hash);
END;
$$;
ALTER FUNCTION public.memory_lifecycle_finalize_payload(text,text,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION public.memory_lifecycle_finalize_payload(text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memory_lifecycle_finalize_payload(text,text,text) TO memory_app;
