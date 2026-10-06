$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$port=8787

function Test-CanonicalApiProcess([int]$ProcessId) {
  $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
  if(-not $proc){ return $false }
  $cmd=[string]$proc.CommandLine
  if([string]::IsNullOrWhiteSpace($cmd)){ return $false }
  $normalized=$cmd.ToLowerInvariant().Replace('/','\')
  return (
    $normalized.Contains('runtime\canonical-api\scripts\python.exe') -and
    $normalized.Contains(' -i ') -and
    $normalized.Contains(' -m uvicorn ') -and
    $normalized.Contains('memory_permanent.api:app') -and
    $normalized.Contains('--host 127.0.0.1') -and
    $normalized.Contains('--port 8787')
  )
}

$existing=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if($existing){
  $existingPid=[int]$existing.OwningProcess
  $canonical=Test-CanonicalApiProcess $existingPid
  try {
    $h=Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 5
    if($h.status -eq 'ok' -and $h.runtime_profile -eq 'V5.5-PRIMARY' -and $h.release_channel -eq 'MEMORIA_PERMANENTE_CANONICAL_1.0' -and $canonical){
      Write-Output 'API_ALREADY_HEALTHY_V55_ISOLATED'
      exit 0
    }
  } catch {}
  throw 'Port 8787 is occupied by a non-canonical, non-isolated, unhealthy, or non-V5.5 process'
}

& (Join-Path $root '.agents\recovery\start-postgres.ps1')
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }
& (Join-Path $root 'deploy\canonical\start-canonical.ps1') -Port 8787
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }

$listener=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -First 1
$listenerPid=[int]$listener.OwningProcess
if(-not (Test-CanonicalApiProcess $listenerPid)){
  throw 'Recovered API process is not the canonical isolated runtime'
}
$h=Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 10
if($h.status -ne 'ok' -or $h.runtime_profile -ne 'V5.5-PRIMARY' -or $h.release_channel -ne 'MEMORIA_PERMANENTE_CANONICAL_1.0'){
  throw 'Recovered API did not return the canonical V5.5 identity'
}
Write-Output 'API_RECOVERY_V55_ISOLATED_READY'
