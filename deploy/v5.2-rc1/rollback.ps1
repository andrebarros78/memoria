$ErrorActionPreference='Continue'
$root='C:\New Projet\MEMORIA-PERMANENTE'
$ports=@(8792,6007,4318)
foreach($port in $ports){
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Output ('STOPPED_PORT_'+$port+'_PID='+$_.OwningProcess)
  }
}
Write-Output 'ROLLBACK_DONE_V4_UNTOUCHED'