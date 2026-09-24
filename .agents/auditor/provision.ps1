[CmdletBinding()]
param(
    [switch]$Recreate
)

$ErrorActionPreference = 'Stop'
$AuditorRoot = $PSScriptRoot
$ProjectRoot = (Resolve-Path (Join-Path $AuditorRoot '..\..')).Path
$Venv = Join-Path $AuditorRoot '.venv'
$BootstrapPython = 'C:\Python313\python.exe'
$Lock = Join-Path $AuditorRoot 'requirements.lock.txt'

if (-not (Test-Path $BootstrapPython)) {
    throw "Canonical Python runtime missing: $BootstrapPython"
}
if (-not (Test-Path $Lock)) {
    throw "Auditor lock file missing: $Lock"
}
if ($Recreate -and (Test-Path $Venv)) {
    Remove-Item $Venv -Recurse -Force
}
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    & $BootstrapPython -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Python = Join-Path $Venv 'Scripts\python.exe'
$PreviousPythonPath = $env:PYTHONPATH
try {
    # The parent S-WMCP process exports its own source tree via PYTHONPATH.
    # Auditor execution is deliberately isolated from that connector runtime.
    $env:PYTHONPATH = ''
    & $Python -m pip install --disable-pip-version-check --only-binary=:all: --requirement $Lock
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -I -c "import importlib.util,sys,agents,phoenix.otel,openinference.semconv.trace; visible=importlib.util.find_spec('windows_mcp') is not None; print('AUDITOR_ENV_READY' if not visible else 'AUDITOR_ENV_CONTAMINATED'); sys.exit(1 if visible else 0)"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
