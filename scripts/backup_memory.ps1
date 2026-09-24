param([string]$OutputDir = "")
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$PgBin=if($env:MEMORY_PG_BIN){$env:MEMORY_PG_BIN}else{Join-Path $Root 'runtime\pgsql18-bin\pgsql\bin'}
$PgPass=Join-Path $Root 'runtime\secrets\pgpass.conf'
if(-not (Test-Path $PgPass)){throw 'pgpass.conf missing'}
$parts=((Get-Content $PgPass -Raw).Trim()).Split(':',5)
if($parts.Count -ne 5){throw 'invalid pgpass.conf'}
$hostName=$parts[0]; $port=$parts[1]; $database=$parts[2]; $user=$parts[3]; $pw=$parts[4]
if(-not $OutputDir){$OutputDir=Join-Path $Root 'backups\operational'}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$stamp=(Get-Date).ToString('yyyyMMdd-HHmmss')
$dump=Join-Path $OutputDir ("memory-$stamp.dump")
$manifest=Join-Path $OutputDir ("memory-$stamp.manifest.json")
$env:PGPASSWORD=$pw
$env:PGOPTIONS='-c app.current_tenant=__SYSTEM__ -c row_security=on'
try {
  & (Join-Path $PgBin 'pg_dump.exe') -h $hostName -p $port -U $user -d $database --no-password --enable-row-security --format=custom --no-owner --no-privileges --file=$dump
  if($LASTEXITCODE -ne 0){throw "pg_dump failed rc=$LASTEXITCODE"}
  $list=& (Join-Path $PgBin 'pg_restore.exe') --list $dump
  if($LASTEXITCODE -ne 0){throw "pg_restore --list failed rc=$LASTEXITCODE"}
  $hash=(Get-FileHash $dump -Algorithm SHA256).Hash
  $obj=[ordered]@{
    generated_at=(Get-Date).ToString('o'); database=$database; host=$hostName; port=[int]$port; role=$user
    dump_file=$dump; dump_bytes=(Get-Item $dump).Length; sha256=$hash; restore_catalog_entries=@($list).Count
    pg_dump_version=(& (Join-Path $PgBin 'pg_dump.exe') --version).Trim(); row_security='ON'; tenant_context='__SYSTEM__'
    backup_valid=($hash.Length -eq 64 -and (Get-Item $dump).Length -gt 0 -and @($list).Count -gt 0)
  }
  [IO.File]::WriteAllText($manifest,($obj|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
  $obj | ConvertTo-Json -Depth 6
} finally {
  Remove-Item Env:PGPASSWORD,Env:PGOPTIONS -ErrorAction SilentlyContinue
}
