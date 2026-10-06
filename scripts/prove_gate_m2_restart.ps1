$ErrorActionPreference='Stop'
$root='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'
$api='http://127.0.0.1:8787'
$suffix=(Get-Date -Format 'yyyyMMddHHmmss')+'-'+([guid]::NewGuid().ToString('N').Substring(0,8))
$namespace=('M2_RESTART_'+$suffix).ToUpper()
$sessionId='m2-restart-session-'+$suffix

function PostJson([string]$path,$body,[hashtable]$headers=@{}) {
  $json=$body | ConvertTo-Json -Depth 20 -Compress
  $h=@{'Content-Type'='application/json'}
  foreach($k in $headers.Keys){$h[$k]=$headers[$k]}
  Invoke-RestMethod -Method Post -Uri ($api+$path) -Headers $h -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec 30
}

$mem1=PostJson '/v1/memories' @{
  namespace=$namespace; memory_key='objective-proof'; category='EVIDENCE';
  content=@{gate='M2';kind='objective';text='Continue Memory Permanente V4 construction without state loss after restart.'};
  content_text='Continue Memory Permanente V4 construction without state loss after restart.';
  provenance=@{trusted=$true;proof='M2_RESTART'};confidence=1.0;source='sovereign-system';source_version='M2';tags=@('M2','RESTART');changed_by='prove_gate_m2_restart'
} @{'Idempotency-Key'=('m2-restart-objective-'+$suffix)}
$mem2=PostJson '/v1/memories' @{
  namespace=$namespace; memory_key='next-action-proof'; category='EVIDENCE';
  content=@{gate='M2';kind='next_action';text='After restart, resume exactly from checkpoint and validate the same Context Pack.'};
  content_text='After restart, resume exactly from checkpoint and validate the same Context Pack.';
  provenance=@{trusted=$true;proof='M2_RESTART'};confidence=1.0;source='sovereign-system';source_version='M2';tags=@('M2','RESTART');changed_by='prove_gate_m2_restart'
} @{'Idempotency-Key'=('m2-restart-next-'+$suffix)}
$required=@($mem1.item_id,$mem2.item_id)

$session=PostJson '/v1/sessions' @{
  session_id=$sessionId; identity=@{system='MEMORIA_PERMANENTE_IA_SISTEMAS_V4';gate='M2';proof='restart'};
  scope=$namespace; objective='Prove sovereign session survives a real Memory API restart without context loss.';
  critical_rules=@('PostgreSQL is source of truth','Never keep canonical memory only in RAM','Resume from last confirmed checkpoint');
  operational_state=@{phase='M2_RESTART_PREPARED';step=21;mission_status='IN_PROGRESS';counter=987654};
  last_confirmed_action='M1 closed with pgvector 0.8.6 and HNSW'; blockers=@(); pending=@('prove restart','prove provider swap');
  next_safe_action='Restart Memory API and call resume endpoint'; active_authorizations=@('CONTINUE_CONSTRUCTION');
  required_memory_ids=$required
}
$binding=PostJson ("/v1/sessions/{0}/bindings" -f $sessionId) @{provider='openai';external_session_ref=('m2-restart-openai-'+$suffix)}
$safe=@{streaming_critical=$false;upload_unconfirmed=$false;non_idempotent_write_pending=$false;tool_call_unpersisted=$false;last_event_confirmed=$true;checkpoint_possible=$true}
$rotation=PostJson '/v1/session-rotations/request' @{session_id=$sessionId;safe_point=$safe;memory_before_mb=128.0;reason='M2_RESTART_PROOF'}
$prepared=PostJson ("/v1/session-rotations/{0}/prepare" -f $rotation.rotation_id) @{last_event_id=('m2-last-event-'+$suffix)}
$before=PostJson ("/v1/sessions/{0}/resume" -f $sessionId) @{}
$pidBefore=(Get-NetTCPConnection -LocalPort 8787 -State Listen | Select-Object -First 1).OwningProcess

Stop-ScheduledTask -TaskName 'MEMORIA-PERMANENTE-API' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$down = -not [bool](Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue)
Start-ScheduledTask -TaskName 'MEMORIA-PERMANENTE-API'
$health=$null
for($i=0;$i-lt40;$i++){
  try{$health=Invoke-RestMethod ($api+'/health') -TimeoutSec 2; if(([version]$health.version) -ge ([version]'0.5.0')){break}}catch{}
  Start-Sleep -Milliseconds 500
}
if(-not $health){throw 'API did not recover'}
$pidAfter=(Get-NetTCPConnection -LocalPort 8787 -State Listen | Select-Object -First 1).OwningProcess
$after=PostJson ("/v1/sessions/{0}/resume" -f $sessionId) @{}

