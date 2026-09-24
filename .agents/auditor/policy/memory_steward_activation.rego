package memory.steward_activation

default allow := false

allow if {
  input.actor == "memory-steward-agent"
  input.operation == "skill:activate"
  input.operational_status == "PROVEN"
  input.evaluation_passed == true
  input.replay_pass == true
  input.recovery_pass == true
  input.direct_db == false
  input.implementation_sha256_match == true
  input.measured_improvement > 0
}
