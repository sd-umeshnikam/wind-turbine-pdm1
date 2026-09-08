<#
.SYNOPSIS
    Installs dependencies and builds (or runs the dev server for) the React
    dashboard at frontend/dashboard-app.

.PARAMETER Dev
    Start the Vite dev server (http://localhost:5173) instead of producing a
    production build. Runs in the foreground - stop it with Ctrl+C.

.EXAMPLE
    .\scripts\setup-frontend.ps1
.EXAMPLE
    .\scripts\setup-frontend.ps1 -Dev
#>
param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$appPath = Join-Path $repoRoot "frontend\dashboard-app"

Push-Location $appPath
try {
    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit code $LASTEXITCODE)" }

    if ($Dev) {
        Write-Host "Starting dev server (Ctrl+C to stop) - runs against mock data unless VITE_APPSYNC_URL is set..." -ForegroundColor Cyan
        npm run dev
    }
    else {
        Write-Host "Building production bundle..." -ForegroundColor Cyan
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit code $LASTEXITCODE)" }
        Write-Host ""
        Write-Host "Build output: frontend\dashboard-app\dist" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
