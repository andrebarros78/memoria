[CmdletBinding()]
param()
$ErrorActionPreference='Continue'
& (Join-Path $PSScriptRoot 'stop-workers.ps1')
& (Join-Path $PSScriptRoot 'stop-canonical.ps1') -Port 8787
& (Join-Path $PSScriptRoot 'stop-canonical.ps1') -Port 8790
Write-Output 'MEMORIA_PERMANENTE_CANONICAL_ALL_STOPPED'
