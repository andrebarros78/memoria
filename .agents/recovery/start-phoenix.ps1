$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA-PERMANENTE'
$port=6006
$existing=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if($existing){
  try { $resp=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:6006/healthz' -TimeoutSec 5; if($resp.StatusCode -eq 200){ Write-Output 'PHOENIX_ALREADY_HEALTHY'; exit 0 } } catch {}
  throw 'Port 6006 is occupied by an unhealthy process'
}
$env:PYTHONPATH=''
$env:PYTHONNOUSERSITE='1'
$env:PYTHONUTF8='1'
$env:PHOENIX_HOST='127.0.0.1'
$env:PHOENIX_PORT='6006'
$env:PHOENIX_WORKING_DIR="$root\.agents\runtime\phoenix-data"
$env:PHOENIX_COLLECTOR_ENDPOINT='http://127.0.0.1:6006'
$env:PHOENIX_TELEMETRY_ENABLED='false'
$exe="$root\.agents\runtime\observability\Scripts\phoenix.exe"
$out="$root\.agents\runtime\phoenix-data\stdout.log"
$err="$root\.agents\runtime\phoenix-data\stderr.log"
New-Item -ItemType Directory -Force "$root\.agents\runtime\phoenix-data" | Out-Null
$p=Start-Process -FilePath $exe -ArgumentList @('serve') -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
for($i=0;$i -lt 120;$i++){
  Start-Sleep -Milliseconds 500
  try { $resp=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:6006/healthz' -TimeoutSec 3; if($resp.StatusCode -eq 200){ Write-Output ('PHOENIX_READY_PID='+$p.Id); exit 0 } } catch {}
}
throw 'Phoenix did not become healthy on 127.0.0.1:6006'
