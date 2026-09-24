import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.backup_crypto import BackupCryptoManager  # noqa: E402

s=json.loads((ROOT/'runtime'/'p18-stage.json').read_text(encoding='utf-8-sig'));dump=Path(s['dump_path']);proof=dump.parent;bid='p18-pre-erasure-'+s['run'];enc=proof/(bid+'.mpb');man=proof/(bid+'.encrypted.manifest.json');keys=Path(os.getenv('ProgramData',r'C:\ProgramData'))/'MemoriaPermanente'/'backup-keys-recovery-proof';m=BackupCryptoManager(keys).encrypt_dump(dump_path=dump,encrypted_path=enc,manifest_path=man,backup_id=bid,generated_at=datetime.now(UTC),metadata={'schema':'memory-0.26.0','release':'0.26.1-recovery','database':'memory_recovery','purpose':'P18_NO_RESURRECTION_PROOF','backup_policy':'BKP-1.0.0'});dump.unlink();s.update({'backup_id':bid,'encrypted_path':str(enc),'manifest_path':str(man),'backup_cipher':m['cipher'],'plaintext_removed':not dump.exists()});(ROOT/'runtime'/'p18-stage.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'backup_id':bid,'cipher':m['cipher'],'plaintext_removed':not dump.exists(),'ciphertext_sha256':m['ciphertext_sha256']}))
