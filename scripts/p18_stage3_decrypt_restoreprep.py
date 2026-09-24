import hashlib
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.backup_crypto import BackupCryptoManager  # noqa: E402

s=json.loads((ROOT/'runtime'/'p18-stage.json').read_text(encoding='utf-8-sig'));man=Path(s['manifest_path']);tmp=man.parent/(s['backup_id']+'.restore.tmp.dump');keys=Path(os.getenv('ProgramData',r'C:\ProgramData'))/'MemoriaPermanente'/'backup-keys-recovery-proof';BackupCryptoManager(keys).decrypt_backup(manifest_path=man,output_path=tmp);sha=hashlib.sha256(tmp.read_bytes()).hexdigest();s.update({'restore_tmp_dump':str(tmp),'decrypt_sha_match':sha==s['dump_sha256']});(ROOT/'runtime'/'p18-stage.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'decrypt_sha_match':sha==s['dump_sha256'],'tmp_bytes':tmp.stat().st_size}))
