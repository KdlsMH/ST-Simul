# Real-time Traffic Simulation Architecture

```text
Campus transport network (loaded and validated once)
                    │
                    ▼
             FastAPI service
                    │
          SIMULATION_PROVIDER
           ┌────────┴────────┐
           ▼                 ▼
   Internal Provider     SUMO / TraCI
           └────────┬────────┘
                    ▼
             OD → Trip → Graph
                    │
        Car / Person / E-Scooter
                    │
     spatial-grid nearby interactions
                    │
      TTC / PET / conflict / collision
                    │
       bounded events and trajectories
                    │
       WebSocket snapshot + compact delta
                    │
           React Three Fiber / Three.js
```

## Runtime flow

Server start loads and validates the network, scenarios, OD demand, behavior profiles, risk config, conflict areas, and traffic signals once. A single asynchronous loop advances the selected Provider outside request handlers. Routes are created only when a Trip starts or its destination changes; ordinary ticks interpolate on the existing route.

The Interaction Manager and Risk Engine use uniform spatial grids. Distant/unreachable pairs exit before route-envelope prediction. Risk events are bounded by `risk_config.json`; live statistics retain scalar counts/minima without retaining an unbounded event list. Agent trajectories are fixed-size ring buffers and are released when an Agent despawns.

The first WebSocket message is a full snapshot. Following messages contain compact entity changes, removed IDs, new risk events, current statistics, signals, and timeline data. The frontend merges updates by Agent ID and reuses the existing Three.js Object3D for movement.

## Provider boundary

- `SIMULATION_PROVIDER=internal`: default, development, UI verification, and fallback.
- `SIMULATION_PROVIDER=sumo`: TraCI-backed runtime when SUMO executable, config, network, and Python module are available.
- `SIMULATION_SEED=42`: optional single deterministic seed for the Internal Provider. It never triggers repeated execution.
