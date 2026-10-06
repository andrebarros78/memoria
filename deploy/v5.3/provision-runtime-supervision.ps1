[CmdletBinding()]
param()

$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -RestartCount 10 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)

function New-SupervisionTriggers {
  $boot=New-ScheduledTaskTrigger -AtStartup
  $watch=New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
  return @($boot,$watch)
}

function Register-CanonicalTask([string]$Name,[CimInstance]$Action) {
  $existing=Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
  if($existing -and $existing.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $Name
    Start-Sleep -Milliseconds 500
  }
  Register-ScheduledTask -TaskName $Name -Action $Action -Trigger (New-SupervisionTriggers) `
    -Settings $settings -Principal $principal -Force | Out-Null
  Write-Output ("REGISTERED="+$Name)
}

$ps='powershell.exe'
$hidden='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File'
Register-CanonicalTask 'MEMORIA-PERMANENTE-POSTGRES18' (New-ScheduledTaskAction -Execute $ps -Argument "$hidden `"$root\scripts\start_postgres18_task.ps1`"")
Register-CanonicalTask 'MEMORIA_PERMANENTE_PHOENIX' (New-ScheduledTaskAction -Execute $ps -Argument "$hidden `"$root\.agents\recovery\start-phoenix.ps1`"")
Register-CanonicalTask 'MEMORIA_PERMANENTE_API' (New-ScheduledTaskAction -Execute $ps -Argument "$hidden `"$root\.agents\recovery\start-api.ps1`"")

$pythonw="$root\runtime\api-clean\Scripts\pythonw.exe"
if(-not (Test-Path $pythonw)) { throw 'Promoted api-clean pythonw.exe not found' }
Register-CanonicalTask 'MEMORIA-PERMANENTE-CONVERSATION-INGESTION-WORKER' (
  New-ScheduledTaskAction -Execute $pythonw -Argument "-I `"$root\scripts\conversation_ingestion_worker.py`" --loop --limit 100 --poll-seconds 5" -WorkingDirectory $root
)
Register-CanonicalTask 'MEMORIA-PERMANENTE-EMBEDDING-WORKER' (
  New-ScheduledTaskAction -Execute $pythonw -Argument "-I `"$root\scripts\embedding_worker.py`" --loop --limit 100 --poll-seconds 15" -WorkingDirectory $root
)

$legacy=Get-ScheduledTask -TaskName 'MEMORIA-PERMANENTE-API' -ErrorAction SilentlyContinue
if($legacy -and $legacy.State -ne 'Disabled') {
  Disable-ScheduledTask -TaskName 'MEMORIA-PERMANENTE-API' | Out-Null
  Write-Output 'DISABLED_LEGACY=MEMORIA-PERMANENTE-API'
}

foreach($name in @(
  'MEMORIA-PERMANENTE-POSTGRES18',
  'MEMORIA_PERMANENTE_PHOENIX',
  'MEMORIA_PERMANENTE_API',
  'MEMORIA-PERMANENTE-CONVERSATION-INGESTION-WORKER',
  'MEMORIA-PERMANENTE-EMBEDDING-WORKER'
)) {
  Start-ScheduledTask -TaskName $name
}
Write-Output 'RUNTIME_SUPERVISION_PROVISIONED'