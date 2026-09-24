[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ingestScript=[IO.Path]::GetFullPath((Join-Path $root 'scripts\conversation_ingestion_worker.py'))
$embedScript=[IO.Path]::GetFullPath((Join-Path $root 'scripts\embedding_worker.py'))
$ing=[regex]::Escape($ingestScript)
$emb=[regex]::Escape($embedScript)
$targets=Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and $_.CommandLine -match '--loop' -and (($_.CommandLine -match $ing) -or ($_.CommandLine -match $emb))
}
foreach($p in ($targets | Sort-Object ProcessId -Descending)){
  Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Output ('CANONICAL_WORKER_STOPPED_PID='+$p.ProcessId)
}
Start-Sleep -Milliseconds 500
$remaining=Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and $_.CommandLine -match '--loop' -and (($_.CommandLine -match $ing) -or ($_.CommandLine -match $emb))
}
if($remaining){throw 'Canonical worker process remained after stop.'}
Write-Output ('CANONICAL_WORKERS_STOPPED_COUNT='+@($targets).Count)
