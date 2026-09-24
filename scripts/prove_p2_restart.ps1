[CmdletBinding()]
param()
$ErrorActionPreference='Continue'
$Root=Split-Path -Parent $PSScriptRoot
$Pg=Join-Path $Root 'runtime\pgsql18-bin\pgsql\bin'
$Data=Join-Path $Root 'runtime\postgres18\data'
$Evidence=Join-Path $Root 'evidence\P2_DB_RESTART_PROOF.json'
$PgPass=Join-Path $Root 'runtime\secrets\pgpass.conf'
$TaskName='MEMORIA-PERMANENTE-POSTGRES18'
function Ready([int]$Port){& "$Pg\pg_isready.exe" -h 127.0.0.1 -p $Port *> $null;return $LASTEXITCODE -eq 0}
function Start-Memory {
  if(Ready 55436){return $true}
  try { Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch { return $false }
  $deadline=(Get-Date).AddSeconds(30)
  do { Start-Sleep -Milliseconds 500; if(Ready 55436){return $true} } while((Get-Date) -lt $deadline)
  return $false
}
if(-not (Start-Memory)){throw 'Não foi possível estabelecer baseline READY da memória'}
$govBefore=Ready 55435
$memBefore=Ready 55436
& "$Pg\pg_ctl.exe" -D $Data -m fast -w -t 30 stop 2>$null | Out-Null
$stopOk=$LASTEXITCODE -eq 0
$memDown=-not (Ready 55436)
$govDuring=Ready 55435
$startOk=Start-Memory
if(-not $startOk){throw 'restart da memória falhou'}
$env:PGPASSFILE=$PgPass
$env:PGOPTIONS='-c app.current_tenant=LEGACY'
try {
  $countRaw=& "$Pg\psql.exe" -h 127.0.0.1 -p 55436 -U memory_app -d memoria_permanente --no-password -tAc 'SELECT count(*) FROM memory_items' 2>$null
  if($LASTEXITCODE -ne 0){throw 'count query falhou'}
  $discardRaw=& "$Pg\psql.exe" -h 127.0.0.1 -p 55436 -U memory_app -d memoria_permanente --no-password -tAc "SELECT lifecycle_state FROM memory_operator_state s JOIN memory_items m USING(item_id) WHERE m.memory_key='proof:discardable'" 2>$null
  if($LASTEXITCODE -ne 0){throw 'discard query falhou'}
  $permRaw=& "$Pg\psql.exe" -h 127.0.0.1 -p 55436 -U memory_app -d memoria_permanente --no-password -tAc "SELECT operator_class FROM memory_operator_state s JOIN memory_items m USING(item_id) WHERE m.memory_key='proof:permanent'" 2>$null
  if($LASTEXITCODE -ne 0){throw 'permanent query falhou'}
} finally {
  Remove-Item Env:PGPASSFILE -ErrorAction SilentlyContinue
  Remove-Item Env:PGOPTIONS -ErrorAction SilentlyContinue
}
$count=[int](([string]$countRaw).Trim())
$discard=([string]$discardRaw).Trim()
$perm=([string]$permRaw).Trim()
$pass=$govBefore -and $memBefore -and $stopOk -and $memDown -and $govDuring -and $startOk -and $count -ge 5 -and $discard -eq 'DELETE_ELIGIBLE' -and $perm -eq 'PERMANENTE'
$proof=[ordered]@{
 governor_ready_before=$govBefore
 memory_ready_before=$memBefore
 memory_stop_ok=$stopOk
 memory_confirmed_down=$memDown
 governor_ready_while_memory_down=$govDuring
 memory_restart_ok=$startOk
 memory_count_after_restart=$count
 discardable_state_after_restart=$discard
 permanent_class_after_restart=$perm
 postgres_start_supervisor=$TaskName
 rls_tenant='LEGACY'
 P2_RESTART_ISOLATION_PROOF=$(if($pass){'PASS'}else{'FAIL'})
}
$proof|ConvertTo-Json|Set-Content $Evidence -Encoding utf8
$proof|ConvertTo-Json
if(-not $pass){exit 1}
