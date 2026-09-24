package memory.skill_creator

default allow := false

allow if {
  input.actor == "memory-steward-agent"
  input.operation == "skill-creator:validate"
  input.source_commit == "41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f"
  input.source_tree_sha256 == "1dc537d6c8667990627852cc50dab39efeecb949c67066765c6d3d525a2ff050"
  input.byte_for_byte_source_match == true
  input.network == false
  input.write_scope == ".agents/generated-skills"
}
