from pathlib import Path

p=Path(r'C:\RMP18\repo-base023\scripts\finalize_p18_evidence.py')
c=p.read_text(encoding='utf-8')
c=c.replace("source_state=q(src,\"select value from schema_meta where key='p18_status'\")[0]","source_state=list(q(src,\"select value from schema_meta where key='p18_status'\").values())[0]")
c=c.replace("m12=q(src,\"select value from schema_meta where key='gate_m12_status'\")[0]","m12=list(q(src,\"select value from schema_meta where key='gate_m12_status'\").values())[0]")
c=c.replace("restore_gate=q(dst,\"select value from schema_meta where key='restore_erasure_replay_status'\")[0]","restore_gate=list(q(dst,\"select value from schema_meta where key='restore_erasure_replay_status'\").values())[0]")
c=c.replace("rstate[0]=='[LEGAL_ERASURE_FINALIZED]' and set((rstate[1] or {}).keys())","rstate['content_text']=='[LEGAL_ERASURE_FINALIZED]' and set((rstate['content_json'] or {}).keys())")
p.write_text(c,encoding='utf-8');print('patched')