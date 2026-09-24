package memory.auditor

default allow := false

allow if {
  input.actor == "retrieval-quality-auditor"
  input.client_id == "wmcp-memory-bridge"
  input.operation == "memory:context"
  input.read_only == true
  input.direct_db == false
  input.telemetry.phoenix_health == true
  input.metrics.pass_rate >= input.thresholds.pass_rate
  input.metrics.scope_leaks <= input.thresholds.scope_leaks
  input.metrics.api_failures <= input.thresholds.api_failures
  input.metrics.conflicts <= input.thresholds.conflicts
  input.metrics.max_case_latency_ms <= input.thresholds.max_case_latency_ms
}
