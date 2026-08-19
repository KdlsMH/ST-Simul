# Full Simulation Audit

Audit date: 2026-08-12 (Asia/Seoul)

## Executive finding

The application is a working Web digital-twin **visualization and internal microscopic simulation prototype**, but it is not yet a calibrated campus digital twin. OD trips, lifecycle, pair interactions, WebSocket rendering, agent details, trajectory, and provider boundaries exist. The transport geometry is the limiting factor: every one of the 364 routing edges is derived, and zero edges are independently surveyed or approved as authoritative.

## Architecture

| Area | Current implementation | Audit result |
|---|---|---|
| Frontend | React 18, Three.js, React Three Fiber; Legacy and VWorld builds | Both are maintained; traffic simulation is rendered only in the existing Canvas |
| Backend | FastAPI, REST, WebSocket, async simulation/weather tasks | Simulation loop is an asyncio task and does not perform blocking weather I/O on the event loop |
| Simulation | OD, Trip, Dijkstra graph, lifecycle, interactions, risk and statistics | Internal provider is operational; SUMO provider is optional |
| Vision | YOLO directional vehicle count PoC | Pixel detections are not converted to world coordinates without calibration |
| Weather | Optional FastAPI weather/microclimate service | Simulation continues with default conditions when unavailable |
| Common data | `common_elemetns.json`, empty `campus_base.geojson` and `zones.json` | IDs exist, but common element geometries are all null |
| 3D asset | `frontend/public/uni.glb`, 2,450,440 bytes | Contains `Topography` and some `BLD_*` meshes; no semantic Road/Sidewalk/BikeLane mesh layer |
| Tests | Python, Node test, Vitest, two Vite builds | See `FULL_IMPLEMENTATION_REPORT.md` for executed results |

## Current transport network

Source: `backend/simulation/data/campus_transport_network.geojson`.

| Metric | Value |
|---|---:|
| Nodes | 106 |
| Edges | 364 |
| POIs | 14 |
| `derived=true` edges | 364 |
| `derived=false` edges | 0 |
| Authoritative edges | 0 |
| Car-allowed edges | 178 |
| Person-allowed edges | 184 |
| Scooter-allowed edges | 354 |

Edge kinds:

| Kind | Count |
|---|---:|
| `allowed_road` | 172 |
| `shared_path` | 125 |
| `crosswalk` | 47 |
| `building_entrance` | 6 |
| `vehicle_gate` | 4 |
| `pedestrian_gate` | 4 |
| `parking_connection` | 2 |
| `parking_walk` | 2 |
| `scooter_parking_connection` | 2 |

All three Agent graphs form one connected component for the current derived network. This proves software connectivity, not spatial accuracy.

## Geometry provenance

| Dataset | Classification | Finding |
|---|---|---|
| `road_zones_wgs84.geojson` | GIS-exported / CAD-derived | 92 Polygon/MultiPolygon road zones; metadata names `road_zone_sketchup.dxf`, EPSG:5179→4326 |
| `routes.geojson` | derived | 92 principal-axis centerlines generated inside those polygons |
| `common_elemetns.json` | metadata only / unknown geometry | 191 IDs; every `geometry` is null |
| `campus_base.geojson` | missing | 0 bytes |
| `zones.json` | missing | 0 bytes |
| `mobility_graph.json` | derived | Vehicle topology and copied derived walk topology |
| `uni.glb` | CAD/GLB asset, semantic transport layers unknown | Buildings/terrain visible; no machine-identifiable lane/sidewalk layer |
| `building_entrances.json` | snapped/derived | Six entrances snapped from GLB building hints to the derived route network |
| parking connections | snapped/derived | Two parking vehicle connectors; not surveyed entrances |

No derived feature is described as surveyed. The unified GeoJSON records `source`, `confidence`, `derived`, `authoritative`, and `review_status` where applicable.

## Crosswalk audit

- `CW_*` IDs in common metadata: 24.
- `CW_*` records with geometry: 0.
- IDs mapped to road zones: 14.
- Pedestrian crosswalk graph edges: 47. This is **not** a count of physical crosswalks; multiple graph connections refer to one mapped ID.
- Derived Conflict Areas: 14, one for each mapped ID.
- Actual crosswalk Polygon coverage: 0/24.
- Validator warnings: two graph crosswalk edges lack an independent pedestrian-side connection, plus six intentional co-located POI/node warnings.

## Provider audit

`InternalSimulationProvider` is the active and tested provider. `SumoSimulationProvider` has executable/config/TraCI preflight and vehicle/person/e-scooter extraction. On this Mac audit environment:

- `sumo`: not installed.
- `sumo-gui`: not installed.
- Python `traci`: not installed.
- authoritative transport edges available to `netconvert`: 0.
- `campus.net.xml`: not built.

Provider selection therefore correctly falls back to Internal. SUMO execution is not claimed.

## Audit conclusion

The priority blocker is authoritative multimodal geometry. The new Route Editing Mode can digitize GLB-aligned drafts, but those drafts remain `authoritative=false` until coordinate, topology, and field review pass. Only after approved vehicle lanes, sidewalks, crosswalks, and scooter routes exist should the SUMO network be generated and research calibration begin.
