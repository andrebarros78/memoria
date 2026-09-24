$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA-PERMANENTE'
$PgPass=Join-Path $root 'runtime\secrets\pgpass.conf'
if(-not (Test-Path $PgPass)){ throw 'PGPASSFILE da Memória Permanente ausente.' }
$env:PGPASSFILE=$PgPass
if(Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue){ Write-Output 'PORT_8787_BUSY_STOP_BEFORE_START'; exit 2 }

# Production must execute only the promoted package from the isolated api-clean venv.
# Never inherit source-tree paths from WMCP, shells, user profiles, or development tooling.
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE='1'
$env:PYTHONUTF8='1'
$env:MEMORY_DATABASE_URL='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
$env:MEMORY_DSN='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
$env:MEMORY_RUNTIME_PROFILE='V5.3-PRIMARY'
$env:MEMORY_RELEASE_CHANNEL='v5.3-primary-promoted'
$env:MEMORY_PROJECT_ROOT=$root
$env:MEMORY_SEMANTIC_ENABLED='1'
$env:MEMORY_EMBEDDING_MODEL='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
$env:MEMORY_EMBEDDING_CACHE="$root\runtime\models\fastembed"
$env:MEMORY_SEMANTIC_MIN_SIMILARITY='0.40'

$py="$root\runtime\api-clean\Scripts\python.exe"
if(-not (Test-Path $py)){ throw 'Runtime Python api-clean ausente.' }
$expectedSite=[IO.Path]::GetFullPath((Join-Path $root 'runtime\api-clean\Lib\site-packages'))
$packagePath=(& $py -I -c "import pathlib,memory_permanent; print(pathlib.Path(memory_permanent.__file__).resolve())").Trim()
if($LASTEXITCODE -ne 0){ throw 'Não foi possível importar o pacote promovido em modo isolado.' }
if(-not $packagePath.StartsWith($expectedSite,[StringComparison]::OrdinalIgnoreCase)){
  throw "Release integrity failure: memory_permanent resolved outside api-clean site-packages: $packagePath"
}

& $py -I -m memory_permanent.runtime_preflight
if($LASTEXITCODE -ne 0){ throw 'Memory runtime preflight failed; API not started.' }

$out="$root\runtime\logs\api-8787-v53-primary.out.log"
$err="$root\runtime\logs\api-8787-v53-primary.err.log"
$p=Start-Process -FilePath $py -ArgumentList @('-I','-m','uvicorn','memory_permanent.api:app','--host','127.0.0.1','--port','8787') -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
Set-Content -Path "$root\.agents\v53-primary-api.pid" -Value $p.Id -Encoding ascii

$deadline=(Get-Date).AddSeconds(30)
$lastHealthError=$null
do {
  Start-Sleep -Milliseconds 500
  $p.Refresh()
  if($p.HasExited){
    $tail = if(Test-Path $err){ (Get-Content $err -Tail 80) -join "`n" } else { 'no stderr log' }
    throw "V5.3 API exited before readiness (exit=$($p.ExitCode)). $tail"
  }
  try {
    $h=Invoke-RestMethod 'http://127.0.0.1:8787/health' -TimeoutSec 2
    if($h.status -eq 'ok' -and $h.runtime_profile -eq 'V5.3-PRIMARY' -and $h.release_channel -eq 'v5.3-primary-promoted'){
      Write-Output ($h | ConvertTo-Json -Compress -Depth 8)
      exit 0
    }
    $lastHealthError="unexpected health identity: $($h | ConvertTo-Json -Compress -Depth 4)"
  } catch {
    $lastHealthError=$_.Exception.Message
  }
} while((Get-Date) -lt $deadline)

try { & taskkill.exe /PID $p.Id /T /F | Out-Null } catch {}
throw "V5.3 API readiness timed out after 30s. Last health error: $lastHealthError"
