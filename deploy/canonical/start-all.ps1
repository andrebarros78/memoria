[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
& (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path '.agents\recovery\start-postgres.ps1')
& (Join-Path $PSScriptRoot 'start-canonical.ps1') -Port 8790
& (Join-Path $PSScriptRoot 'start-canonical.ps1') -Port 8787
& (Join-Path $PSScriptRoot 'start-workers.ps1')
Write-Output 'MEMORIA_PERMANENTE_CANONICAL_ALL_READY'
