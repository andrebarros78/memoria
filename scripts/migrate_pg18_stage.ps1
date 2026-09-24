$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$PgRoot=Join-Path $Root 'runtime\pgsql18-bin\pgsql'
$Bin=Join-Path $PgRoot 'bin'
$Data=Join-Path $Root 'runtime\postgres18\data'
$Log=Join-Path $Root 'runtime\logs\postgres18-stage.log'
$AdminPwFile=Join-Path $Root 'runtime\secrets\postgres_admin.pw'
$PgPassFile=Join-Path $Root 'runtime\secrets\pgpass.conf'
$MigDir=Join-Path $Root 'backups\migration'
New-Item -ItemType Directory -Force $MigDir,(Split-Path $Log),(Split-Path $Data) | Out-Null
$adminPw=(Get-Content $AdminPwFile -Raw).Trim()
$parts=((Get-Content $PgPassFile -Raw).Trim()).Split(':',5)
$appPw=$parts[4]
if(-not $adminPw -or -not $appPw){throw 'required local database credentials missing'}
$stamp=(Get-Date -Format 'yyyyMMdd-HHmmss')
$dump=Join-Path $MigDir "memory-pg17-to-pg18-$stamp.dump"
$env:PGPASSWORD=$adminPw
try {
  & (Join-Path $Bin 'pg_dump.exe') -h 127.0.0.1 -p 55436 -U memory_admin -d memoria_permanente -w -Fc -f $dump
  if($LASTEXITCODE -ne 0){throw "PG18 pg_dump from PG17 failed rc=$LASTEXITCODE"}
  $dumpHash=(Get-FileHash $dump -Algorithm SHA256).Hash
  if(Test-Path $Data){
    $existing=Get-ChildItem $Data -Force -ErrorAction SilentlyContinue
    if($existing){throw "staging data directory already initialized: $Data"}
  } else {New-Item -ItemType Directory -Force $Data | Out-Null}
  & (Join-Path $Bin 'initdb.exe') -D $Data -U memory_admin --pwfile=$AdminPwFile --encoding=UTF8 --locale=C --auth-host=scram-sha-256 --auth-local=scram-sha-256
  if($LASTEXITCODE -ne 0){throw "initdb failed rc=$LASTEXITCODE"}
  Add-Content -LiteralPath (Join-Path $Data 'postgresql.conf') -Value "`nlisten_addresses = '127.0.0.1'`nport = 55438`npassword_encryption = 'scram-sha-256'`n" -Encoding ASCII
  & (Join-Path $Bin 'pg_ctl.exe') -D $Data -l $Log -w start
  if($LASTEXITCODE -ne 0){throw "PG18 staging start failed rc=$LASTEXITCODE"}
  $escaped=$appPw.Replace("'","''")
  "CREATE ROLE memory_app LOGIN PASSWORD '$escaped';" | & (Join-Path $Bin 'psql.exe') -h 127.0.0.1 -p 55438 -U memory_admin -d postgres -w -v ON_ERROR_STOP=1
  if($LASTEXITCODE -ne 0){throw "memory_app role create failed rc=$LASTEXITCODE"}
  & (Join-Path $Bin 'createdb.exe') -h 127.0.0.1 -p 55438 -U memory_admin -w -O memory_app -E UTF8 -T template0 memoria_permanente
  if($LASTEXITCODE -ne 0){throw "database create failed rc=$LASTEXITCODE"}
  & (Join-Path $Bin 'pg_restore.exe') -h 127.0.0.1 -p 55438 -U memory_admin -d memoria_permanente -w --exit-on-error $dump
  if($LASTEXITCODE -ne 0){throw "pg_restore failed rc=$LASTEXITCODE"}
  $info=& (Join-Path $Bin 'psql.exe') -h 127.0.0.1 -p 55438 -U memory_admin -d memoria_permanente -w -Atc "SELECT current_setting('server_version')||'|'||(SELECT extversion FROM pg_extension WHERE extname='vector')||'|'||(SELECT value FROM schema_meta WHERE key='schema_version')||'|'||(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database());"
  [pscustomobject]@{stage='RESTORED';port=55438;data=$Data;dump=$dump;dump_bytes=(Get-Item $dump).Length;dump_sha256=$dumpHash;target_info=$info} | ConvertTo-Json -Compress
} finally {Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue}
