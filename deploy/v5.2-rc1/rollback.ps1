$ErrorActionPreference='Continue'
$root='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'
$ports=@(8792,6007,4318)
foreach($port in $ports){
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Output ('STOPPED_PORT_'+$port+'_PID='+$_.OwningProcess)
  }
}
Write-Output 'ROLLBACK_DONE_V4_UNTOUCHED'