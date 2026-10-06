$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'
$PgPass=Join-Path $root 'runtime\secrets\pgpass.conf'
if(-not (Test-Path $PgPass)){ throw 'PGPASSFILE da Memória Permanente ausente.' }
$env:PGPASSFILE=$PgPass
$v4Root='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0-V4-ROLLBACK'
if(Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue){ Write-Output 'PORT_8787_BUSY_STOP_BEFORE_ROLLBACK'; exit 2 }
$env:PYTHONPATH="$v4Root\src"
$env:PYTHONNOUSERSITE='1'
$env:PYTHONUTF8='1'
$env:MEMORY_DATABASE_URL='postgresql://memory_app@127.0.0.1:55436/memoria_permanente'
$env:MEMORY_DSN='postgresql://memory_app@127.0.0.1:55436/memoria_permanente'
$env:MEMORY_RUNTIME_PROFILE='V4-ROLLBACK'
$env:MEMORY_RELEASE_CHANNEL='v4-baseline-rollback'
$env:MEMORY_SEMANTIC_ENABLED='1'
$env:MEMORY_EMBEDDING_MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
$env:MEMORY_EMBEDDING_CACHE="$root\runtime\models\fastembed"
$env:MEMORY_SEMANTIC_MIN_SIMILARITY='0.40'
$py="$root\runtime\api-clean\Scripts\python.exe"
$out="$root\runtime\logs\api-8787-v4-rollback.out.log"
$err="$root\runtime\logs\api-8787-v4-rollback.err.log"
$p=Start-Process -FilePath $py -ArgumentList @('-m','uvicorn','memory_permanent.api:app','--host','127.0.0.1','--port','8787') -WorkingDirectory $v4Root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
Set-Content -Path "$root\.agents\v4-rollback-api.pid" -Value $p.Id -Encoding ascii
Start-Sleep -Seconds 4
Write-Output ((Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/health' -TimeoutSec 10).Content)
