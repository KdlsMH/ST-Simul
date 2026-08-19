# Risk Engine Specification

## Pair metrics

For supported car–car, car–person, car–scooter, scooter–person and scooter–scooter pairs, the Internal Risk Engine retains raw metrics:

- Euclidean distance.
- Relative and closing velocity from velocity vectors.
- Approaching test using the distance derivative.
- Predicted minimum distance and closest time.
- Graph Route prediction sampled every 0.25 s over a configurable six-second horizon.
- Linear path intersection/TTC as a fallback when Route samples are unavailable.
- Shape-aware collision envelope, minimum exterior clearance, and swept overlap time.
- Time headway.
- Required deceleration based on current closing motion.
- PET when both Agents use the same Conflict Area.

Interaction state is classified as `NONE`, `APPROACHING`, `FOLLOWING`, `CROSSING`, `CONFLICT`, `BRAKING`, or `AVOIDING`. Safety events distinguish collision, near miss, traffic conflict, unsafe crossing, sudden braking, vehicle yielding, and scooter yielding.

Current shapes are a 4.5 m × 1.8 m oriented vehicle box, 0.35 m pedestrian circle, and 1.8 m × 0.65 m scooter capsule/OBB approximation. Future screening uses directional support envelopes; `COLLISION` confirmation uses Circle–OBB or OBB–OBB overlap. These dimensions are project assumptions.

Pair enumeration uses a uniform spatial grid, then rejects distant or unreachable pairs before trajectory-envelope calculations. Exact candidate counts vary as Agents move and are exposed in live statistics.

## Conflict Area and PET

`conflict_areas.json` currently contains 14 derived areas corresponding to the 14 mapped `CW_*` IDs. Their centre locations follow the mapped crosswalk data; the polygon width is the explicitly assumed 3.0 m default, not a surveyed outline. A manager records Agent entry/exit transitions:

```text
PET = later Agent entry time - earlier Agent exit time
```

Simultaneous occupancy records PET `0` and overlap. Negative/overlapping physical interpretations should be analyzed as conflict, not treated as a safe PET. These polygons are provisional until surveyed crosswalk outlines are available.

## Risk event payload

```json
{
  "risk_level": "danger",
  "risk_score": 87,
  "ttc": 1.2,
  "pet": 0.8,
  "minimum_distance": 0.7,
  "minimum_clearance": 0.1,
  "prediction_model": "route_swept_envelope",
  "relative_speed": 5.1,
  "required_deceleration": 3.4,
  "time_headway": 1.1,
  "interaction_type": "crossing",
  "conflict_area_id": "CA_CW_019"
}
```

Thresholds in `risk_config.json` are configurable project assumptions. They are not described as copied research parameters.

## Agent evaluation and replay

Agent metrics include stop/brake/hard-brake/conflict/near-miss counts, risk exposure, minimum TTC/PET, maximum risk, travel/wait/walk time, speeding and wrong-way measures as relevant. Trajectories use a bounded sampled ring buffer and store timestamp, XYZ, speed, heading, Edge, state, and risk.

Risk events capture five seconds of available pre-event trajectory and finalize five seconds of post-event trajectory. Endpoints:

- `GET /api/simulation/events/{event_id}`
- `GET /api/simulation/timeline`

## Limits

Risk accuracy cannot exceed geometry and behavior calibration accuracy. Current Conflict Areas and paths are derived, and events are suitable for software evaluation—not campus safety claims—until network and demand calibration are completed.
