# Full Implementation Report

Date: 2026-08-12

## 1. 기존 시스템 분석

The existing project already had OD/Trip/Dijkstra routing, lifecycle, interactions, TTC, WebSocket rendering, Agent selection, bounded trajectory and provider separation. The runtime was the Internal provider. The fundamental defect was not one merged route but multiple graph edges whose vehicle and derived pedestrian geometries substantially overlapped.

## 2. Geometry 문제

`road_zones_wgs84.geojson` supplies 92 road polygons. No authored vehicle centerline, sidewalk, bike/scooter lane, or physical crosswalk polygon exists. `common_elemetns.json` has 24 crosswalk IDs and 88 road IDs, but all 191 element geometries are null. `campus_base.geojson` and `zones.json` are empty. The GLB does not expose semantic road/sidewalk lane names.

## 3. 실제 Network 구축 내용

Created `campus_transport_network.geojson`, a provenance-aware multimodal Source of Truth schema. The existing 364 edges were migrated only for traceability and remain `derived=true`, `authoritative=false`. A new GLB Route Editing Mode exports non-derived but still unapproved drafts. No geometry was falsely promoted to surveyed.

## 4. Vehicle Lane 구축

Schema, policy, digitizer option, debug rendering, builder and validator support `vehicle_lane`. Current physical vehicle lines remain derived `allowed_road`; authoritative vehicle-lane coverage is 0.

## 5. Sidewalk 구축

Schema/policy/digitizer/debug support real `sidewalk` lines. Current `shared_path` lines retain `source=derived_from_vehicle_network` and low confidence. They were not renamed as surveyed sidewalks.

## 6. Crosswalk 구축

Fourteen of 24 metadata IDs are mapped. Physical geometry coverage remains 0. The system now separates pedestrian crosswalk edges from vehicle lanes that pass the mapped location, supports polygon or centerline+width authoring, and generates 14 clearly derived Conflict Areas. Forty-seven graph edges are connections—not 47 real crosswalks.

## 7. Scooter Network 구축

Policy supports scooter/bike lane, shared path, conditional allowed road, slow/dismount crosswalk and required scooter-parking connectors. These rules are configuration values. There is no authoritative campus scooter lane yet.

## 8. Coordinate Alignment

`CoordinateTransform` now handles WGS84, simulation, Three.js and SUMO spaces. A 5-point similarity fit reports translation, scale, rotation, inversion, residuals and RMSE. Current points are derived from the existing transform, so the report correctly records `alignment_accepted=false` despite near-zero regression error.

## 9. Mobility Graph 변경

Added GeoJSON→Graph builder and structural/semantic validator. The validated unified GeoJSON is now the default in-memory Runtime source. Development mode permits derived geometry; research mode rejects it. `--authoritative-only` produces no route edges, accurately demonstrating that real geometry is still missing.

## 10. SUMO 실제 연동

Improved provider preflight, TraCI stepping, person extraction, e-scooter type mapping and SUMO coordinate conversion. Added authoritative-only SUMO input generation. Actual SUMO execution is **not complete**: `sumo`, `sumo-gui`, `traci`, and authoritative edges were absent; `campus.net.xml` was therefore not fabricated.

## 11. 차량 Behavior

JSON profiles now define cautious/normal/aggressive differences in desired speed, acceleration, deceleration, emergency deceleration, minimum gap, headway and yield tendency. Values are implementation assumptions. Existing car-following, intersection turn slowing and yielding remain active.

## 12. 보행자 Behavior

Student/staff/visitor/group/distracted profiles exist with walking and crossing differences. Person separation, crosswalk waiting/crossing, jaywalking and building states remain. Group profile metadata exists, but cohesive 2–5 person shared-trip movement is not yet a validated completed feature.

## 13. 킥보드 Behavior

Safe/normal/aggressive profiles now alter speed, gaps, braking, yielding and wrong-way probability. Vehicle and pedestrian interactions constrain scooter speed. SUMO e-scooter vTypes are generated only as assumed starting profiles.

## 14. Interaction

Car–car following, car–person crosswalk yield, car–scooter approaching/crossing, and scooter–person separation/avoidance are retained and regression-tested.

Representative execution:

- Car–person: a crossing Person causes the approaching Car target speed to fall and state to become BRAKING/CONFLICT.
- Car–scooter: intersecting velocity vectors produce a predicted conflict point, TTC and a risk event; both receive avoidance/braking constraints.
- Scooter–person: decreasing separation lowers scooter target speed and can produce Near Miss.
- Car–car: a rear vehicle within the longitudinal gap is constrained by leader speed.

## 15. TTC / PET / Near Miss

Risk events now retain distance, relative/closing speed, vector TTC, predicted minimum distance, conflict point, time headway, required deceleration, PET, risk score and classification. PET is based on Conflict Area exit/entry transitions; overlap is recorded as zero. Parameters remain configurable project assumptions.

## 16. SUMO SSM 검증

Added a comparison tool for ordered Custom/SUMO TTC with MAE/RMSE/relative error and an explicit warning that pedestrian coverage is not assumed. No SSM result exists because SUMO was not run. Stable event matching remains required before research validation.

## 17. 실제 데이터 Calibration

