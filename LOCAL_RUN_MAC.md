# Mac Apple Silicon 로컬 실행

`...`은 실제 경로가 아닙니다. 현재 Codex 결과물을 그대로 실행한다면 다음 절대 경로를 사용합니다.

## Terminal 1 — Simulation API

```bash
cd "/Users/kwon._.dls/Documents/Codex/2026-08-10/backend-simulation-fastapi-websocket-ttc-frontend/outputs/symmetrical-octo-umbrella-dev-traffic-simulation/backend"

python3 -m venv .venv-simulation
source .venv-simulation/bin/activate
python -m pip install --upgrade pip
python -m pip install -r simulation/requirements.txt
export SIMULATION_NETWORK_MODE=transport-derived
python -m uvicorn simulation.main:app --reload --host 127.0.0.1 --port 8002
```

```bash
curl http://127.0.0.1:8002/health
```

Network mode:

- `transport-derived`: default development mode; derived paths and documented offsets are allowed.
- `research`: only `authoritative=true` paths; currently exits because approved Edge coverage is zero.
- `legacy`: diagnostic fallback to the previous `mobility_graph.json`.

## Terminal 2 — Legacy 3D frontend

```bash
cd "/Users/kwon._.dls/Documents/Codex/2026-08-10/backend-simulation-fastapi-websocket-ttc-frontend/outputs/symmetrical-octo-umbrella-dev-traffic-simulation/frontend"
npm install
npm run dev:legacy
```

Open `http://127.0.0.1:5173`. In development, Safety → Route Editing Mode exposes the GLB digitizer. Production builds hide it unless `.env.local` contains:

```env
VITE_SIMULATION_DEBUG=true
```

## Data and validation commands

```bash
cd "/Users/kwon._.dls/Documents/Codex/2026-08-10/backend-simulation-fastapi-websocket-ttc-frontend/outputs/symmetrical-octo-umbrella-dev-traffic-simulation/backend"
source .venv-simulation/bin/activate

python -m simulation.tools.validate_network
python -m simulation.tools.calibrate_coordinates
python -m simulation.tools.build_conflict_areas
python -m pytest -q
```

Coordinate calibration currently exits with status 2 by design because its five points are derived, not independent measurements.

## Optional Weather API

```bash
cd "/Users/kwon._.dls/Documents/Codex/2026-08-10/backend-simulation-fastapi-websocket-ttc-frontend/outputs/symmetrical-octo-umbrella-dev-traffic-simulation/weather"
python3 -m venv .venv-weather
source .venv-weather/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
```

Weather is optional; the traffic simulation retains fallback weather when port 8000 is unavailable.

## SUMO

`python -m simulation.tools.prepare_sumo` currently reports `ready=false` because SUMO and authoritative geometry are absent. After installing SUMO/TraCI and approving real network geometry, follow `SUMO_INTEGRATION.md`.

## Common errors

`simulation/requirements.txt` not found means the shell is not in the project `backend` directory. Check `pwd` and `ls simulation/requirements.txt`.

`No module named uvicorn` means the intended virtual environment is not active or requirements were not installed with that interpreter. Use `python -m pip`, then confirm with `python -m uvicorn --version`.
