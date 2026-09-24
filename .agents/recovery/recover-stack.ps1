$ErrorActionPreference='Stop'
& 'C:\New Projet\MEMORIA-PERMANENTE\.agents\recovery\start-postgres.ps1'
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& 'C:\New Projet\MEMORIA-PERMANENTE\.agents\recovery\start-phoenix.ps1'
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& 'C:\New Projet\MEMORIA-PERMANENTE\.agents\recovery\start-api.ps1'
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Write-Output 'STACK_RECOVERED'
