# SUMO Integration

## Provider boundary

```text
SimulationProvider
├── InternalSimulationProvider  # UI, tests, fallback, debugging
└── SumoSimulationProvider      # TraCI runtime when prerequisites pass
    └── TraCI
```

The frontend consumes the same Agent contract from either provider. Three.js performs interpolation/rendering only; it is not the traffic physics engine.

## Current status

SUMO was not installed in the audited Mac environment, `traci` was unavailable, and the transport network had zero authoritative edges. Consequently SUMO was not run and no `campus.net.xml` was fabricated. `generation_status.json` records `ready=false`.

The provider checks all of the following before selection:

1. `SUMO_BINARY` resolves to an executable.
2. `SUMO_CONFIG_PATH` exists.
3. The config declares a `net-file` and that network file exists.
4. Python can import `traci`.

Any failure returns the Internal provider with an explicit health message.

## Network preparation

```bash
cd backend
python -m simulation.tools.prepare_sumo
```

The tool emits `campus.nod.xml`, `campus.edg.xml`, car/e-scooter vTypes, route/person/additional/detector/signal files and `campus.sumocfg`. It deliberately excludes `derived=true` or `authoritative=false` edges. When `netconvert` and approved edges exist, it builds `campus.net.xml`.

Profile numbers in the generated vTypes are **implementation-specific assumptions**, not paper-derived or campus-calibrated parameters.

## Run after prerequisites are met

```bash
export SIMULATION_PROVIDER=sumo
export SUMO_BINARY="$(command -v sumo)"
export SUMO_GUI_BINARY="$(command -v sumo-gui)"
export SUMO_CONFIG_PATH="$PWD/simulation/sumo/campus.sumocfg"
python -m uvicorn simulation.main:app --host 127.0.0.1 --port 8002
```

TraCI maps passenger vehicles to `car`, `e_scooter*` vTypes to `scooter`, and SUMO persons to `person`. SUMO positions pass through `CoordinateTransform.sumo_to_simulation`.

## SSM comparison

After SUMO SSM output exists:

```bash
python -m simulation.tools.compare_sumo_ssm custom_events.json ssm.xml
```

The current tool performs an ordered TTC comparison and reports MAE/RMSE/relative error. Field validation requires a stable event-ID/time/location matching rule. It does not assume SUMO SSM provides equivalent pedestrian-conflict coverage.
