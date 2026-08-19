# Runtime Network and Risk Upgrade Report

Date: 2026-08-12

## Requested scope

Implemented items 1, 2, 4, 6 and 7 from the improvement list, plus broader whole-campus traffic distribution.

## 1. Unified Network Runtime

`campus_transport_network.geojson` is now validated and converted to the Runtime Graph in memory when the backend starts.

```text
transport-derived (default) → derived geometry permitted
research                    → authoritative geometry only
legacy                      → old JSON diagnostic fallback
```

Research mode currently raises an explicit error because authoritative Edge count is zero. It never silently promotes derived geometry.

## 2. Agent-specific derived offsets

Configurable Runtime offsets reduce the visual overlap of paths derived from one vehicle centerline.

| Agent | Edge | Offset |
|---|---|---:|
| Car | allowed road | 0 m |
| Person | shared path/sidewalk | +2.8 m |
| Scooter | shared path/lane | +1.4 m |
| Scooter | allowed road | -1.0 m |

Offsets converge to zero at crosswalks, entrances, gates and parking connectors so shared conflict locations remain connected. Every Agent reports `route_geometry=derived_offset` in development mode. These offsets are not surveyed sidewalks or lanes.

## 3. Whole-campus distribution

The previous OD profiles used only 4–5 representative pairs and deterministic shortest paths. The upgrade adds:

- balanced sampling across all routeable POIs;
- inverse POI-use weighting;
- geographic separation weighting;
- bounded per-trip Edge-cost variation;
- a capped prior Edge-use penalty;
- planned and actually visited Edge Coverage metrics.

For the deterministic seed-42 default population, observed initial distribution was:

- coordinate span: over 600 m in X and 400 m in Z;
- occupied 100 m grid cells: at least 22;
- planned coverage: Car over 30%, Person over 60%, Scooter over 18% of each type's routable Edge denominator.

Scooter's denominator is 360 because it can use both the derived road and shared-path networks.

## 4. Spatial broad phase

`UniformSpatialGrid` replaces full pair enumeration in interaction and risk passes. Each Agent is indexed by its local cell and only same/neighbor Cell candidates inside the configured radius are evaluated.

One 160-Agent runtime measurement produced:

```text
All theoretical pairs: 12,720
Interaction nearby pairs: about 145
Risk nearby pairs: about 850
```

Counts change with Agent positions. A 100-Step measurement took about 51 ms per Step on the development Mac, inside the 100 ms backend update interval.

## 5. Route-based future trajectory

Each moving Agent now receives a private six-second forecast sampled every 0.25 seconds along its actual Graph segments. Risk evaluation compares synchronized samples and records:

- predicted minimum center distance;
- minimum exterior clearance;
- time to closest approach;
- swept shape overlap time;
- `prediction_model=route_swept_envelope`.

The linear velocity TTC remains only as a fallback and is exposed as `linear_ttc`. A regression test confirms that a vehicle turning away on its Route does not retain a false straight-line collision TTC.

## 6. Agent dimensions and collision shapes

| Agent | Current assumed shape |
|---|---|
| Car | 4.5 m × 1.8 m oriented box |
| Person | 0.35 m radius circle |
| Scooter | 1.8 m × 0.65 m capsule/OBB approximation |

Future screening uses directional support envelopes. Collision confirmation uses Circle–Circle, Circle–OBB or OBB–OBB overlap. Spawn separation also uses shape envelopes, preventing initial body overlap.

These dimensions are configurable project assumptions and require calibration against the actual rendered models and campus observations.

## 7. UI/API changes

- `/health` and `/api/simulation/status` expose `network_runtime`.
- Statistics expose `network_coverage` and `spatial_broad_phase`.
- Safety UI shows Runtime mode and planned/visited coverage by Agent type.
- Risk cards show exterior clearance and prediction model.
- Risk events include collision envelope, shape overlap, linear TTC and Route prediction fields.

## 8. Validation

- Python: 44 passed.
- Frontend Node: 140 passed.
- Vitest: 55 passed.
- Legacy build: passed.
- VWorld build: passed.
- Network validator: 0 errors, 8 existing disclosed warnings.
- Browser: Runtime mode, Coverage, movement clock and Route-shaped risk fields confirmed.

## 9. Remaining limitation

The distribution and offsets improve development behavior but do not replace missing field data. All 364 Edge features remain derived and zero are authoritative. Actual sidewalks, lanes, crosswalk polygons, entrance positions and observed OD demand are still required for research-valid campus claims.
