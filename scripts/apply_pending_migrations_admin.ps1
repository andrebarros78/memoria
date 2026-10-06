[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_]{1,63}$')][string]$Database,
  [string]$Root = 'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0',
  [string]$Python = ''
)
$ErrorActionPreference='Stop'
if(-not $Python){ $Python=Join-Path $Root 'runtime\api-secure\Scripts\python.exe' }
if(-not (Test-Path $Python)){ throw "Secure Python runtime missing: $Python" }
$PgPass=Join-Path $Root 'runtime\secrets\postgres.pgpass.conf'
if(-not (Test-Path $PgPass)){ throw 'Administrative PGPASSFILE is not provisioned.' }
$env:PGPASSFILE=$PgPass
$env:MEMORY_PROJECT_ROOT=$Root
$env:MEMORY_ADMIN_DATABASE_URL="postgresql://postgres@127.0.0.1:55436/$Database"
try {
  & $Python (Join-Path $Root 'scripts\apply_pending_migrations_admin.py')
  if($LASTEXITCODE -ne 0){ throw "Administrative migration runner failed rc=$LASTEXITCODE" }
} finally {
  Remove-Item Env:MEMORY_ADMIN_DATABASE_URL,Env:MEMORY_PROJECT_ROOT -ErrorAction SilentlyContinue
}
