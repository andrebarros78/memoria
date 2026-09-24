import json
from memory_permanent.memory_steward_agent import MemoryStewardAgent
from memory_permanent.signed_client import SignedMemoryClient
state=json.load(open(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\.agents\evidence\mission-20260904-terminal\learning-loop\learning-loop-state.json",encoding="utf-8"))
c=SignedMemoryClient("http://127.0.0.1:8787","memory-steward-agent")
s,current=c.request("GET","/v1/operations/skill-versions/"+state["skill_version_id"],None,timeout=15)
if s!=200: raise SystemExit(f"GET failed {s}: {current}")
proofs={p["proof_type"] for p in current.get("proofs",[]) if p.get("result")=="PASS"}
decision=MemoryStewardAgent().activation_decision(operational_status=current["current_status"],evaluation_passed=True,policy_allowed=True,implementation_sha256=state["implementation_sha256"],proof_types_passed=proofs)
print(json.dumps({"status":current["current_status"],"proofs":sorted(proofs),"activation_allowed":decision.allow,"reasons":list(decision.reasons)},ensure_ascii=False))
raise SystemExit(0 if decision.allow else 1)
