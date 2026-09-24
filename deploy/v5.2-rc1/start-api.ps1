$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA-PERMANENTE'
$PgPass=Join-Path $root 'runtime\secrets\pgpass.conf'
if(-not (Test-Path $PgPass)){ throw 'PGPASSFILE da Memória Permanente ausente.' }
$env:PGPASSFILE=$PgPass
$port=8792
if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){ Write-Output 'V52_RC1_API_ALREADY_LISTENING'; exit 0 }
$env:PYTHONPATH="$root\src"
$env:PYTHONNOUSERSITE='1'
$env:PYTHONUTF8='1'
$env:MEMORY_DATABASE_URL='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_rc1'
$env:MEMORY_SEMANTIC_ENABLED='1'
$env:MEMORY_EMBEDDING_MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
$env:MEMORY_EMBEDDING_CACHE="$root\runtime\models\fastembed"
$env:MEMORY_SEMANTIC_MIN_SIMILARITY='0.40'
$env:MEMORY_RUNTIME_PROFILE='V5.2-RC1'
$env:MEMORY_RELEASE_CHANNEL='rc1-parallel'
$py="$root\runtime\api-clean\Scripts\python.exe"
$out="$root\runtime\logs\api-8792-v52rc1.out.log"
$err="$root\runtime\logs\api-8792-v52rc1.err.log"
& $py (Join-Path $root 'scripts\runtime_preflight.py')
if($LASTEXITCODE -ne 0){ throw 'Memory runtime preflight failed; API not started.' }
$p=Start-Process -FilePath $py -ArgumentList @('-m','uvicorn','memory_permanent.api:app','--host','127.0.0.1','--port','8792') -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
Set-Content -Path "$root\.agents\v52-rc1-api.pid" -Value $p.Id -Encoding ascii
Write-Output ('V52_RC1_API_STARTED_PID='+$p.Id)