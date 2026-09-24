$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA-PERMANENTE'
$PgPass=Join-Path $root 'runtime\secrets\pgpass.conf'
if(-not (Test-Path $PgPass)){ throw 'PGPASSFILE da Memória Permanente ausente.' }
$env:PGPASSFILE=$PgPass
if(Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue){ Write-Output 'PORT_8787_BUSY_STOP_BEFORE_START'; exit 2 }
$env:PYTHONPATH="$root\src"
$env:PYTHONNOUSERSITE='1'
$env:PYTHONUTF8='1'
$env:MEMORY_DATABASE_URL='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
$env:MEMORY_DSN='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
$env:MEMORY_RUNTIME_PROFILE='V5.2-PRIMARY'
$env:MEMORY_RELEASE_CHANNEL='primary-promoted'
$env:MEMORY_SEMANTIC_ENABLED='1'
$env:MEMORY_EMBEDDING_MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
$env:MEMORY_EMBEDDING_CACHE="$root\runtime\models\fastembed"
$env:MEMORY_SEMANTIC_MIN_SIMILARITY='0.40'
$py="$root\runtime\api-clean\Scripts\python.exe"
$out="$root\runtime\logs\api-8787-v52-primary.out.log"
$err="$root\runtime\logs\api-8787-v52-primary.err.log"
& $py (Join-Path $root 'scripts\runtime_preflight.py')
if($LASTEXITCODE -ne 0){ throw 'Memory runtime preflight failed; API not started.' }
$p=Start-Process -FilePath $py -ArgumentList @('-m','uvicorn','memory_permanent.api:app','--host','127.0.0.1','--port','8787') -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
Set-Content -Path "$root\.agents\v52-primary-api.pid" -Value $p.Id -Encoding ascii
Start-Sleep -Seconds 4
Write-Output ((Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/health' -TimeoutSec 10).Content)
