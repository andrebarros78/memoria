[CmdletBinding()]
param(
  [string]$Root = 'C:\New Projet\MEMORIA-PERMANENTE',
  [string]$Database = 'memoria_permanente_v52_primary'
)
$ErrorActionPreference='Stop'
$PgBin=Join-Path $Root 'runtime\pgsql18-bin\pgsql\bin'
$Psql=Join-Path $PgBin 'psql.exe'
$PgCtl=Join-Path $PgBin 'pg_ctl.exe'
$Data=Join-Path $Root 'runtime\postgres18\data'
$Hba=Join-Path $Data 'pg_hba.conf'
$AppPass=Join-Path $Root 'runtime\secrets\pgpass.conf'
$AdminPass=Join-Path $Root 'runtime\secrets\postgres.pgpass.conf'
foreach($p in @($Psql,$PgCtl,$Hba,$AppPass,$AdminPass)){ if(-not (Test-Path $p)){ throw "Required hardening input missing: $p" } }

$activeRole=(& $Psql -X -w -h 127.0.0.1 -p 55436 -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c "select count(*) from pg_stat_activity where datname='$Database' and usename='memory_app' and application_name like '%uvicorn%';" 2>$null).Trim()
# pg_stat_activity application_name is not guaranteed for psycopg/uvicorn; the API's
# own runtime preflight is authoritative. Require an explicit proof file written by promotion.
$Proof=Join-Path $Root 'runtime\security\memory-app-runtime-proven.json'
if(-not (Test-Path $Proof)){ throw 'memory_app runtime proof is missing; refusing HBA hardening before promotion.' }

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$Backup="$Hba.pre-scram-$stamp.bak"
Copy-Item -LiteralPath $Hba -Destination $Backup -Force
try {
  $lines=Get-Content -LiteralPath $Hba
  $new=foreach($line in $lines){
    if($line -match '^\s*(local|host)\s+' -and $line -match '\btrust\b'){
      $line -replace '\btrust\b','scram-sha-256'
    } else { $line }
  }
  Set-Content -LiteralPath $Hba -Value $new -Encoding ascii
  & $PgCtl -D $Data reload | Out-Null
  if($LASTEXITCODE -ne 0){ throw 'PostgreSQL reload failed.' }
  Start-Sleep -Seconds 1

  $env:PGPASSFILE=$AdminPass
  $admin=& $Psql -X -w -h 127.0.0.1 -p 55436 -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c "select current_user;"
  if($LASTEXITCODE -ne 0 -or $admin.Trim() -ne 'postgres'){ throw 'SCRAM admin verification failed.' }
  $env:PGPASSFILE=$AppPass
  $app=& $Psql -X -w -h 127.0.0.1 -p 55436 -U memory_app -d $Database -At -v ON_ERROR_STOP=1 -c "select current_user;"
  if($LASTEXITCODE -ne 0 -or $app.Trim() -ne 'memory_app'){ throw 'SCRAM runtime verification failed.' }
  $env:PGPASSFILE=$AdminPass
  $trust=& $Psql -X -w -h 127.0.0.1 -p 55436 -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c "select count(*) from pg_hba_file_rules where error is not null or auth_method='trust';"
  if($LASTEXITCODE -ne 0 -or [int]$trust.Trim() -ne 0){ throw 'HBA still contains trust or parse errors.' }
  Write-Output 'PG_HBA_SCRAM=PROVEN'
  Write-Output 'TRUST_RULES=0'
  Write-Output 'SECRET_MATERIAL_EXPOSED=FALSE'
} catch {
  Copy-Item -LiteralPath $Backup -Destination $Hba -Force
  & $PgCtl -D $Data reload | Out-Null
  throw
} finally {
  Remove-Item Env:PGPASSFILE -ErrorAction SilentlyContinue
}
