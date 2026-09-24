$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA-PERMANENTE'
$pg=Join-Path $root 'runtime\pgsql18-bin\pgsql\bin'
$api='http://127.0.0.1:8787'
$stamp=(Get-Date -Format 'yyyyMMddHHmmss')+'-'+([guid]::NewGuid().ToString('N').Substring(0,8))
$restoreDb=('m4_restore_'+($stamp -replace '[^0-9A-Za-z]','_')).ToLower()
$work=Join-Path $root ('runtime\m4-restore-'+$stamp)
$dump=Join-Path $work 'source.dump'
$evidence=Join-Path $root 'evidence'
New-Item -ItemType Directory -Force -Path $work,$evidence | Out-Null
$parts=(Get-Content (Join-Path $root 'runtime\secrets\pgpass.conf') -Raw).Trim().Split(':',5)
$srcHost=$parts[0]; $srcPort=[int]$parts[1]; $srcDb=$parts[2]
$adminPw=(Get-Content (Join-Path $root 'runtime\secrets\postgres_admin.pw') -Raw).Trim()
$appPw=(Get-Content (Join-Path $root 'runtime\secrets\memory_app.pw') -Raw).Trim()
$apiPort=$null
foreach($candidate in 8788..8800){ if(-not (Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue)){ $apiPort=$candidate; break } }
if(-not $apiPort){ throw 'No free temporary API port' }
function Sha256([string]$text){ $sha=[Security.Cryptography.SHA256]::Create(); try { ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-','').ToLowerInvariant()) } finally { $sha.Dispose() } }
function PsqlText([string]$db,[string]$sql){
  $env:PGPASSWORD=$adminPw
  $out=& (Join-Path $pg 'psql.exe') -h $srcHost -p $srcPort -U memory_admin -d $db -At -v ON_ERROR_STOP=1 -c $sql 2>&1
  if($LASTEXITCODE -ne 0){ throw ('psql failed: '+(($out|ForEach-Object{$_.ToString()}) -join ' | ')) }
  return (($out|ForEach-Object{$_.ToString()}) -join "`n").Trim()
}
function PostJson([string]$base,[string]$path,$body,[hashtable]$headers=@{}){
  $json=$body|ConvertTo-Json -Depth 30 -Compress
  $h=@{'Content-Type'='application/json'}; foreach($k in $headers.Keys){$h[$k]=$headers[$k]}
  Invoke-RestMethod -Method Post -Uri ($base+$path) -Headers $h -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec 30
}
$tempApi=$null
$dbCreated=$false
try {
  $namespace=('M4_RESTORE_'+$stamp).ToUpper(); $sessionId='m4-restore-session-'+$stamp
  $memory=PostJson $api '/v1/memories' @{
    namespace=$namespace; memory_key='restore-proof'; category='EVIDENCE';
    content=@{gate='M4';stamp=$stamp;purpose='backup restore checkpoint resume'};
    content_text=('Gate M4 backup restore checkpoint resume '+$stamp);
    provenance=@{trusted=$true;proof='M4_RESTORE'};confidence=1.0;source='sovereign-system';source_version='M4';tags=@('M4','RESTORE');changed_by='prove_gate_m4_restore'
  } @{'Idempotency-Key'=('m4-memory-'+$stamp)}
  $session=PostJson $api '/v1/sessions' @{
    session_id=$sessionId; identity=@{system='MEMORIA_PERMANENTE_IA_SISTEMAS_V4';gate='M4'}; scope=$namespace;
    objective='Prove restored database resumes the exact sovereign checkpoint.';
    critical_rules=@('restore must preserve canonical state','context hash must match');
    operational_state=@{phase='M4_RESTORE_READY';step=404;stamp=$stamp};
    last_confirmed_action='created restore proof state'; blockers=@(); pending=@('restore database','resume checkpoint');
    next_safe_action='resume from isolated restored database'; active_authorizations=@('LOCAL_RESTORE_PROOF'); required_memory_ids=@($memory.item_id)
  }
  $binding=PostJson $api ("/v1/sessions/{0}/bindings" -f $sessionId) @{provider='restore-source';external_session_ref=('source-'+$stamp)}
  $safe=@{streaming_critical=$false;upload_unconfirmed=$false;non_idempotent_write_pending=$false;tool_call_unpersisted=$false;last_event_confirmed=$true;checkpoint_possible=$true}
  $rotation=PostJson $api '/v1/session-rotations/request' @{session_id=$sessionId;safe_point=$safe;memory_before_mb=64.0;reason='M4_RESTORE_PROOF'}
  $prepared=PostJson $api ("/v1/session-rotations/{0}/prepare" -f $rotation.rotation_id) @{last_event_id=('m4-event-'+$stamp)}
  $before=PostJson $api ("/v1/sessions/{0}/resume" -f $sessionId) @{}
  $manifestSql=@"
SELECT 'schema='||(SELECT value FROM schema_meta WHERE key='schema_version');
SELECT 'vector='||COALESCE((SELECT extversion FROM pg_extension WHERE extname='vector'),'');
SELECT 'memory_items='||count(*) FROM memory_items;
SELECT 'memory_versions='||count(*) FROM memory_versions;
SELECT 'memory_events='||count(*) FROM memory_events;
SELECT 'checkpoints='||count(*) FROM checkpoints;
SELECT 'sessions='||count(*) FROM sovereign_sessions;
SELECT 'MI|'||item_id||'|'||content_sha256 FROM memory_items ORDER BY item_id;
SELECT 'MV|'||version_id||'|'||content_sha256||'|'||COALESCE(previous_version_id,'') FROM memory_versions ORDER BY version_id;
SELECT 'ME|'||event_id||'|'||event_type||'|'||COALESCE(request_sha256,'') FROM memory_events ORDER BY event_id;
SELECT 'CP|'||checkpoint_id||'|'||state_sha256 FROM checkpoints ORDER BY checkpoint_id;
"@
  $sourceManifest=PsqlText $srcDb $manifestSql; $sourceHash=Sha256 $sourceManifest
  $env:PGPASSWORD=$adminPw
  & (Join-Path $pg 'pg_dump.exe') -h $srcHost -p $srcPort -U memory_admin -d $srcDb -Fc --no-owner --no-privileges -f $dump
  if($LASTEXITCODE -ne 0){ throw 'pg_dump failed' }
  & (Join-Path $pg 'createdb.exe') -h $srcHost -p $srcPort -U memory_admin -O memory_admin $restoreDb
  if($LASTEXITCODE -ne 0){ throw 'createdb restore target failed' }; $dbCreated=$true
  & (Join-Path $pg 'pg_restore.exe') -h $srcHost -p $srcPort -U memory_admin -d $restoreDb --no-owner --no-privileges --exit-on-error $dump
  if($LASTEXITCODE -ne 0){ throw 'pg_restore failed' }
  $targetManifest=PsqlText $restoreDb $manifestSql; $targetHash=Sha256 $targetManifest
  $env:MEMORY_DATABASE_URL="host=$srcHost port=$srcPort dbname=$restoreDb user=memory_admin password=$adminPw connect_timeout=5"
  $env:MEMORY_DEFAULT_TENANT='LEGACY'
  $env:PYTHONPATH=(Join-Path $root 'src')
  $python=Join-Path $root '.venv\Scripts\python.exe'
  $args=@('-m','uvicorn','memory_permanent.api:app','--host','127.0.0.1','--port',[string]$apiPort,'--log-level','warning')
  $tempApi=Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -PassThru
  $tempBase='http://127.0.0.1:'+$apiPort
  $health=$null
  for($i=0;$i -lt 40;$i++){ try{$health=Invoke-RestMethod ($tempBase+'/health') -TimeoutSec 2; if($health.status -eq 'ok'){break}}catch{}; Start-Sleep -Milliseconds 500 }
  if(-not $health){ throw 'restored API did not start' }
  $after=PostJson $tempBase ("/v1/sessions/{0}/resume" -f $sessionId) @{}
  $checks=[ordered]@{
    DUMP_CREATED=((Test-Path $dump) -and ((Get-Item $dump).Length -gt 0))
    RESTORE_DATABASE_CREATED=$dbCreated
    RESTORE_COMPLETED=$true
    MANIFEST_SHA256_MATCH=($sourceHash -eq $targetHash)
    RESTORED_API_HEALTHY=($health.status -eq 'ok')
    SESSION_ID_PRESERVED=($after.session.session_id -eq $before.session.session_id)
    OBJECTIVE_PRESERVED=($after.session.objective -eq $before.session.objective)
    OPERATIONAL_STATE_PRESERVED=(($after.session.operational_state|ConvertTo-Json -Compress) -eq ($before.session.operational_state|ConvertTo-Json -Compress))
    CHECKPOINT_ID_PRESERVED=($after.checkpoint.checkpoint_id -eq $before.checkpoint.checkpoint_id)
    CHECKPOINT_HASH_PRESERVED=($after.checkpoint.state_sha256 -eq $before.checkpoint.state_sha256)
    CONTEXT_PACK_ID_PRESERVED=($after.context_pack.context_pack_id -eq $before.context_pack.context_pack_id)
    CONTEXT_HASH_PRESERVED=($after.context_pack.context_sha256 -eq $before.context_pack.context_sha256)
    REQUIRED_MEMORY_IDS_PRESERVED=((@($after.context_pack.required_memory_ids|Sort-Object)-join ',') -eq (@($before.context_pack.required_memory_ids|Sort-Object)-join ','))
    RESUME_INTEGRITY_VALID=([bool]$after.integrity.all_valid)
    PGVECTOR_RESTORED=($targetManifest -match 'vector=0\.8\.6')
  }
  $failed=@($checks.GetEnumerator()|Where-Object{-not $_.Value}|ForEach-Object{$_.Key})
  $result=[ordered]@{generated_at=(Get-Date).ToString('o');gate='M4';proof='PG_DUMP_RESTORE_PLUS_RESTORED_API_RESUME';restore_database=$restoreDb;temporary_api_port=$apiPort;dump_bytes=(Get-Item $dump).Length;source_manifest_sha256=$sourceHash;target_manifest_sha256=$targetHash;session_id=$sessionId;checkpoint_id=$after.checkpoint.checkpoint_id;context_sha256=$after.context_pack.context_sha256;checks=$checks;failed_checks=$failed;GATE_M4=$(if($failed.Count -eq 0){'PASS'}else{'FAIL'});RECOVERY_PROVEN=($failed.Count -eq 0)}
  $result|ConvertTo-Json -Depth 30|Set-Content (Join-Path $evidence 'M4_GATE_PROOF.json') -Encoding UTF8
  $lines=@('# Gate M4 - Recovery','','**GATE_M4:** '+$result.GATE_M4,'**RECOVERY_PROVEN:** '+$result.RECOVERY_PROVEN,'','Source manifest SHA-256: `'+$sourceHash+'`','Restored manifest SHA-256: `'+$targetHash+'`','Checkpoint: `'+$result.checkpoint_id+'`','Context SHA-256: `'+$result.context_sha256+'`','','## Checks'); foreach($kv in $checks.GetEnumerator()){$lines+=('- '+$kv.Key+': '+$(if($kv.Value){'PASS'}else{'FAIL'}))}; $lines -join "`r`n"|Set-Content (Join-Path $evidence 'M4_GATE_PROOF.md') -Encoding UTF8
  $result|ConvertTo-Json -Depth 30
  if($failed.Count -gt 0){exit 1}
}
finally {
  if($tempApi -and -not $tempApi.HasExited){ Stop-Process -Id $tempApi.Id -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 500 }
  Remove-Item Env:MEMORY_DATABASE_URL,Env:MEMORY_DEFAULT_TENANT,Env:PYTHONPATH,Env:PGPASSWORD -ErrorAction SilentlyContinue
  if($dbCreated){ $env:PGPASSWORD=$adminPw; & (Join-Path $pg 'dropdb.exe') -h $srcHost -p $srcPort -U memory_admin --if-exists --force $restoreDb 2>$null; Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
}
