[CmdletBinding()]
param(
  [string]$Root = 'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'
)
$ErrorActionPreference='Stop'
$PgBin=Join-Path $Root 'runtime\pgsql18-bin\pgsql\bin'
$Psql=Join-Path $PgBin 'psql.exe'
$Secrets=Join-Path $Root 'runtime\secrets'
$AppPassFile=Join-Path $Secrets 'pgpass.conf'
$AdminPassFile=Join-Path $Secrets 'postgres.pgpass.conf'
if(-not (Test-Path $Psql)){ throw 'PostgreSQL 18 psql.exe is missing.' }
New-Item -ItemType Directory -Force $Secrets | Out-Null

function New-HexSecret {
  $bytes=New-Object byte[] 48
  $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  return ([System.BitConverter]::ToString($bytes) -replace '-','').ToLowerInvariant()
}
function Escape-SqlLiteral([string]$Value){ return $Value.Replace("'","''") }
function Protect-Path([string]$Path,[bool]$Container){
  $who=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
  if($Container){
    & icacls $Path /inheritance:r /grant:r "${who}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
  } else {
    & icacls $Path /inheritance:r /grant:r "${who}:F" "*S-1-5-18:F" | Out-Null
  }
  if($LASTEXITCODE -ne 0){ throw "ACL hardening failed: $Path" }
}

$appPw=New-HexSecret
$adminPw=New-HexSecret
try {
  $appSql=Escape-SqlLiteral $appPw
  $adminSql=Escape-SqlLiteral $adminPw
  $sql=@"
ALTER ROLE memory_app LOGIN PASSWORD '$appSql';
ALTER ROLE memory_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 64;
ALTER ROLE postgres LOGIN PASSWORD '$adminSql';
"@
  $sql | & $Psql -X -w -h 127.0.0.1 -p 55436 -U postgres -d postgres -v ON_ERROR_STOP=1 | Out-Null
  if($LASTEXITCODE -ne 0){ throw 'PostgreSQL role credential provisioning failed.' }

  $appLines=@(
    "127.0.0.1:55436:memoria_permanente_v52_primary:memory_app:$appPw",
    "127.0.0.1:55436:memoria_permanente_v52_rc1:memory_app:$appPw",
    "127.0.0.1:55436:memoria_permanente_v52_hardening:memory_app:$appPw",
    "127.0.0.1:55436:memoria_permanente_v52_restoreproof:memory_app:$appPw",
    "127.0.0.1:55436:memoria_permanente:memory_app:$appPw"
  )
  Set-Content -LiteralPath $AppPassFile -Value ($appLines -join "`n") -NoNewline -Encoding ascii
  Set-Content -LiteralPath $AdminPassFile -Value "127.0.0.1:55436:*:postgres:$adminPw" -NoNewline -Encoding ascii
  Protect-Path $Secrets $true
  Protect-Path $AppPassFile $false
  Protect-Path $AdminPassFile $false

  $checkSql="select rolname||'|login='||rolcanlogin||'|super='||rolsuper||'|createdb='||rolcreatedb||'|createrole='||rolcreaterole||'|replication='||rolreplication||'|bypassrls='||rolbypassrls||'|password_set='||(rolpassword is not null) from pg_authid where rolname in ('postgres','memory_app','memory_admin') order by rolname;"
  $rows=& $Psql -X -w -h 127.0.0.1 -p 55436 -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c $checkSql
  if($LASTEXITCODE -ne 0){ throw 'Post-provision role verification failed.' }
  Write-Output 'POSTGRES_RUNTIME_CREDENTIALS=PROVISIONED'
  $rows | ForEach-Object { Write-Output $_ }
  Write-Output ('APP_PGPASS_PRESENT='+(Test-Path $AppPassFile))
  Write-Output ('ADMIN_PGPASS_PRESENT='+(Test-Path $AdminPassFile))
  Write-Output 'SECRET_MATERIAL_EXPOSED=FALSE'
} finally {
  $appPw=$null; $adminPw=$null; $appSql=$null; $adminSql=$null; $sql=$null
}
