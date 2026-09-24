[CmdletBinding()]
param(
  [int]$Port = 8790
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$base = "http://127.0.0.1:$Port"
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if(-not $conn){
  Remove-Item (Join-Path $root 'runtime\canonical-api.pid') -Force -ErrorAction SilentlyContinue
  Write-Output 'CANONICAL_API_ALREADY_STOPPED'
  exit 0
}

try {
  $h = Invoke-RestMethod "$base/health" -TimeoutSec 3
} catch {
  throw "Port $Port is listening but canonical identity could not be verified. Refusing blind stop."
}
if($h.status -ne 'ok' -or $h.runtime_profile -ne 'V5.5-PRIMARY' -or $h.release_channel -ne 'MEMORIA_PERMANENTE_CANONICAL_1.0'){
  throw "Port $Port is not the canonical runtime. Refusing stop."
}

$canonicalRuntime = [IO.Path]::GetFullPath((Join-Path $root 'runtime\canonical-api'))
$targets = Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -and $_.CommandLine -and
  ([IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith($canonicalRuntime,[StringComparison]::OrdinalIgnoreCase) -and
  $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match "--port\s+$Port"
}
if(-not $targets){
  $ownerPid = ($conn | Select-Object -First 1).OwningProcess
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid"
  if(-not $p -or -not $p.ExecutablePath -or -not ([IO.Path]::GetFullPath($p.ExecutablePath)).StartsWith($canonicalRuntime,[StringComparison]::OrdinalIgnoreCase)){
    throw 'Listening process does not belong to canonical runtime.'
  }
  $targets = @($p)
}

$targets | Sort-Object ProcessId -Descending | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$deadline = (Get-Date).AddSeconds(15)
do {
  Start-Sleep -Milliseconds 300
  $still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if(-not $still){ break }
} while((Get-Date) -lt $deadline)
if($still){ throw "Canonical API port $Port remained listening after stop." }
Remove-Item (Join-Path $root 'runtime\canonical-api.pid') -Force -ErrorAction SilentlyContinue
Write-Output 'CANONICAL_API_STOPPED'