Introduced the shared observation schema and converted three existing YOLO gate events. `world_x/world_z` remain null without homography. MAE/RMSE/relative-error utilities and OD weight normalization/routeability checks exist. Three events are insufficient for demand calibration.

## 18. Agent-level Evaluation

Metrics now include conflicts, stops, hard brakes, near misses, risk exposure, minimum TTC/PET and maximum risk in addition to type-specific travel/wait/speed/jaywalking/wrong-way measures. Trajectory samples store time, XYZ, speed, heading, Edge, state and risk in a bounded ring buffer.

## 19. Three.js Digital Twin 변경

The existing Canvas/UI remains. Development Safety UI adds Route Editing Mode, a colored network debug layer, Point editing and draft GeoJSON download. Browser QA confirmed a two-point sidewalk draft appears as a yellow line. Production hides editing unless explicitly enabled.

## 20. Scenario 시스템

Time/weather/density/congestion scenarios and behavior profiles are defined in JSON. The user selects one scenario and runs it through the live simulation controls.

## 21. 테스트 결과

Executed results at final verification time are recorded in the handoff summary. During implementation:

- Python: 44 passed after adding Runtime Source-of-Truth, network coverage, derived offsets, spatial broad phase, Route prediction and shape-overlap tests.
- Frontend Node tests: 140 passed.
- Vitest: 55 passed.
- Legacy production build: passed.
- VWorld production build: passed.
- Network validator: PASS with 0 errors and 8 disclosed warnings.
- Browser QA: simulation WebSocket connected; 30/100/30 Agents, scenarios, timeline, Route Editing Mode, Data Quality, simulation clock advancement and two-point GLB digitizing worked.

## 22. 실제 데이터와 Derived 데이터 구분

| Category | Current status |
|---|---|
| Road-zone polygons | CAD/GIS-derived source polygons |
| Transport edges | 364 derived, 0 authoritative |
| Crosswalk IDs | 24 metadata IDs |
| Mapped crosswalk IDs | 14 derived mappings |
| Crosswalk physical polygons | 0 |
| Building entrances | 6 snapped/derived |
| Parking vehicle connections | 2 snapped/derived |
| Independent coordinate controls | 0 |
| YOLO observations | 3 observed event rows; no world coordinates |

## 23. 현재 남아있는 한계

- Survey/CAD-authoritative lane, sidewalk, crosswalk and scooter geometry is absent.
- Two derived crosswalk edges lack an independent pedestrian connection warning.
- Six POI nodes intentionally share coordinates with a road node.
- SUMO/TraCI is not installed and a valid `.net.xml` cannot be generated from zero approved edges.
- OD/behavior/risk values are not campus-calibrated.
- Pedestrian groups have profiles but not validated cohesive group-trip dynamics.
- WebSocket still sends full snapshots; delta transport/instancing remain performance follow-ups.

## 24. 다음 연구 단계

1. Digitize/import and field-review vehicle lanes, sidewalks, crosswalk polygons, entrances and parking links.
2. Replace five derived alignment pairs with independent controls and accept an RMSE threshold.
3. Approve features, run the validator with zero semantic warnings, then generate `campus.net.xml`.
4. Install SUMO/TraCI on the research machine and validate TraCI entity/traffic-light lifecycle.
5. Aggregate gate observations into fixed windows, collect pedestrian/scooter counts, and calibrate demand/behavior.
6. Validate Custom TTC against SUMO SSM or observed cases where supported.

## Final architecture

```text
Real Campus / CCTV / Survey
          │
    Observation Data
          │
 Calibration + Provenance
          │
  Authoritative Network
          │
   ┌──────┴──────┐
Internal        SUMO
Provider       Provider
   └──────┬──────┘
        FastAPI
  OD / Risk / Statistics
 TTC / PET / Near Miss
          │
       WebSocket
          │
 React Three Fiber Canvas
 Agents / Network / Timeline
```

## Phase reports

### Phase 1 — Data / Geometry

- Implemented: audit, unified schema, provenance, policy, GLB digitizer and debug UI.
- Remaining derived data: all 364 edges.
- Limitation: no real geometry supplied.
- Next: independent authoring/review.

### Phase 2 — Network

- Implemented: builder, validator, Agent connectivity, coordinate fit, Conflict Areas.
- Tests: structural PASS; 8 warnings retained.
- Limitation: authoritative-only graph is empty.

### Phase 3 — SUMO

- Implemented: preflight, adapter improvements and generator.
- Observed: `ready=false`.
- Limitation: executable/TraCI/approved network absent.

### Phase 4 — Safety

- Implemented: TTC/PET/raw metrics/replay/timeline and Agent minima.
- Limitation: safety validity depends on geometry/calibration.

### Phase 5 — Real Data

- Implemented: observation contract/import and comparison metrics.
- Limitation: insufficient observations and no homography.

### Phase 6 — Digital Twin UX

- Implemented: existing selection/trajectory plus editor, debug layer and timeline.
- Limitation: full risk replay playback controls remain API/data-ready rather than a complete scrubber UI.

### Phase 7 — Runtime validation

- Implemented: live statistics, network validation, and provider-level TTC comparison.
- Limitation: results are not research-valid before Phase 1/3/5 prerequisites.
