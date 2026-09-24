package memory.retrieval_quality_promotion

default allow := false

allow if {
  input.actor == "retrieval-quality-agent"
  input.operation == "retrieval:promote"
  input.status == "PASS"
  input.direct_db == false
  input.golden_set_sha256_match == true
  input.baseline_ref_present == true
  input.trace_coverage == 1
  input.metrics.precision >= input.thresholds.min_precision
  input.metrics.recall >= input.thresholds.min_recall
  input.metrics.case_pass_rate >= input.thresholds.min_case_pass_rate
  input.metrics.forbidden_hit_rate <= input.thresholds.max_forbidden_hit_rate
  input.metrics.scope_violation_rate <= input.thresholds.max_scope_violation_rate
  input.metrics.temporal_violation_rate <= input.thresholds.max_temporal_violation_rate
  input.metrics.authority_violation_rate <= input.thresholds.max_authority_violation_rate
}