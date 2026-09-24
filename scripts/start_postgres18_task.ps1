[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Pg=Join-Path $Root 'runtime\pgsql18-bin\pgsql\bin'
$Data=Join-Path $Root 'runtime\postgres18\data'
$LogDir=Join-Path $Root 'runtime\postgres18\logs'
$Log=Join-Path $LogDir 'scheduled-start.log'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
function Ready { & (Join-Path $Pg 'pg_isready.exe') -h 127.0.0.1 -p 55436 *> $null; return $LASTEXITCODE -eq 0 }
if(Ready){ exit 0 }
$PidFile=Join-Path $Data 'postmaster.pid'
if(Test-Path $PidFile){
  $first=(Get-Content -LiteralPath $PidFile -First 1 -ErrorAction Stop).Trim()
  $postmasterPid=0
  [void][int]::TryParse($first,[ref]$postmasterPid)
  $live=$false
  if($postmasterPid -gt 0){
    $proc=Get-Process -Id $postmasterPid -ErrorAction SilentlyContinue
    if($proc){ $live=$true }
  }
  if($live){
    for($i=0;$i -lt 60;$i++){ if(Ready){ exit 0 }; Start-Sleep -Seconds 1 }
    exit 3
  }
  $stamp=(Get-Date).ToString('yyyyMMdd-HHmmss')
  $quarantine=Join-Path $LogDir ("postmaster.pid.stale.$stamp")
  Move-Item -LiteralPath $PidFile -Destination $quarantine -Force
  Add-Content -LiteralPath $Log -Value ("[$((Get-Date).ToString('o'))] quarantined stale postmaster.pid pid=$postmasterPid -> $quarantine") -Encoding UTF8
}
& (Join-Path $Pg 'pg_ctl.exe') -D $Data -l $Log -w -t 120 start *> $null
if($LASTEXITCODE -ne 0){ exit 1 }
for($i=0;$i -lt 30;$i++){ if(Ready){ exit 0 }; Start-Sleep -Seconds 1 }
exit 2
