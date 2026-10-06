$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pg=Join-Path $root 'runtime\pgsql18-bin\pgsql\bin\pg_isready.exe'
$svc=Get-Service -Name 'MEMORIA_PERMANENTE_PG' -ErrorAction Stop
if($svc.Status -ne 'Running'){ Start-Service -Name 'MEMORIA_PERMANENTE_PG' }
for($i=0;$i -lt 60;$i++){
  & $pg -h 127.0.0.1 -p 55436 -d sovereign_memory *> $null
  if($LASTEXITCODE -eq 0){ Write-Output 'POSTGRES_SERVICE_READY'; exit 0 }
  Start-Sleep -Seconds 1
}
throw 'MEMORIA_PERMANENTE_PG did not become ready on 127.0.0.1:55436'
