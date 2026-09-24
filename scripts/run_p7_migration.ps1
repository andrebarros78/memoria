$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$GovRoot='C:\New Projet\GOVERNADOR-WINDOWS'
$GovPw=(Get-Content (Join-Path $GovRoot 'runtime\secrets\postgres-app.pw') -Raw).Trim()
$Parts=(Get-Content (Join-Path $Root 'runtime\secrets\pgpass.conf') -Raw).Trim().Split(':')
$env:OLD_DSN="host=127.0.0.1 port=55435 dbname=sovereign_memory user=govmem_app password=$GovPw"
$env:NEW_DSN="host=$($Parts[0]) port=$($Parts[1]) dbname=$($Parts[2]) user=$($Parts[3]) password=$($Parts[4])"
$env:P7_BACKUP_DIR=Join-Path $Root 'backups\P7_PREMIGRATION_20260824-130743'
& (Join-Path $Root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'migrate_governor_memory_p7.py')
$exit=$LASTEXITCODE
Remove-Item Env:OLD_DSN -ErrorAction SilentlyContinue
Remove-Item Env:NEW_DSN -ErrorAction SilentlyContinue
Remove-Item Env:P7_BACKUP_DIR -ErrorAction SilentlyContinue
exit $exit
