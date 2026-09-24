[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$py=Join-Path $root 'runtime\canonical-api\Scripts\python.exe'
$adminPass=Join-Path $env:ProgramData 'MemoriaPermanente\postgres\postgres.pgpass.conf'
$workerPass=Join-Path $env:ProgramData 'MemoriaPermanente\postgres\embedding-worker.pgpass.conf'
if(-not (Test-Path $py)){throw 'Canonical runtime Python is missing.'}
if(-not (Test-Path $adminPass)){throw 'Administrative PostgreSQL credential store is missing.'}
$env:MEMORY_ADMIN_PGPASSFILE=$adminPass
$env:MEMORY_EMBEDDING_WORKER_PGPASSFILE=$workerPass
$code=@'
import os,secrets
from pathlib import Path
import psycopg
from psycopg import sql
admin=Path(os.environ['MEMORY_ADMIN_PGPASSFILE'])
out=Path(os.environ['MEMORY_EMBEDDING_WORKER_PGPASSFILE'])
os.environ['PGPASSFILE']=str(admin)
pwd=secrets.token_urlsafe(48)
with psycopg.connect('postgresql://postgres@127.0.0.1:55436/memoria_permanente_v52_primary',connect_timeout=5,autocommit=True) as c:
    c.execute(sql.SQL('ALTER ROLE memory_embedding_worker LOGIN PASSWORD {}').format(sql.Literal(pwd)))
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(f'127.0.0.1:55436:memoria_permanente_v52_primary:memory_embedding_worker:{pwd}\n',encoding='utf-8',newline='\n')
pwd=None
print('EMBEDDING_WORKER_CREDENTIAL_WRITTEN')
'@
$prior=$ErrorActionPreference
$ErrorActionPreference='Continue'
$output=& $py -I -c $code 2>&1
$rc=$LASTEXITCODE
$ErrorActionPreference=$prior
if($rc -ne 0){throw ('Embedding worker credential provisioning failed: '+(($output|Out-String).Trim()))}
& icacls.exe $workerPass /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Unable to harden embedding worker credential ACL.'}
$env:PGPASSFILE=$workerPass
$test=@'
import psycopg
with psycopg.connect('postgresql://memory_embedding_worker@127.0.0.1:55436/memoria_permanente_v52_primary',connect_timeout=5) as c:
    user=c.execute('select current_user').fetchone()[0]
    print('EMBEDDING_WORKER_DB_IDENTITY='+str(user))
    try:
        c.execute('select count(*) from public.memory_items').fetchone()
    except Exception:
        c.rollback()
        print('EMBEDDING_WORKER_DIRECT_TABLE_ACCESS=DENIED')
    else:
        raise SystemExit('embedding worker unexpectedly has direct table access')
'@
& $py -I -c $test
if($LASTEXITCODE -ne 0){throw 'Embedding worker credential validation failed.'}
Write-Output 'EMBEDDING_WORKER_PROVISION=PASS'
