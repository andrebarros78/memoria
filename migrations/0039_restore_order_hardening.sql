-- Restore-order hardening: prevent SQL-function inlining from requiring the helper
-- before pg_restore has recreated all pre-data functions. Historical migrations
-- remain immutable; this migration replaces only the executable definition.
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
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  RETURN
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
END;
$$;
