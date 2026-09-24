-- Canonical 1.0 hardening: dedicated least-privilege discovery identity for
-- the embedding worker. The role can discover only access-context metadata;
-- canonical memory content remains behind the normal memory_app RLS boundary.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='memory_embedding_worker') THEN
    CREATE ROLE memory_embedding_worker
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  ELSE
    ALTER ROLE memory_embedding_worker
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM memory_embedding_worker;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM memory_embedding_worker;
GRANT USAGE ON SCHEMA public TO memory_embedding_worker;

CREATE OR REPLACE FUNCTION public.memory_embedding_access_contexts(
  p_model_id text,
  p_limit integer DEFAULT 1000
)
RETURNS TABLE(
  tenant_id text,
  sharing_scope text,
  owner_user_id text,
  owner_agent_id text,
  project_id text,
  team_id text,
  organization_id text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_limit integer;
BEGIN
  IF session_user <> 'memory_embedding_worker' THEN
    RAISE EXCEPTION 'embedding context discovery requires dedicated database identity' USING ERRCODE='42501';
  END IF;
  IF p_model_id IS NULL OR btrim(p_model_id) = '' OR length(p_model_id) > 300 THEN
    RAISE EXCEPTION 'invalid embedding model id' USING ERRCODE='22023';
  END IF;

  v_limit := LEAST(GREATEST(COALESCE(p_limit, 1000), 1), 5000);
  RETURN QUERY
  SELECT DISTINCT
    m.tenant_id,
    m.sharing_scope,
    m.owner_user_id,
    m.owner_agent_id,
    m.project_id,
    m.team_id,
    m.organization_id
  FROM public.memory_items m
  LEFT JOIN public.memory_embeddings e ON e.item_id=m.item_id
  WHERE public.memory_bitemporal_visible(
      m.valid_from,m.valid_to,m.observed_at,m.created_at,now(),now()
    )
    AND (
      e.item_id IS NULL
      OR e.model_id<>p_model_id
      OR e.content_sha256<>m.content_sha256
      OR e.status<>'READY'
    )
  ORDER BY
    m.tenant_id,m.sharing_scope,m.project_id,m.owner_user_id,
    m.owner_agent_id,m.team_id,m.organization_id
  LIMIT v_limit;
END;
$$;

REVOKE ALL ON FUNCTION public.memory_embedding_access_contexts(text,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.memory_embedding_access_contexts(text,integer) FROM memory_app;
REVOKE ALL ON FUNCTION public.memory_embedding_access_contexts(text,integer) FROM memory_admin;
GRANT EXECUTE ON FUNCTION public.memory_embedding_access_contexts(text,integer) TO memory_embedding_worker;
