[CmdletBinding()]
param(
  [int]$Port = 8790
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'stop-canonical.ps1') -Port $Port
& (Join-Path $PSScriptRoot 'start-canonical.ps1') -Port $Port
