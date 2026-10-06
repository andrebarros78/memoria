$ErrorActionPreference='Stop'
& 'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\.agents\recovery\start-postgres.ps1'
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& 'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\.agents\recovery\start-phoenix.ps1'
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& 'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\.agents\recovery\start-api.ps1'
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Write-Output 'STACK_RECOVERED'
