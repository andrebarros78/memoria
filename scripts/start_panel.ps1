$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$existing=Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if($existing){
    try {
        $h=Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 5
        if($h.status -eq 'ok' -and $h.runtime_profile -eq 'V5.5-PRIMARY'){ Write-Output 'API_ALREADY_HEALTHY_V55'; exit 0 }
    } catch {}
    throw 'Port 8787 is occupied by an unhealthy or non-V5.5 process'
}
& "$Root\deploy\v5.5\start-primary-v55.ps1"
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }
