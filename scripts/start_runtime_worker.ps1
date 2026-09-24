[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('conversation','embedding')]
  [string]$Worker
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Py=Join-Path $Root 'runtime\api-clean\Scripts\python.exe'
$PgPass=Join-Path $Root 'runtime\secrets\pgpass.conf'
if(-not(Test-Path $Py)){throw 'Canonical runtime Python is missing'}
if(-not(Test-Path $PgPass)){throw 'Canonical runtime pgpass is missing'}
$env:PGPASSFILE=$PgPass
$env:PYTHONPATH="$Root\src"
$env:PYTHONNOUSERSITE='1'
$env:PYTHONUTF8='1'
$env:MEMORY_DATABASE_URL='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
$env:MEMORY_DSN=$env:MEMORY_DATABASE_URL
$env:MEMORY_DEFAULT_TENANT='LEGACY'
$env:MEMORY_RUNTIME_PROFILE='V5.3-PRIMARY'
$env:MEMORY_RELEASE_CHANNEL='v5.3-primary-promoted'
if($Worker -eq 'conversation'){
  & $Py (Join-Path $Root 'scripts\conversation_ingestion_worker.py') --loop --limit 100 --poll-seconds 5
}else{
  $env:MEMORY_EMBEDDING_MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
  $env:MEMORY_EMBEDDING_CACHE=Join-Path $Root 'runtime\models\fastembed'
  & $Py (Join-Path $Root 'scripts\embedding_worker.py') --loop --limit 100 --poll-seconds 15
}
exit $LASTEXITCODE
