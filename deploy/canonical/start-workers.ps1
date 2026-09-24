[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$py=Join-Path $root 'runtime\canonical-api\Scripts\python.exe'
if(-not (Test-Path $py)){throw 'Canonical runtime Python is missing.'}
$pgPass=Join-Path $env:ProgramData 'MemoriaPermanente\postgres\pgpass.conf'
if(-not (Test-Path $pgPass)){throw 'Canonical PostgreSQL credential store is missing.'}
$discoveryPass=Join-Path $env:ProgramData 'MemoriaPermanente\postgres\embedding-worker.pgpass.conf'
if(-not (Test-Path $discoveryPass)){throw 'Embedding worker discovery credential store is missing.'}
$env:PGPASSFILE=$pgPass
$env:MEMORY_EMBEDDING_DISCOVERY_PGPASSFILE=$discoveryPass
$env:PYTHONNOUSERSITE='1'
$env:PYTHONUTF8='1'
$env:MEMORY_DATABASE_URL='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
$env:MEMORY_DSN=$env:MEMORY_DATABASE_URL
$env:MEMORY_PROJECT_ROOT=$root
$env:MEMORY_EMBEDDING_MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
$env:MEMORY_EMBEDDING_IDENTITY='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2|fastembed-0.8.0|mean-pooling-v1'
$env:MEMORY_EMBEDDING_CACHE=Join-Path $root 'runtime\models\fastembed'
$env:HF_HUB_OFFLINE='1'
$logs=Join-Path $root 'runtime\logs'
New-Item -ItemType Directory -Force $logs|Out-Null

# One-shot probes must pass before persistent loops are started.
& $py -I (Join-Path $root 'scripts\conversation_ingestion_worker.py') --limit 10
if($LASTEXITCODE -ne 0){throw 'Canonical conversation ingestion worker probe failed.'}
& $py -I (Join-Path $root 'scripts\embedding_worker.py') --limit 10
if($LASTEXITCODE -ne 0){throw 'Canonical embedding worker probe failed.'}

$canonicalRuntime=[IO.Path]::GetFullPath((Join-Path $root 'runtime\canonical-api'))
$procs=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.CommandLine -and ([IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith($canonicalRuntime,[StringComparison]::OrdinalIgnoreCase) }
$ingestScript=[IO.Path]::GetFullPath((Join-Path $root 'scripts\conversation_ingestion_worker.py'))
$embedScript=[IO.Path]::GetFullPath((Join-Path $root 'scripts\embedding_worker.py'))
$ingest=$procs | Where-Object { $_.CommandLine -like "*$ingestScript*--loop*" } | Select-Object -First 1
$embed=$procs | Where-Object { $_.CommandLine -like "*$embedScript*--loop*" } | Select-Object -First 1
if(-not $ingest){
  $ingestArgs='-I "'+$ingestScript+'" --loop --poll-seconds 5 --limit 100'
  $p=Start-Process -FilePath $py -ArgumentList $ingestArgs -WorkingDirectory $root -RedirectStandardOutput (Join-Path $logs 'canonical-ingestion.out.log') -RedirectStandardError (Join-Path $logs 'canonical-ingestion.err.log') -PassThru -WindowStyle Hidden
  Write-Output ('CANONICAL_INGESTION_STARTED_PID='+$p.Id)
}else{Write-Output ('CANONICAL_INGESTION_ALREADY_RUNNING_PID='+$ingest.ProcessId)}
if(-not $embed){
  $embedArgs='-I "'+$embedScript+'" --loop --poll-seconds 10 --limit 100'
  $p=Start-Process -FilePath $py -ArgumentList $embedArgs -WorkingDirectory $root -RedirectStandardOutput (Join-Path $logs 'canonical-embedding.out.log') -RedirectStandardError (Join-Path $logs 'canonical-embedding.err.log') -PassThru -WindowStyle Hidden
  Write-Output ('CANONICAL_EMBEDDING_STARTED_PID='+$p.Id)
}else{Write-Output ('CANONICAL_EMBEDDING_ALREADY_RUNNING_PID='+$embed.ProcessId)}
Start-Sleep -Seconds 2
$after=Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like '*MEMORIA_PERMANENTE_CANONICAL_1.0*' }
$ingestAlive=$after | Where-Object { $_.CommandLine -like "*$ingestScript*--loop*" } | Select-Object -First 1
$embedAlive=$after | Where-Object { $_.CommandLine -like "*$embedScript*--loop*" } | Select-Object -First 1
if(-not $ingestAlive){throw 'Canonical ingestion loop did not remain alive after startup.'}
if(-not $embedAlive){throw 'Canonical embedding loop did not remain alive after startup.'}
Write-Output 'CANONICAL_WORKERS_READY'
