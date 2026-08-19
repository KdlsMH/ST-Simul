$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot "backend"
$frontendPath = Join-Path $projectRoot "frontend"

$backend = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", "Set-Location -LiteralPath '$backendPath'; `$env:SIMULATION_PROVIDER='internal'; python -m uvicorn simulation.main:app --reload --port 8002"
$frontend = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", "Set-Location -LiteralPath '$frontendPath'; npm run dev:legacy"

Write-Host "Simulation backend: http://127.0.0.1:8002"
Write-Host "Legacy frontend:    http://127.0.0.1:5173"
Write-Host "Close the two service windows to stop the simulation."
Wait-Process -Id $backend.Id, $frontend.Id
