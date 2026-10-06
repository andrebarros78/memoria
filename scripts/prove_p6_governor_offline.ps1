$ErrorActionPreference='Stop'
$SupervisorTasks=@('WMCP31-Management-Services-Watchdog','WMCP31-24x24-Supervisor')
$MemoryTask='WMCP31-SovereignMemory'
$Pg='C:\Program Files\PostgreSQL\17\bin'
$Data='C:\New Projet\GOVERNADOR-WINDOWS\runtime\postgres\data'
$Result=[ordered]@{}
try {
    foreach($Task in $SupervisorTasks){ Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    & "$Pg\pg_ctl.exe" -D $Data -m fast -w -t 30 stop *> $null
    & "$Pg\pg_isready.exe" -h 127.0.0.1 -p 55435 *> $null
    $Result.governor_store_offline = ($LASTEXITCODE -ne 0)
    $Health=Invoke-RestMethod 'http://127.0.0.1:8787/health'
    $Summary=Invoke-RestMethod 'http://127.0.0.1:8787/v1/dashboard/summary'
    $Result.memory_health_while_governor_offline = $Health.status
    $Result.memory_count = $Summary.memories_total
}
finally {
    Start-ScheduledTask -TaskName $MemoryTask -ErrorAction SilentlyContinue
    $Deadline=(Get-Date).AddSeconds(30)
    $Ready=$false
    do {
        Start-Sleep -Milliseconds 500
        & "$Pg\pg_isready.exe" -h 127.0.0.1 -p 55435 *> $null
        $Ready=($LASTEXITCODE -eq 0)
    } until ($Ready -or (Get-Date) -gt $Deadline)
    $Result.governor_store_restored=$Ready
    Start-ScheduledTask -TaskName 'WMCP31-24x24-Supervisor' -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName 'WMCP31-Management-Services-Watchdog' -ErrorAction SilentlyContinue
}
$Result.P6_GOVERNOR_OFFLINE_MEMORY_ALIVE = if($Result.governor_store_offline -and $Result.memory_health_while_governor_offline -eq 'ok' -and $Result.governor_store_restored){'PASS'}else{'FAIL'}
$Json=$Result | ConvertTo-Json -Depth 4
$Json | Set-Content -Encoding utf8 'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\evidence\P6_GOVERNOR_OFFLINE_MEMORY_ALIVE.json'
$Json
if($Result.P6_GOVERNOR_OFFLINE_MEMORY_ALIVE -ne 'PASS'){exit 1}
