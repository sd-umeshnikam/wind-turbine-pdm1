<#
.SYNOPSIS
    One-shot local setup for the Wind Turbine PdM platform scaffold on Windows.

.DESCRIPTION
    Checks prerequisites (Python, Node.js/npm), then:
      1. Runs the EDA scripts against the real SCADA CSVs (scripts/setup-eda.ps1)
      2. Installs and tests all five backend Lambda services (scripts/setup-services.ps1)
      3. Installs and builds the React dashboard (scripts/setup-frontend.ps1)
    Safe to re-run - every step is idempotent (re-running npm install/pip install
    is a no-op if already satisfied).

    This only sets up the LOCAL pieces (EDA, services, frontend). It does not
    touch AWS or Databricks - see docs/manual-setup/RUNBOOK.md or
    infra/terraform/README.md for deploying to an actual environment.

.PARAMETER SkipEda
    Skip the EDA step (useful once eda/outputs/ is already populated).
.PARAMETER SkipServices
    Skip installing/testing the backend Lambda services.
.PARAMETER SkipFrontend
    Skip installing/building the frontend.

.EXAMPLE
    .\scripts\setup-all.ps1
.EXAMPLE
    .\scripts\setup-all.ps1 -SkipEda
#>
param(
    [switch]$SkipEda,
    [switch]$SkipServices,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot

function Assert-Command {
    param([string]$Name, [string]$Hint)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "'$Name' was not found on PATH. $Hint"
    }
    Write-Host "Found $Name : $($cmd.Source)" -ForegroundColor DarkGray
}

Write-Host "=== Checking prerequisites ===" -ForegroundColor Cyan
Assert-Command -Name "python" -Hint "Install Python 3.10+ from https://www.python.org/downloads/ and re-open this terminal."
Assert-Command -Name "node" -Hint "Install Node.js 18+ (LTS) from https://nodejs.org/ and re-open this terminal."
Assert-Command -Name "npm" -Hint "npm ships with Node.js - reinstall Node.js if this is missing."

if (-not $SkipEda) {
    Write-Host ""
    Write-Host "=== EDA ===" -ForegroundColor Cyan
    & (Join-Path $scriptDir "setup-eda.ps1")
}
else {
    Write-Host ""
    Write-Host "Skipping EDA (-SkipEda)" -ForegroundColor Yellow
}

if (-not $SkipServices) {
    Write-Host ""
    Write-Host "=== Backend services ===" -ForegroundColor Cyan
    & (Join-Path $scriptDir "setup-services.ps1")
}
else {
    Write-Host ""
    Write-Host "Skipping backend services (-SkipServices)" -ForegroundColor Yellow
}

if (-not $SkipFrontend) {
    Write-Host ""
    Write-Host "=== Frontend ===" -ForegroundColor Cyan
    & (Join-Path $scriptDir "setup-frontend.ps1")
}
else {
    Write-Host ""
    Write-Host "Skipping frontend (-SkipFrontend)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  - Read docs\DEVELOPER_SETUP.md for the full walkthrough"
Write-Host "  - Read docs\architecture\BLUEPRINT.md and docs\architecture\ANOMALY_DETECTION_GUIDE.md"
Write-Host "  - cd frontend\dashboard-app && npm run dev   (to browse the dashboard against mock data)"
