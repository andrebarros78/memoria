import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.backup_crypto import BackupCryptoManager  # noqa: E402
from memory_permanent.erasure_ledger import ExternalErasureLedger  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

s=json.loads((ROOT/'runtime'/'p18-stage.json').read_text(encoding='utf-8-sig'));src=PostgresMemoryStore('postgresql://postgres@127.0.0.1:55439/memory_recovery',tenant_id='LEGACY',initialize=False);dst=PostgresMemoryStore('postgresql://postgres@127.0.0.1:55439/memory_restore_p18',tenant_id='LEGACY',initialize=False);pd=Path(os.getenv('ProgramData',r'C:\ProgramData'))/'MemoriaPermanente';ledger=ExternalErasureLedger(pd/'erasure-recovery-proof');crypto=BackupCryptoManager(pd/'backup-keys-recovery-proof');man=crypto.read_manifest(Path(s['manifest_path']))
def present(st):
 p='%'+s['canary']+'%'
 with st._connection() as c:return bool(c.execute('select exists(select 1 from memory_items where item_id=%s and (content_text like %s or content_json::text like %s or memory_key like %s))',(s['canary_item'],p,p,p)).fetchone()['exists'])
def q(st,sql,params=()):
 with st._connection() as c:return c.execute(sql,params).fetchone()
source_state=list(q(src,"select value from schema_meta where key='p18_status'").values())[0];m12=list(q(src,"select value from schema_meta where key='gate_m12_status'").values())[0];restore_gate=list(q(dst,"select value from schema_meta where key='restore_erasure_replay_status'").values())[0];rstate=q(dst,"select content_text,content_json from memory_items where item_id=%s",(s['canary_item'],));lt=(pd/'erasure-recovery-proof'/'ledger.jsonl').read_text(encoding='utf-8');proofdir=Path(s['manifest_path']).parent
checks={'MIGRATIONS_38_SOURCE':len(src.migrations())==38,'M12_PROVEN':m12=='PROVEN','P18_PROVEN':source_state=='PROVEN','AUDIT_CHAIN_VALID':bool(src.verify_audit_chain().get('valid',src.verify_audit_chain().get('ok',False))),'LEDGER_CHAIN_VALID':ledger.verify()['ok'] is True,'LEDGER_ITEM_ID_BLINDED':s['canary_item'] not in lt,'LEDGER_CANARY_BLINDED':s['canary'] not in lt,'SOURCE_NO_CANARY':not present(src),'RESTORE_NO_CANARY':not present(dst),'RESTORE_REPLAY_PASS':restore_gate=='PASS','MINIMAL_TOMBSTONE':rstate['content_text']=='[LEGAL_ERASURE_FINALIZED]' and set((rstate['content_json'] or {}).keys()) <= {'_erasure','erasure_id'},'BACKUP_AES_256_GCM':man.get('cipher')=='AES-256-GCM','BACKUP_KEY_SHREDDED':man.get('key_state')=='SHREDDED','MANIFEST_NO_CANARY':s['canary'] not in Path(s['manifest_path']).read_text(encoding='utf-8'),'MANIFEST_NO_ITEM_ID':s['canary_item'] not in Path(s['manifest_path']).read_text(encoding='utf-8'),'NO_PLAINTEXT_DUMPS':not any(proofdir.glob('*.dump'))}
failed=[k for k,v in checks.items() if not v];out={'generated_at':datetime.now(UTC).isoformat(),'run':s['run'],'canary_item_id':s['canary_item'],'backup_id':s['backup_id'],'erasure_id':s['erasure_id'],'restore_database':'memory_restore_p18','checks':checks,'failed_checks':failed,'RESTORE_ERASURE_NO_RESURRECTION':'PASS' if not failed else 'FAIL','P18_STATUS':source_state,'M12_STATUS':m12};path=ROOT/'evidence'/'P18_RECOVERY_TERMINAL_PROOF.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding='utf-8');print(json.dumps({'result':out['RESTORE_ERASURE_NO_RESURRECTION'],'failed_checks':failed,'evidence':str(path)},ensure_ascii=False));raise SystemExit(1 if failed else 0)
