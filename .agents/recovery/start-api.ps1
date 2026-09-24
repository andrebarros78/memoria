$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA-PERMANENTE'
$port=8787

function Test-CanonicalApiProcess([int]$ProcessId) {
  $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
  if(-not $proc){ return $false }
  $cmd=[string]$proc.CommandLine
  if([string]::IsNullOrWhiteSpace($cmd)){ return $false }
  $normalized=$cmd.ToLowerInvariant().Replace('/','\')
  return (
    $normalized.Contains('runtime\api-clean\scripts\python.exe') -and
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
    if($h.status -eq 'ok' -and $h.runtime_profile -eq 'V5.3-PRIMARY' -and $h.release_channel -eq 'v5.3-primary-promoted' -and $canonical){
      Write-Output 'API_ALREADY_HEALTHY_V53_ISOLATED'
      exit 0
    }
  } catch {}
  throw 'Port 8787 is occupied by a non-canonical, non-isolated, unhealthy, or non-V5.3 process'
}

& "$root\.agents\recovery\start-postgres.ps1"
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }
& "$root\deploy\v5.3\start-primary-v53.ps1"
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }

$listener=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -First 1
$listenerPid=[int]$listener.OwningProcess
if(-not (Test-CanonicalApiProcess $listenerPid)){
  throw 'Recovered API process is not the canonical isolated api-clean runtime'
}
$h=Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 10
if($h.status -ne 'ok' -or $h.runtime_profile -ne 'V5.3-PRIMARY' -or $h.release_channel -ne 'v5.3-primary-promoted'){
  throw 'Recovered API did not return the canonical V5.3 identity'
}
Write-Output 'API_RECOVERY_V53_ISOLATED_READY'
