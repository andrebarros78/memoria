[CmdletBinding()]
param(
    [string]$Baseline = (Join-Path $PSScriptRoot 'baselines\retrieval-quality-canonical-8787.json'),
    [string]$Phoenix = 'http://127.0.0.1:6006'
)

$ErrorActionPreference = 'Stop'
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$Auditor = Join-Path $PSScriptRoot 'retrieval_quality_auditor.py'

if (-not (Test-Path $Python)) {
    throw 'Auditor environment is not provisioned. Run provision.ps1 first.'
}
if (-not (Test-Path $Auditor)) {
    throw "Auditor entrypoint missing: $Auditor"
}

$PreviousPythonPath = $env:PYTHONPATH
$ExitCode = 1
try {
    # -I plus an empty PYTHONPATH prevents connector/runtime imports from leaking into the auditor.
    $env:PYTHONPATH = ''
    & $Python -I $Auditor --baseline $Baseline --phoenix $Phoenix
    $ExitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
exit $ExitCode
