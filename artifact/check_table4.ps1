# Recompute the studies that the paper reports outside the 6,749-check suite.
# Writes reports under runs/R10/table4-check and does not modify frozen runs.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$outDir = Join-Path $root "runs/R10/table4-check"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$jobs = @(
    @{ Name = "R45"; Script = "scripts/verify_r45.py"; Run = "runs/R45/attempt2"; Checks = 273 },
    @{ Name = "R46"; Script = "scripts/verify_r46.py"; Run = "runs/R46/attempt1"; Checks = 111 },
    @{ Name = "R47"; Script = "scripts/verify_r47.py"; Run = "runs/R47/attempt1"; Checks = 59 },
    @{ Name = "R48"; Script = "scripts/verify_r48.py"; Run = "runs/R48/attempt2"; Checks = 13 },
    @{ Name = "R49"; Script = "scripts/verify_r49.py"; Run = "runs/R49/attempt2"; Checks = 121 }
)

foreach ($job in $jobs) {
    $out = Join-Path $outDir ($job.Name + "_verification.json")
    & python $job.Script --run $job.Run --out $out
    if ($LASTEXITCODE -ne 0) {
        throw "$($job.Name) verification failed with exit code $LASTEXITCODE"
    }
}

Write-Host "table4 studies passed: R45 273/273, R46 111/111, R47 59/59, R48 13/13, R49 121/121"
