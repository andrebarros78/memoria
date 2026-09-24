[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PgBin = if ($env:MEMORY_PG_BIN) { $env:MEMORY_PG_BIN } else { Join-Path $Root 'runtime\pgsql18-bin\pgsql\bin' }
$Data = Join-Path $Root 'runtime\postgres18\data'
$Logs = Join-Path $Root 'runtime\postgres18\logs'
$Secrets = Join-Path $Root 'runtime\secrets'
$AdminPwFile = Join-Path $Secrets 'postgres_admin.pw'
$AppPwFile = Join-Path $Secrets 'memory_app.pw'
$PgPassFile = Join-Path $Secrets 'pgpass.conf'
$Port = 55436
$Database = if ($env:MEMORY_BOOTSTRAP_DATABASE) { $env:MEMORY_BOOTSTRAP_DATABASE.Trim() } else { 'memoria_permanente_v52_primary' }

foreach ($dir in @($Data,$Logs,$Secrets)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
& icacls $Secrets /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" *> $null

function New-StrongText { return ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')) }
function Ready { & (Join-Path $PgBin 'pg_isready.exe') -h 127.0.0.1 -p $Port *> $null; return $LASTEXITCODE -eq 0 }
function Scalar([object]$value) { if ($null -eq $value) { return '' }; return ([string]$value).Trim() }

if (-not (Test-Path (Join-Path $Data 'PG_VERSION'))) {
    if (-not (Test-Path $AdminPwFile)) { Set-Content -Path $AdminPwFile -Value (New-StrongText) -NoNewline -Encoding ascii }
    & (Join-Path $PgBin 'initdb.exe') -D $Data -U memory_admin --pwfile=$AdminPwFile --auth-local=scram-sha-256 --auth-host=scram-sha-256 --encoding=UTF8 --no-locale
    if ($LASTEXITCODE -ne 0) { throw 'initdb falhou' }
    Add-Content -Path (Join-Path $Data 'postgresql.conf') -Value "`nport = $Port`nlisten_addresses = '127.0.0.1'`nlogging_collector = on`nlog_directory = '$($Logs -replace '\\','/')'`nlog_filename = 'postgresql-%Y-%m-%d.log'`n"
}

if (-not (Ready)) {
    & (Join-Path $PgBin 'pg_ctl.exe') -D $Data -l (Join-Path $Logs 'bootstrap.log') -w -t 60 start
    if ($LASTEXITCODE -ne 0 -or -not (Ready)) { throw 'PostgreSQL independente não iniciou' }
}

if (-not (Test-Path $AppPwFile)) { Set-Content -Path $AppPwFile -Value (New-StrongText) -NoNewline -Encoding ascii }
$adminPw = (Get-Content $AdminPwFile -Raw).Trim()
$appPw = (Get-Content $AppPwFile -Raw).Trim()
$env:PGPASSWORD = $adminPw
try {
    $roleRaw = & (Join-Path $PgBin 'psql.exe') -h 127.0.0.1 -p $Port -U memory_admin -d postgres --no-password -tAc "SELECT 1 FROM pg_roles WHERE rolname='memory_app'" 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('role probe failed: ' + (Scalar $roleRaw)) }
    $roleExists = Scalar $roleRaw
    if ($roleExists -ne '1') {
        $createRole = & (Join-Path $PgBin 'psql.exe') -h 127.0.0.1 -p $Port -U memory_admin -d postgres --no-password -v ON_ERROR_STOP=1 -c "CREATE ROLE memory_app LOGIN PASSWORD '$appPw';" 2>&1
        if ($LASTEXITCODE -ne 0) { throw ('criação da role memory_app falhou: ' + (Scalar $createRole)) }
    }
    $syncRole = & (Join-Path $PgBin 'psql.exe') -h 127.0.0.1 -p $Port -U memory_admin -d postgres --no-password -v ON_ERROR_STOP=1 -c "ALTER ROLE memory_app PASSWORD '$appPw';" 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('sincronização da credencial memory_app falhou: ' + (Scalar $syncRole)) }
    $dbRaw = & (Join-Path $PgBin 'psql.exe') -h 127.0.0.1 -p $Port -U memory_admin -d postgres --no-password -tAc "SELECT 1 FROM pg_database WHERE datname='$Database'" 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('database probe failed: ' + (Scalar $dbRaw)) }
    $dbExists = Scalar $dbRaw
    if ($dbExists -ne '1') {
        $createDb = & (Join-Path $PgBin 'createdb.exe') -h 127.0.0.1 -p $Port -U memory_admin --no-password -O memory_admin $Database 2>&1
        if ($LASTEXITCODE -ne 0) { throw ('criação do banco memoria_permanente falhou: ' + (Scalar $createDb)) }
    }
} finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }

Set-Content -Path $PgPassFile -Value "127.0.0.1:${Port}:${Database}:memory_app:${appPw}" -NoNewline -Encoding ascii
$version = (& (Join-Path $PgBin 'postgres.exe') --version).Trim()
[ordered]@{
  status='ready'
  host='127.0.0.1'
  port=$Port
  database=$Database
  user='memory_app'
  pgdata=$Data
  pgpass=$PgPassFile
  postgres_version=$version
  release_target='PostgreSQL 18.6'
  release_version_match=($version -match '18\.6')
}|ConvertTo-Json -Compress
