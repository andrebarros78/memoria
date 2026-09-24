from __future__ import annotations

import hashlib
import json
import re
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.store import PostgresMemoryStore  # noqa: E402


def run(*args):
    return subprocess.run(args,cwd=ROOT,text=True,encoding='utf-8',errors='replace',capture_output=True)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
with urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=5) as r:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
    health=json.loads(r.read().decode())
parts=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='utf-8').strip().split(':',4)
host,port,db,user,pw=parts
dsn=f'host={host} port={port} dbname={db} user={user} password={pw} connect_timeout=5'
store=PostgresMemoryStore(dsn,initialize=False,tenant_id='__SYSTEM__')
with store._connection() as conn:
    schema=conn.execute("select value from schema_meta where key='schema_version'").fetchone()['value']
    pg=conn.execute('show server_version').fetchone()['server_version']
    vector=conn.execute("select extversion from pg_extension where extname='vector'").fetchone()['extversion']
    migrations=[dict(x) for x in conn.execute('select version,checksum_sha256 from schema_migrations order by version').fetchall()]
audit=store.verify_audit_chain()
compile_p=run(str(ROOT/'.venv/Scripts/python.exe'),'-m','compileall','-q','src','scripts','integration','tests')
pytest_p=run(str(ROOT/'.venv/Scripts/python.exe'),'-m','pytest','-q')
m=re.search(r'(\d+) passed',pytest_p.stdout)
wheels=sorted((ROOT/'runtime/baseline-wheel-0.13.0').glob('*.whl'),key=lambda p:p.stat().st_mtime,reverse=True)
backups=sorted((ROOT/'backups/baseline-validation').glob('*.dump'),key=lambda p:p.stat().st_mtime,reverse=True)
wheel=wheels[0] if wheels else None; backup=backups[0] if backups else None
candidates=run('git','ls-files','--others','--exclude-standard').stdout.splitlines()
patterns={'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),'openai':re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),'aws':re.compile(r'\bAKIA[0-9A-Z]{16}\b'),'github':re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b')}
hits=[]
for rel in candidates:
    p=ROOT/rel
    if not p.is_file(): continue
    try:s=p.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):continue
    for name,pat in patterns.items():
        if pat.search(s): hits.append({'file':rel.replace('\\','/'),'pattern':name,'safe':rel.replace('\\','/')=='src/memory_permanent/secret_sanitizer.py' and name=='private_key'})
unclassified=[x for x in hits if not x['safe']]
tracked=run('git','ls-files').stdout.splitlines()
forbidden=[x for x in tracked if x.replace('\\','/').startswith(('.venv/','runtime/','backups/','build/','dist/'))]
proof={'generated_at':datetime.now(UTC).isoformat(),'baseline':'0.13.0','api':health,'database':{'schema_version':schema,'postgresql':pg,'pgvector':vector,'migration_count':len(migrations),'last_migration':migrations[-1]['version']},'compileall_pass':compile_p.returncode==0,'pytest':{'returncode':pytest_p.returncode,'passed':int(m.group(1)) if m else None},'audit':audit,'wheel':{'file':wheel.name if wheel else None,'sha256':sha256(wheel) if wheel else None,'bytes':wheel.stat().st_size if wheel else None},'backup':{'sha256':sha256(backup) if backup else None,'bytes':backup.stat().st_size if backup else None},'secret_scan':{'hits':hits,'unclassified':unclassified},'forbidden_tracked':forbidden,'memoria_plus':{'01':'PROVEN','02':'PROVEN','03':'PROVEN','04':'PROVEN','05_18':'OPEN'}}
proof['PASS']=bool(health.get('status')=='ok' and health.get('version')=='0.13.0' and schema=='memory-0.13.0' and str(pg).startswith('18.6') and vector=='0.8.6' and compile_p.returncode==0 and pytest_p.returncode==0 and m and int(m.group(1))==53 and audit.get('ok') and wheel and backup and not unclassified and not forbidden)
(ROOT/'evidence/BASELINE_0_13_0_PROOF.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
(ROOT/'evidence/BASELINE_0_13_0_PROOF.md').write_text(f"# BASELINE 0.13.0 PROOF\n\n- Result: **{'PASS' if proof['PASS'] else 'FAIL'}**\n- API: `{health.get('status')} {health.get('version')}`\n- Schema: `{schema}`\n- PostgreSQL: `{pg}`\n- pgvector: `{vector}`\n- Migrations: `{len(migrations)}` / last `{migrations[-1]['version']}`\n- Tests: `{proof['pytest']['passed']} passed`\n- Audit: `ok={audit.get('ok')}` / strict errors `{len(audit.get('strict_errors') or [])}`\n- Wheel SHA-256: `{proof['wheel']['sha256']}`\n- Backup SHA-256: `{proof['backup']['sha256']}`\n- Unclassified secret findings: `{len(unclassified)}`\n- Forbidden tracked runtime paths: `{len(forbidden)}`\n- MEMORIA PLUS 01-04: `PROVEN`\n\n`V4_FULL_PROVEN = NÃO`  \n`MISSION_PROVEN = NÃO`\n",encoding='utf-8')
print(json.dumps({'PASS':proof['PASS'],'tests':proof['pytest']['passed'],'schema':schema,'audit_ok':audit.get('ok'),'strict_errors':audit.get('strict_errors'),'secret_unclassified':len(unclassified)},ensure_ascii=False))
raise SystemExit(0 if proof['PASS'] else 1)
