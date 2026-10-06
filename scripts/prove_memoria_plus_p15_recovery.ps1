$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'
$pg=Join-Path $root 'runtime\pgsql18-bin\pgsql\bin'
$backupDir=Join-Path $root 'backups\post-memoria-plus-p15-final'
$evidence=Join-Path $root 'evidence\MEMORIA_PLUS_P15_RECOVERY_PROOF.json'
$dump=Get-ChildItem $backupDir -Filter 'memory-*.dump' -File | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(-not $dump){ throw 'post-P15 dump not found' }
$stamp=Get-Date -Format 'yyyyMMddHHmmssfff'
$data=Join-Path $root ('runtime\p15-restore-cluster-'+$stamp)
$pwFile=Join-Path $root ('runtime\p15-restore-password-'+$stamp+'.txt')
$restoreLog=Join-Path $root ('runtime\p15-restore-'+$stamp+'.log')
$serverLog=Join-Path $root ('runtime\p15-postgres-'+$stamp+'.log')
$admin='p15_restore_admin'; $db='p15_restore'
$bytes=New-Object byte[] 32
$rng=[Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($bytes); $rng.Dispose()
$pw=-join ($bytes | ForEach-Object { $_.ToString('x2') })
$listener=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0)
$listener.Start(); $port=([System.Net.IPEndPoint]$listener.LocalEndpoint).Port; $listener.Stop()
$started=$false
function Step([string]$s){ Add-Content -LiteralPath $restoreLog -Value ('[STEP] '+$s+' '+(Get-Date).ToString('o')) -Encoding ascii }
try {
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    [IO.File]::WriteAllText($pwFile,$pw,(New-Object Text.UTF8Encoding($false)))
    Step 'INITDB_BEGIN'
    & (Join-Path $pg 'initdb.exe') -D $data -U $admin --pwfile=$pwFile --auth-local=scram-sha-256 --auth-host=scram-sha-256 --encoding=UTF8 --no-locale *>> $restoreLog
    if($LASTEXITCODE -ne 0){ throw "initdb failed rc=$LASTEXITCODE" }; Step 'INITDB_END'
    Add-Content -LiteralPath (Join-Path $data 'postgresql.conf') -Value "listen_addresses='127.0.0.1'`nport=$port`nmax_connections=40`n" -Encoding ascii
    Step 'START_BEGIN'
    & (Join-Path $pg 'pg_ctl.exe') -D $data -l $serverLog -w -t 30 start | Out-Null
    if($LASTEXITCODE -ne 0){ throw "pg_ctl start failed rc=$LASTEXITCODE" }; $started=$true; Step 'START_END'
    $env:PGPASSWORD=$pw
    Step 'CREATEDB_BEGIN'
    & (Join-Path $pg 'createdb.exe') -h 127.0.0.1 -p $port -U $admin $db *>> $restoreLog
    if($LASTEXITCODE -ne 0){ throw "createdb failed rc=$LASTEXITCODE" }; Step 'CREATEDB_END'
    Step 'RESTORE_BEGIN'
    & (Join-Path $pg 'pg_restore.exe') --jobs=4 --exit-on-error --no-owner --no-privileges -h 127.0.0.1 -p $port -U $admin -d $db $dump.FullName *>> $restoreLog
    if($LASTEXITCODE -ne 0){ throw "pg_restore failed rc=$LASTEXITCODE" }; Step 'RESTORE_END'

    $catalog=@(& (Join-Path $pg 'pg_restore.exe') --list $dump.FullName 2>&1)
    if($LASTEXITCODE -ne 0){ throw 'pg_restore --list failed' }
    $catalogEntries=@($catalog | Where-Object { $_.ToString() -match '^\d+;' }).Count
    $query=@"
SELECT 'schema='||(SELECT value FROM schema_meta WHERE key='schema_version');
SELECT 'guard='||(SELECT value FROM schema_meta WHERE key='input_guard_version');
SELECT 'p15_item='||count(*) FROM memory_items WHERE item_id='mem-0a43c85342cb4776ad5d96353898bb92';
SELECT 'p15_versions='||count(*) FROM memory_versions WHERE item_id='mem-0a43c85342cb4776ad5d96353898bb92';
SELECT 'p15_current_hash='||content_sha256 FROM memory_versions WHERE item_id='mem-0a43c85342cb4776ad5d96353898bb92' ORDER BY version_no DESC LIMIT 1;
SELECT 'p15_current_status='||COALESCE(content_json->>'status','') FROM memory_versions WHERE item_id='mem-0a43c85342cb4776ad5d96353898bb92' ORDER BY version_no DESC LIMIT 1;
SELECT 'migration_checksum='||(SELECT checksum_sha256 FROM schema_migrations WHERE version='0030_input_guard_v2');
"@
    Step 'VERIFY_BEGIN'
    $queryOut=@(& (Join-Path $pg 'psql.exe') -h 127.0.0.1 -p $port -U $admin -d $db -At -v ON_ERROR_STOP=1 -c $query 2>&1)
    if($LASTEXITCODE -ne 0){ throw 'restore verification query failed' }; Step 'VERIFY_END'
    $map=@{}
    foreach($line in $queryOut){ $text=$line.ToString().Trim(); if($text -match '^([^=]+)=(.*)$'){ $map[$matches[1]]=$matches[2] } }
    $migrationHash=(Get-FileHash (Join-Path $root 'migrations\0030_input_guard_v2.sql') -Algorithm SHA256).Hash.ToLowerInvariant()
    $checks=[ordered]@{
        DUMP_EXISTS=($dump.Length -gt 0); PG_RESTORE_LIST_RC0=$true; CATALOG_ENTRIES_GE_700=($catalogEntries -ge 700)
        TEMP_CLUSTER_INITDB=$true; TEMP_CLUSTER_STARTED=$true; LIVE_DATABASE_CREATED=$true; LIVE_PG_RESTORE_RC0=$true
        SCHEMA_0_23_0_RESTORED=([string]$map['schema'] -eq 'memory-0.23.0')
        INPUT_GUARD_IG_2_0_0_RESTORED=([string]$map['guard'] -eq 'IG-2.0.0')
        P15_ITEM_RESTORED=([int]$map['p15_item'] -eq 1)
        P15_VERSIONS_RESTORED=([int]$map['p15_versions'] -ge 2)
        P15_CURRENT_HASH_VALID=([string]$map['p15_current_hash'] -match '^[0-9a-f]{64}$')
        P15_CURRENT_STATUS_PROVEN=([string]$map['p15_current_status'] -eq 'PROVEN')
        MIGRATION_0030_CHECKSUM_RESTORED=([string]$map['migration_checksum'] -eq $migrationHash)
    }
    $failed=@($checks.GetEnumerator()|Where-Object{-not $_.Value}|ForEach-Object{$_.Key})
    $result=[ordered]@{
        generated_at=(Get-Date).ToString('o'); proof='LIVE_ISOLATED_POSTGRESQL18_RESTORE'; live_isolated_restore=$true
        temporary_port=$port; dump_file=$dump.FullName; dump_bytes=$dump.Length; dump_sha256=(Get-FileHash $dump.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        restore_catalog_entries=$catalogEntries; restored_schema=[string]$map['schema']; restored_input_guard=[string]$map['guard']
        restored_p15_versions=[int]$map['p15_versions']; restored_p15_current_hash=[string]$map['p15_current_hash']; restored_migration_checksum=[string]$map['migration_checksum']
        checks=$checks; failed_checks=$failed; RECOVERY_PROVEN=($failed.Count -eq 0)
    }
    $result|ConvertTo-Json -Depth 10|Set-Content $evidence -Encoding UTF8
    $result|ConvertTo-Json -Depth 10
    if($failed.Count -gt 0){ exit 1 }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    if($started){ Step 'STOP_BEGIN'; & (Join-Path $pg 'pg_ctl.exe') -D $data -m fast -w -t 30 stop | Out-Null; Step 'STOP_END' }
    Remove-Item $pwFile -Force -ErrorAction SilentlyContinue
    Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $restoreLog -Force -ErrorAction SilentlyContinue
    Remove-Item $serverLog -Force -ErrorAction SilentlyContinue
}
