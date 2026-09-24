from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
EV = ROOT / '.agents' / 'evidence' / 'mission-20260904-terminal' / 'learning-loop'
EV.mkdir(parents=True, exist_ok=True)
STATE = EV / 'learning-loop-state.json'
sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.signed_client import SignedMemoryClient  # noqa: E402

BASE = os.getenv("MEMORY_API_BASE", "http://127.0.0.1:8787").rstrip("/")
client = SignedMemoryClient(BASE, 'memory-steward-agent')

def req(method,path,payload=None):
    status,data=client.request(method,path,payload)
    if status not in (200,201):
        raise RuntimeError(f'{method} {path} -> {status}: {data}')
    return data

def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run_inspector(out:Path)->int:
    cli=ROOT/'.agents'/'tools'/'mcp-inspector'/'node_modules'/'@modelcontextprotocol'/'inspector'/'clients'/'cli'/'build'/'index.js'
    cmd=['node',str(cli),str(ROOT/'runtime'/'canonical-api'/'Scripts'/'python.exe'),'-m','memory_permanent.mcp_server','--','--transport','stdio','--cwd',str(ROOT),'-e',f'PYTHONPATH={ROOT / "src"}','--method','tools/call','--tool-name','memory_summary','--tool-args-json','{}','--format','json']
    r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=30)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
    out.write_text((r.stdout or '')+(r.stderr or ''),encoding='utf-8')
    return r.returncode

run=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
mission=f'terminal-learning-{run}'
prov={'source':'terminal-learning-loop','run':run,'direct_db':False}
node_specs=[
 ('HYPOTHESIS','hypothesis:mcp-inspector-quoting',{'statement':'PowerShell/Inspector argument ordering caused tools/call failure'}),
 ('EVIDENCE','evidence:before-after',{'before_exit':1,'after_exit':0,'files':['experience-before-inspector.txt','experience-after-inspector.txt']}),
 ('DECISION','decision:target-before-delimiter',{'decision':'place target and target args before --; Inspector options after --'}),
 ('INTERVENTION','intervention:procedure',{'procedure':'procedure.json'}),
 ('RESULT','result:tools-call-exit-zero',{'success':True,'exit_code':0}),
 ('LEARNING','learning:mcp-inspector-powershell-call',{'procedure':'procedure.json','skill':'mcp-inspector-powershell-call'}),
]
nodes=[]
for typ,ref,payload in node_specs:
    nodes.append(req('POST',f'/v1/experience/missions/{mission}/nodes',{'node_type':typ,'entity_ref':ref,'payload':payload,'provenance':prov}))
relations=['EVALUATED_BY','INFORMS','IMPLEMENTED_BY','PRODUCES','DERIVES']
for a,b,rel in zip(nodes[:-1],nodes[1:],relations,strict=True):
    req('POST',f'/v1/experience/missions/{mission}/edges',{'from_node_id':a['node_id'],'relation_type':rel,'to_node_id':b['node_id'],'evidence':{'run':run,'direct_db':False}})

comp=req('POST','/v1/operations/competencies',{'competency_key':f'MCP.INSPECTOR.{run}','title':'Reliable MCP Inspector invocation','description':'Execute MCP Inspector tools/call reliably through PowerShell while preserving stdio target argument order.','domain':'MCP.OPERATIONS'})
skill=req('POST','/v1/operations/skills',{'competency_id':comp['competency_id'],'skill_key':f'MCP.INSPECTOR.POWERSHELL.{run}','title':'MCP Inspector PowerShell tools/call','description':'Procedure derived from measured failure-to-success experience.'})
skill_md=ROOT/'.agents'/'generated-skills'/'mcp-inspector-powershell-call'/'SKILL.md'
impl_sha=sha(skill_md)
version=req('POST','/v1/operations/skill-versions',{'skill_id':skill['skill_id'],'version_label':'1.0.0','implementation_version':'mcp-inspector-2.5.0/powershell-v1','implementation_sha256':impl_sha,'contract':{'input':'MCP stdio server command plus Inspector method/tool args','output':'Inspector JSON result with exit_code=0 and isError=false','direct_db':False,'procedure_ref':str(EV/'procedure.json')}})
cap=req('POST',f"/v1/operations/skill-versions/{version['skill_version_id']}/capabilities",{'capability_key':'MCP.TOOLS_CALL.RELIABLE','contract':{'transport':'stdio','client':'MCP Inspector 2.5.0','shell':'PowerShell','direct_db':False}})
replay_file=EV/'skill-replay.txt'
replay_exit=run_inspector(replay_file)
if replay_exit != 0:
    raise RuntimeError(f'replay failed exit={replay_exit}')
replay=req('POST',f"/v1/operations/skill-versions/{version['skill_version_id']}/proofs",{'proof_type':'REPLAY','result':'PASS','artifact_ref':str(replay_file),'artifact_sha256':sha(replay_file),'evidence':{'exit_code':replay_exit,'client':'MCP Inspector 2.5.0','direct_db':False}})
current=req('GET',f"/v1/operations/skill-versions/{version['skill_version_id']}")
state={'run':run,'mission_id':mission,'nodes':[n['node_id'] for n in nodes],'competency_id':comp['competency_id'],'skill_id':skill['skill_id'],'skill_version_id':version['skill_version_id'],'implementation_sha256':impl_sha,'replay_exit':replay_exit,'replay_proof_id':replay['proof_id'],'status_after_replay':current['current_status'],'recovery_pending':True}
STATE.write_text(json.dumps(state,indent=2),encoding='utf-8')
print(json.dumps(state,indent=2))
