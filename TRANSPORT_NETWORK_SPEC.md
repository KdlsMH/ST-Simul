# Campus Transport Network Specification

## Source of Truth

`backend/simulation/data/campus_transport_network.geojson` is the canonical edit/exchange contract. The current file imports the legacy derived graph for traceability; it does not certify it as real geometry.

It is also the default Runtime source. `SimulationEngine` validates and converts it in memory at startup. Set `SIMULATION_NETWORK_MODE=transport-authoritative` to require approved geometry; the current dataset has no authoritative Edge coverage and therefore cannot start in that mode. `legacy` remains available only for diagnosis.

Feature roles:

- `feature_type=node`: network endpoint/intersection/POI anchor as a Point.
- `feature_type=edge`: routeable LineString.
- `feature_type=poi`: OD destination Point tied to `node_id`.

Required Edge properties:

```json
{
  "id": "SIDEWALK_D4_031",
  "feature_type": "edge",
  "kind": "sidewalk",
  "allowed_types": ["person"],
  "from_node": "NODE_031",
  "to_node": "NODE_032",
  "bidirectional": true,
  "speed_limit": null,
  "source_id": "CAD_SIDEWALK_031",
  "source": "CAD-derived",
  "confidence": 0.9,
  "derived": false,
  "authoritative": true
}
```

An Edge becomes authoritative only after coordinate alignment, semantic kind, topology, and field/drawing provenance are reviewed. Browser-downloaded drafts intentionally use `authoritative=false`.

## Mobility policy

`backend/simulation/config/mobility_policy.json` is the policy contract. It separates `vehicle_lane`, `sidewalk`, `crosswalk`, `bike_lane`, `scooter_lane`, `shared_path`, `allowed_road`, gates, entrances, and parking connectors. Scooter permissions are policy values rather than observed campus regulations.

The project does not construct a sidewalk by merely copying a vehicle line and changing `allowed_types`. Legacy copies remain `source=derived_from_vehicle_network`, `confidence=0.2`, and `derived=true` until replaced.

Development mode applies configurable derived lateral offsets without modifying the Source GeoJSON: Person shared paths 2.8 m, Scooter shared paths 1.4 m, and Scooter allowed roads -1.0 m. Crosswalks, gates, entrances and parking connectors converge to zero offset. These are visualization/movement aids, not surveyed geometry.

Coverage demand mixes all routeable POIs with the configured time-profile OD pairs, and route costs include bounded random variation plus prior Edge-use penalties. This spreads Agents across more campus corridors while retaining explicit OD endpoints.

## Authoring workflow

In development, open the Safety tab and enable **Route Editing Mode**. Supported operations:

- Create Path, Edit Path, select/move/delete Point, Finish, Cancel.
- Vehicle Lane, Sidewalk, Scooter Lane, Shared Path, Crosswalk, Building Entrance, Parking Connection, Scooter Parking Connection.
- Crosswalk centerline + width or Polygon.
- Direction, confidence, and source metadata.
- Load an existing GeoJSON and download a draft GeoJSON.

The draft must then be merged into the Source of Truth with stable node IDs and validated:

```bash
cd backend
python -m simulation.tools.validate_network
python -m simulation.tools.build_graph --output simulation/data/mobility_graph_from_transport.json
```

Use `--authoritative-only` to verify that approved routing does not silently use derived data.

## Debug colors

- Vehicle lane/allowed road: blue solid.
- Sidewalk: green dashed.
- Scooter/bike lane: orange solid.
- Shared path: purple solid.
- Crosswalk: white.
- Invalid/disconnected node: red point.

Production builds hide editing tools unless `VITE_SIMULATION_DEBUG=true`.

## Validation semantics

`python -m simulation.tools.validate_network` writes JSON and Markdown reports and checks geometry, finite coordinates, zero length, endpoint references, duplicate positions, policy violations, Agent connectivity, crosswalk connections, parking connections, and building entrances. A structural PASS does not mean surveyed accuracy; provenance coverage must be examined separately.
