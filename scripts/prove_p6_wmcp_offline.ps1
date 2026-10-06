$ErrorActionPreference='Stop'
$Evidence='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\evidence\P6_WMCP_OFFLINE_MEMORY_ALIVE.json'
$Result=[ordered]@{started_at=(Get-Date).ToString('o')}
Start-Sleep -Seconds 3
try {
    $before=Get-NetTCPConnection -State Listen -LocalPort 8767 -ErrorAction SilentlyContinue | Select-Object -First 1
    $Result.wmcp_pid_before=if($before){[int]$before.OwningProcess}else{$null}
    $memoryBefore=Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 5
    $Result.memory_before=$memoryBefore.status

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {$_.CommandLine -like '*-m windows_mcp serve*--port 8767*'} |
        ForEach-Object { try { Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction Stop } catch {} }

    Start-Sleep -Seconds 2
    $down=Get-NetTCPConnection -State Listen -LocalPort 8767 -ErrorAction SilentlyContinue | Select-Object -First 1
    $Result.wmcp_offline_observed=($null -eq $down)
    $memoryDuring=Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 5
    $summaryDuring=Invoke-RestMethod 'http://127.0.0.1:8787/v1/dashboard/summary' -TimeoutSec 5
    $Result.memory_during_wmcp_offline=$memoryDuring.status
    $Result.memory_count_during_wmcp_offline=$summaryDuring.memories_total

    $deadline=(Get-Date).AddSeconds(35)
    $after=$null
    do {
        Start-Sleep -Seconds 1
        $after=Get-NetTCPConnection -State Listen -LocalPort 8767 -ErrorAction SilentlyContinue | Select-Object -First 1
    } until ($after -or (Get-Date) -gt $deadline)
    $Result.wmcp_restored=($null -ne $after)
    $Result.wmcp_pid_after=if($after){[int]$after.OwningProcess}else{$null}
    $Result.memory_after=(Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 5).status
    $Result.P6_WMCP_OFFLINE_MEMORY_ALIVE=if($Result.wmcp_offline_observed -and $Result.memory_during_wmcp_offline -eq 'ok' -and $Result.wmcp_restored -and $Result.memory_after -eq 'ok'){'PASS'}else{'FAIL'}
}
catch {
    $Result.error=$_.Exception.Message
    $Result.P6_WMCP_OFFLINE_MEMORY_ALIVE='FAIL'
}
$Result.finished_at=(Get-Date).ToString('o')
[IO.File]::WriteAllText($Evidence,($Result|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
