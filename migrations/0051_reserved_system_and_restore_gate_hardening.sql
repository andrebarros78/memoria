-- V5.3 audit hardening: reserved system context and restore-gate boundary.
-- Runtime sessions must never gain global RLS/agent visibility by setting custom GUCs.

CREATE OR REPLACE FUNCTION public.memory_rls_visible(row_tenant text) RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT
    row_tenant = NULLIF(current_setting('app.current_tenant', true), '')
    OR (
      current_setting('app.current_tenant', true) = '__SYSTEM__'
      AND current_user <> 'memory_app'
      AND (current_user = 'postgres' OR pg_has_role(current_user, 'memory_admin', 'MEMBER'))
    )
$$;
REVOKE ALL ON FUNCTION public.memory_rls_visible(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memory_rls_visible(text) TO memory_app, memory_admin;

CREATE OR REPLACE FUNCTION public.memory_agent_visible(
  row_scope text,
  row_owner_user text,
  row_owner_agent text,
  row_project text,
  row_team text,
  row_org text
) RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT
    (
      (
        current_setting('app.current_tenant', true) = '__SYSTEM__'
        OR current_setting('app.current_agent', true) = '__SYSTEM__'
      )
      AND current_user <> 'memory_app'
      AND (current_user = 'postgres' OR pg_has_role(current_user, 'memory_admin', 'MEMBER'))
    )
    OR CASE row_scope
      WHEN 'SYSTEM_SHARED' THEN true
      WHEN 'PRIVATE_USER' THEN row_owner_user IS NOT NULL AND row_owner_user = current_setting('app.current_user_id', true)
      WHEN 'PROJECT_SHARED' THEN row_project IS NOT NULL AND row_project = current_setting('app.current_project', true)
      WHEN 'AGENT_PRIVATE' THEN row_owner_agent IS NOT NULL AND row_owner_agent = current_setting('app.current_agent', true)
      WHEN 'AGENT_TEAM' THEN row_team IS NOT NULL AND row_team = current_setting('app.current_team', true)
      WHEN 'ORGANIZATION_SHARED' THEN row_org IS NOT NULL AND row_org = current_setting('app.current_org', true)
      ELSE false
    END
$$;
REVOKE ALL ON FUNCTION public.memory_agent_visible(text,text,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memory_agent_visible(text,text,text,text,text,text) TO memory_app, memory_admin;

CREATE OR REPLACE FUNCTION public.memory_set_tenant_from_context() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v text;
BEGIN
  v := NULLIF(current_setting('app.current_tenant', true), '');
  IF v = '__SYSTEM__'
     AND current_user = 'memory_app' THEN
    RAISE EXCEPTION 'runtime role cannot use reserved system tenant context' USING ERRCODE='42501';
  END IF;
  IF NEW.tenant_id IS NULL OR NEW.tenant_id = '' THEN
    IF v IS NULL OR v = '__SYSTEM__' THEN
      NEW.tenant_id := 'LEGACY';
    ELSE
      NEW.tenant_id := v;
    END IF;
  ELSIF v IS NOT NULL AND v <> '' AND v <> '__SYSTEM__' AND NEW.tenant_id <> v THEN
    RAISE EXCEPTION 'tenant mismatch' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.memory_set_tenant_from_context() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memory_set_tenant_from_context() TO memory_app, memory_admin;

-- A restored database must always start closed. Only the administrative
-- recovery workflow may flip this to PASS after external-ledger replay.
INSERT INTO public.schema_meta(key,value)
VALUES('restore_erasure_replay_status','PENDING')
ON CONFLICT(key) DO UPDATE SET value='PENDING', updated_at=now();

GRANT SELECT ON public.legal_erasure_gate_p18, public.lifecycle_gate_m12 TO memory_admin;
GRANT SELECT, INSERT, UPDATE ON public.schema_meta TO memory_admin;

CREATE OR REPLACE FUNCTION public.memory_set_runtime_gate(p_key text, p_value text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_tenant text;
BEGIN
  v_tenant := NULLIF(current_setting('app.current_tenant', true), '');
  IF v_tenant IS NULL OR v_tenant = '__SYSTEM__' THEN
    RAISE EXCEPTION 'runtime gate mutation requires a concrete tenant' USING ERRCODE='42501';
  END IF;

  IF p_key = 'restore_erasure_replay_status' THEN
    RAISE EXCEPTION 'restore replay gate is administrative-only' USING ERRCODE='42501';
  ELSIF p_key = 'p18_status' THEN
    IF p_value <> 'PROVEN' OR NOT EXISTS(
      SELECT 1 FROM public.legal_erasure_gate_p18
      WHERE tenant_id=v_tenant AND gate_id='P18' AND status='PROVEN'
    ) THEN
      RAISE EXCEPTION 'P18 runtime gate lacks a proven tenant gate' USING ERRCODE='42501';
    END IF;
  ELSIF p_key = 'gate_m12_status' THEN
    IF p_value <> 'PROVEN' OR NOT EXISTS(
      SELECT 1 FROM public.lifecycle_gate_m12
      WHERE tenant_id=v_tenant AND gate_id='M12' AND status='PROVEN'
    ) THEN
      RAISE EXCEPTION 'M12 runtime gate lacks a proven tenant gate' USING ERRCODE='42501';
    END IF;
  ELSE
    RAISE EXCEPTION 'runtime schema_meta key is not authorized: %', p_key USING ERRCODE='42501';
  END IF;

  INSERT INTO public.schema_meta(key,value) VALUES(p_key,p_value)
  ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
END;
$$;
ALTER FUNCTION public.memory_set_runtime_gate(text,text) OWNER TO memory_admin;
REVOKE ALL ON FUNCTION public.memory_set_runtime_gate(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.memory_set_runtime_gate(text,text) TO memory_app;