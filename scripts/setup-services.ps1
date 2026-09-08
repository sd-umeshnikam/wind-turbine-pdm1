<#
.SYNOPSIS
    Installs dependencies and runs the test suite for each backend Lambda
    service under services/. Each service is independent - a failure in one
    still lets you see results for the others by re-running with -Only.

.PARAMETER Only
    Run against a single service name (e.g. "telemetry-api") instead of all five.

.EXAMPLE
    .\scripts\setup-services.ps1
.EXAMPLE
    .\scripts\setup-services.ps1 -Only telemetry-api
#>
param(
    [string]$Only
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

$allServices = @("telemetry-api", "prediction-api", "alerting-service", "digital-twin-service", "ingestion-trigger")
$services = if ($Only) { @($Only) } else { $allServices }

foreach ($service in $services) {
    $path = Join-Path $repoRoot "services\$service"
    if (-not (Test-Path $path)) {
        throw "Unknown service '$service' (expected one of: $($allServices -join ', '))"
    }

    Write-Host ""
    Write-Host "=== $service ===" -ForegroundColor Cyan
    Push-Location $path
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "$service : npm install failed (exit code $LASTEXITCODE)" }

        npm test
        if ($LASTEXITCODE -ne 0) { throw "$service : npm test failed (exit code $LASTEXITCODE)" }
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "All backend services installed and tested." -ForegroundColor Green