$checks=[ordered]@{
  API_WAS_DOWN=$down
  API_PID_CHANGED=($pidBefore -ne $pidAfter)
  API_RECOVERED=($health.status -eq 'ok' -and ([version]$health.version) -ge ([version]'0.5.0'))
  SESSION_ID_PRESERVED=($before.session.session_id -eq $after.session.session_id -and $after.session.session_id -eq $sessionId)
  OBJECTIVE_PRESERVED=($before.session.objective -eq $after.session.objective)
  OPERATIONAL_STATE_PRESERVED=(($before.session.operational_state | ConvertTo-Json -Compress) -eq ($after.session.operational_state | ConvertTo-Json -Compress))
  CURRENT_BINDING_PRESERVED=($before.current_binding.binding_id -eq $after.current_binding.binding_id -and $after.current_binding.status -eq 'CURRENT')
  PROVIDER_PRESERVED=($after.current_binding.provider -eq 'openai')
  CHECKPOINT_ID_PRESERVED=($before.checkpoint.checkpoint_id -eq $after.checkpoint.checkpoint_id -and $after.checkpoint.checkpoint_id -eq $prepared.context_pack.checkpoint_id)
  CHECKPOINT_HASH_PRESERVED=($before.checkpoint.state_sha256 -eq $after.checkpoint.state_sha256)
  CONTEXT_PACK_ID_PRESERVED=($before.context_pack.context_pack_id -eq $after.context_pack.context_pack_id -and $after.context_pack.context_pack_id -eq $prepared.context_pack.context_pack_id)
  CONTEXT_HASH_PRESERVED=($before.context_pack.context_sha256 -eq $after.context_pack.context_sha256 -and $after.context_pack.context_sha256 -eq $prepared.context_pack.context_sha256)
  REQUIRED_MEMORY_IDS_PRESERVED=((@($after.context_pack.required_memory_ids | Sort-Object) -join ',') -eq (@($required | Sort-Object) -join ','))
  NEXT_SAFE_ACTION_PRESERVED=($after.session.next_safe_action -eq 'Restart Memory API and call resume endpoint')
  INTEGRITY_VALID=([bool]$after.integrity.all_valid)
}
$failed=@($checks.GetEnumerator() | Where-Object {-not $_.Value} | ForEach-Object {$_.Key})
$result=[ordered]@{
  generated_at=(Get-Date).ToString('o'); gate='M2'; proof='RESTART'; session_id=$sessionId; namespace=$namespace;
  pid_before=$pidBefore;pid_after=$pidAfter;api_health=$health;binding_id=$after.current_binding.binding_id;
  checkpoint_id=$after.checkpoint.checkpoint_id;checkpoint_sha256=$after.checkpoint.state_sha256;
  context_pack_id=$after.context_pack.context_pack_id;context_sha256=$after.context_pack.context_sha256;
  required_memory_ids=$required;checks=$checks;failed_checks=$failed;
  M2_RESTART_CONTINUITY_PROOF=$(if($failed.Count -eq 0){'PASS'}else{'FAIL'})
}
$evidence="$root\evidence"
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$result | ConvertTo-Json -Depth 20 | Set-Content "$evidence\M2_RESTART_CONTINUITY_PROOF.json" -Encoding UTF8
$md=@('# Gate M2 - Restart Continuity','',("**M2_RESTART_CONTINUITY_PROOF:** "+$result.M2_RESTART_CONTINUITY_PROOF),'',('Session: '+$sessionId),('Checkpoint: '+$result.checkpoint_id),('Context Pack: '+$result.context_pack_id),('Context SHA-256: '+$result.context_sha256),'','## Checks')
foreach($kv in $checks.GetEnumerator()){$md += ('- '+$kv.Key+': '+$(if($kv.Value){'PASS'}else{'FAIL'}))}
$md -join "`r`n" | Set-Content "$evidence\M2_RESTART_CONTINUITY_PROOF.md" -Encoding UTF8
$result | ConvertTo-Json -Depth 20
if($failed.Count -gt 0){exit 1}
