# Simulation Run Guide

## Backend

PowerShell:

```powershell
cd backend
python -m venv .venv-simulation
.\.venv-simulation\Scripts\Activate.ps1
python -m pip install -r simulation/requirements.txt
$env:SIMULATION_PROVIDER = "internal"
python -m uvicorn simulation.main:app --reload --port 8002
```

macOS/Linux activation is `source .venv-simulation/bin/activate`. Optional deterministic debugging uses one value: `SIMULATION_SEED=42`.

## Frontend

```powershell
cd frontend
npm install
npm run dev:legacy
```

Open `http://127.0.0.1:5173`, choose one Scenario and Agent counts, then press Start. The Safety panel provides Pause, Resume, Reset, speed control, live statistics, Agent detail, recent trajectory, and risk events.

## Optional one-command development start

After Python and npm dependencies are installed:

```powershell
.\scripts\start_simulation.ps1
```

## Validation

```powershell
cd backend
python -m compileall simulation tests
python -m pytest
python -m simulation.tools.validate_network

cd ..\frontend
npm test
npm run build
npm run build:vworld
```

## SUMO

Set `SIMULATION_PROVIDER=sumo`, `SUMO_BINARY`, and `SUMO_CONFIG_PATH`. If prerequisites are unavailable, the health response explains the fallback to the Internal Provider. See `SUMO_INTEGRATION.md`.
