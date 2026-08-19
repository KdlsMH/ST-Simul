# Calibration and Validation

## Coordinate alignment

`CoordinateTransform` supports:

- WGS84 ↔ simulation local meters.
- simulation ↔ Three.js.
- SUMO ↔ simulation.

Run the 5+ control-point fit:

```bash
cd backend
python -m simulation.tools.calibrate_coordinates
```

The current five control points are generated from the existing transform and are not independent survey points. Their numerical RMSE is effectively zero, but `alignment_accepted=false` because independent evidence is absent. Replace them with measured Main Gate, Central Intersection, Engineering 3, Library, and Student Center correspondences before accepting alignment.

The fit evaluates translation, uniform scale, rotation and Z inversion. Acceptance requires both RMSE below the configured threshold and every point marked `independent=true`.

## Observation contract

```json
{
  "timestamp": "2026-05-04 21:33:43",
  "location": "MAIN_GATE",
  "type": "car",
  "direction": "in",
  "count": 1,
  "source": "yolo",
  "world_x": null,
  "world_z": null
}
```

The existing directional YOLO CSV was converted to `simulation/data/observations/yolo_gate_observations.json`. Because no camera homography exists, world coordinates remain null.

Convert a new file:

```bash
python -m simulation.tools.import_vision_observations input.csv \
  --location MAIN_GATE \
  --output simulation/data/observations/main_gate.json
```

## Calibration metrics

`simulation.calibration.metric_pair` reports MAE, RMSE, and mean relative error for equal-length observed/simulated series. Intended comparisons include traffic volume, average speed, waiting time, and OD flow.

Calibration requires matching aggregation windows and locations. Event rows from the current YOLO CSV must first be grouped into a defined interval such as five minutes; the three sample events are insufficient for a calibrated demand model.

## OD validation

The existing OD file uses positive weights rather than authored probabilities. `ODManager` validates every OD pair, verifies routeability for the Agent type, normalizes weights, and checks the normalized probability sum equals 1. This is mathematical validation only; the weights remain demonstration demand until observation/timetable calibration.
