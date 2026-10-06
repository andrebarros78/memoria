param(
  [Parameter(Mandatory=$true)][string]$ConversationRef
)
$ErrorActionPreference='Stop'
$Root='C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'
$Python='C:\New Projet\WMCP 3.1\.venv\Scripts\python.exe'
$Script=Join-Path $Root 'scripts\prove_real_conversation_backfill_attempt.py'
if(-not (Test-Path $Python)){ throw 'WMCP 3.1 homologated Python runtime missing' }
if(-not (Test-Path $Script)){ throw 'real conversation proof script missing' }
& $Python $Script --conversation-ref $ConversationRef
exit $LASTEXITCODE
