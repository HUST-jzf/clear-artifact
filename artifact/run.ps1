param(
    [string]$RunDir = "runs/R10/attempt1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$cli = Join-Path $root "sources/R3_temporal/cli/temporal.exe"
if (-not (Test-Path $cli)) {
    python (Join-Path $root "sources/R3_temporal/cli/assemble.py")
    if ($LASTEXITCODE -ne 0) { throw "failed to assemble sources/R3_temporal/cli/temporal.exe" }
}

$runPath = Join-Path $root $RunDir
if (Test-Path (Join-Path $runPath "reproduction.json")) {
    throw "Refusing to overwrite an existing R10 reproduction: $runPath"
}
New-Item -ItemType Directory -Force -Path $runPath | Out-Null

$venv = Join-Path $runPath "env"
$python = Join-Path $venv "Scripts/python.exe"
if (-not (Test-Path $python)) {
    python -m venv $venv
}

$env:PIP_NO_INDEX = "1"
$wheel = Join-Path $root "runs/U07/attempt1/dist/clear_assurance-2.0.0-py3-none-any.whl"
& $python -m pip install --no-index --no-deps --force-reinstall --disable-pip-version-check $wheel
if ($LASTEXITCODE -ne 0) { throw "wheel install failed with exit code $LASTEXITCODE" }

& $python (Join-Path $root "artifact/reproduce.py") --run-dir $RunDir
if ($LASTEXITCODE -ne 0) { throw "reproduction failed with exit code $LASTEXITCODE" }
