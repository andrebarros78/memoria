$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA-PERMANENTE'
& "$root\scripts\start_postgres18_task.ps1"
if($LASTEXITCODE -ne 0){ throw "PostgreSQL recovery supervisor failed rc=$LASTEXITCODE" }
$pgIsReady="$root\runtime\pgsql18-bin\pgsql\bin\pg_isready.exe"
& $pgIsReady -h 127.0.0.1 -p 55436 -d memoria_permanente_v52_primary *> $null
if($LASTEXITCODE -ne 0){ throw 'Canonical PostgreSQL database is not ready on 127.0.0.1:55436' }
Write-Output 'POSTGRES_V53_PRIMARY_READY'
