<#
.SYNOPSIS
    Installs the EDA Python dependencies and runs all five EDA scripts against
    the real SCADA CSVs.

.PARAMETER SkipInstall
    Skip the `pip install` step (use if dependencies are already installed).

.EXAMPLE
    .\scripts\setup-eda.ps1
#>
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $SkipInstall) {
    Write-Host "Installing EDA Python dependencies (pandas, matplotlib, numpy, pyarrow)..." -ForegroundColor Cyan
    python -m pip install --quiet pandas matplotlib numpy pyarrow
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit code $LASTEXITCODE)" }
}

$scripts = @(
    "eda/scripts/01_data_quality.py",
    "eda/scripts/02_event_analysis.py",
    "eda/scripts/03_sensor_profiling.py",
    "eda/scripts/04_degradation_trends.py",
    "eda/scripts/05_fleet_summary.py"
)

foreach ($script in $scripts) {
    Write-Host ""
    Write-Host "=== Running $script ===" -ForegroundColor Cyan
    python $script
    if ($LASTEXITCODE -ne 0) { throw "$script failed (exit code $LASTEXITCODE)" }
}

Write-Host ""
Write-Host "EDA complete. See eda\EDA_REPORT.md and eda\outputs\charts\." -ForegroundColor Green
