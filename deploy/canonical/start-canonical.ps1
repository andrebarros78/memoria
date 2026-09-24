[CmdletBinding()]
param(
  [int]$Port = 8790
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$base = "http://127.0.0.1:$Port"

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if($existing){
  try {
    $h = Invoke-RestMethod "$base/health" -TimeoutSec 3
    if($h.status -eq 'ok' -and $h.runtime_profile -eq 'V5.5-PRIMARY' -and $h.release_channel -eq 'MEMORIA_PERMANENTE_CANONICAL_1.0'){
      Write-Output 'CANONICAL_API_ALREADY_HEALTHY'
      Write-Output ($h | ConvertTo-Json -Compress -Depth 8)
      exit 0
    }
  } catch {}
  throw "Port $Port is already occupied by a non-canonical runtime."
}

$pgPass = Join-Path $env:ProgramData 'MemoriaPermanente\postgres\pgpass.conf'
if(-not (Test-Path $pgPass)){ throw 'Canonical PostgreSQL credential store is missing.' }
$env:PGPASSFILE = $pgPass
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:MEMORY_DATABASE_URL = 'postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
$env:MEMORY_DSN = $env:MEMORY_DATABASE_URL
$env:MEMORY_RUNTIME_PROFILE = 'V5.5-PRIMARY'
$env:MEMORY_RELEASE_CHANNEL = 'MEMORIA_PERMANENTE_CANONICAL_1.0'
$env:MEMORY_PROJECT_ROOT = $root
$env:MEMORY_V55_WINDOWS_PROVEN = '1'
$env:MEMORY_SEMANTIC_ENABLED = '1'
$env:MEMORY_EMBEDDING_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
$env:MEMORY_EMBEDDING_IDENTITY = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2|fastembed-0.8.0|mean-pooling-v1'
$env:MEMORY_EMBEDDING_CACHE = Join-Path $root 'runtime\models\fastembed'
$env:MEMORY_SEMANTIC_MIN_SIMILARITY = '0.40'

$py = Join-Path $root 'runtime\canonical-api\Scripts\python.exe'
if(-not (Test-Path $py)){ throw 'Canonical runtime Python is missing.' }
$expectedSite = [IO.Path]::GetFullPath((Join-Path $root 'runtime\canonical-api\Lib\site-packages'))
$packagePath = (& $py -I -c "import pathlib,memory_permanent; print(pathlib.Path(memory_permanent.__file__).resolve())").Trim()
if($LASTEXITCODE -ne 0){ throw 'Unable to import promoted package in isolated mode.' }
if(-not $packagePath.StartsWith($expectedSite,[StringComparison]::OrdinalIgnoreCase)){
  throw "Release integrity failure: memory_permanent resolved outside canonical runtime site-packages: $packagePath"
}
$installedVersion = (& $py -I -c "import importlib.metadata; print(importlib.metadata.version('memoria-permanente'))").Trim()
if($installedVersion -ne '0.29.3'){ throw "Release integrity failure: expected 0.29.3, got $installedVersion" }

& $py -I -m memory_permanent.runtime_preflight
if($LASTEXITCODE -ne 0){ throw 'Canonical runtime preflight failed.' }

# Semantic retrieval is an optional capability, never a startup dependency for the sovereign core.
# Prewarm strictly offline so a restart cannot block the first context request on a model download.
$semanticMode = 'SEMANTIC_READY_OFFLINE'
$oldOffline = $env:HF_HUB_OFFLINE
try {
  $probeCode = "import os; from fastembed import TextEmbedding; m=TextEmbedding(model_name=os.environ['MEMORY_EMBEDDING_MODEL'], cache_dir=os.environ['MEMORY_EMBEDDING_CACHE'], threads=2, local_files_only=True); print(len(next(iter(m.embed(['startup probe'])))))"
  $probeEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $probe = ((& $py -I -c $probeCode 2>$null) -join "").Trim()
  $probeRc = $LASTEXITCODE
  $ErrorActionPreference = $probeEap
  Write-Output ("CANONICAL_SEMANTIC_PROBE_RC="+$probeRc+" LEN="+$probe.Length)
  if($probeRc -ne 0 -or -not $probe){
    $env:MEMORY_SEMANTIC_ENABLED = '0'
    $semanticMode = 'LEXICAL_DEGRADED_NO_LOCAL_MODEL'
    if($null -eq $oldOffline){ Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue } else { $env:HF_HUB_OFFLINE = $oldOffline }
  } else {
    $env:HF_HUB_OFFLINE = '1'
  }
} catch {
  if($probeEap){ $ErrorActionPreference = $probeEap }
  Write-Output ("CANONICAL_SEMANTIC_PROBE_EXCEPTION="+$_.Exception.GetType().Name)
  $env:MEMORY_SEMANTIC_ENABLED = '0'
  $semanticMode = 'LEXICAL_DEGRADED_NO_LOCAL_MODEL'
  if($null -eq $oldOffline){ Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue } else { $env:HF_HUB_OFFLINE = $oldOffline }
}
Write-Output ("CANONICAL_RETRIEVAL_MODE=" + $semanticMode)

$logs = Join-Path $root 'runtime\logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$out = Join-Path $logs "canonical-api-$Port.out.log"
$err = Join-Path $logs "canonical-api-$Port.err.log"
$p = Start-Process -FilePath $py -ArgumentList @('-I','-m','uvicorn','memory_permanent.api:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
Set-Content -Path (Join-Path $root 'runtime\canonical-api.pid') -Value $p.Id -Encoding ascii

$deadline = (Get-Date).AddSeconds(30)
$lastError = $null
do {
  Start-Sleep -Milliseconds 500
  $p.Refresh()
  if($p.HasExited){
    $tail = if(Test-Path $err){ (Get-Content $err -Tail 60) -join "`n" } else { 'no stderr log' }
    throw "Canonical API exited before readiness (exit=$($p.ExitCode)). $tail"
  }
  try {
    $h = Invoke-RestMethod "$base/health" -TimeoutSec 2
    if($h.status -eq 'ok' -and $h.runtime_profile -eq 'V5.5-PRIMARY' -and $h.release_channel -eq 'MEMORIA_PERMANENTE_CANONICAL_1.0'){
      Write-Output 'CANONICAL_API_READY'
      Write-Output ($h | ConvertTo-Json -Compress -Depth 8)
      exit 0
    }
    $lastError = "unexpected health identity: $($h | ConvertTo-Json -Compress -Depth 4)"
  } catch {
    $lastError = $_.Exception.Message
  }
} while((Get-Date) -lt $deadline)

try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
throw "Canonical API readiness timed out after 30s. Last error: $lastError"




