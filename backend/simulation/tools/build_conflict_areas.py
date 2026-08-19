from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from simulation.network_schema import iter_features, load_feature_collection, load_policy, normalize_kind


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def buffered_rectangle(coordinates, width):
    first, last = coordinates[0], coordinates[-1]
    dx, dz = last[0] - first[0], last[1] - first[1]
    length = max(math.hypot(dx, dz), 1e-9)
    nx, nz = -dz / length * width / 2, dx / length * width / 2
    return [[first[0] + nx, first[1] + nz], [last[0] + nx, last[1] + nz], [last[0] - nx, last[1] - nz], [first[0] - nx, first[1] - nz], [first[0] + nx, first[1] + nz]]


def build(network: dict, policy: dict, crosswalk_width_m: float = 3.0) -> dict:
    """Build exploratory conflict areas from observed crosswalk centerlines.

    Width is an explicit model assumption, never a surveyed polygon claim.
    """
    if crosswalk_width_m <= 0:
        raise ValueError("crosswalk_width_m must be positive")
    edges = list(iter_features(network, "edge"))
    nodes = {feature.feature_id: feature for feature in iter_features(network, "node")}
    roads = [edge for edge in edges if normalize_kind(str(edge.properties.get("kind")), policy) in {"vehicle_lane", "allowed_road"}]
    areas = []
    groups = {}
    for crosswalk in (edge for edge in edges if normalize_kind(str(edge.properties.get("kind")), policy) == "crosswalk"):
        crosswalk_id = crosswalk.properties.get("crosswalk_id") or crosswalk.feature_id
        groups.setdefault(crosswalk_id, []).append(crosswalk)
    for crosswalk_id, crosswalks in groups.items():
        related_nodes = {str(value) for edge in crosswalks for value in (edge.properties.get("from_node"), edge.properties.get("to_node"))}
        crosswalk_node = next((nodes[node_id] for node_id in related_nodes if nodes.get(node_id) and nodes[node_id].properties.get("road_id") == crosswalk_id), None)
        # The longest observed centerline is buffered in its perpendicular
        # direction. This preserves its observed alignment while making the
        # 3 m crossing width an explicit, reproducible assumption.
        centerline = max(crosswalks, key=lambda edge: sum(math.dist(first[:2], second[:2]) for first, second in zip(edge.coordinates, edge.coordinates[1:])))
        polygon = buffered_rectangle(centerline.coordinates, crosswalk_width_m)
        intersecting = [road.feature_id for road in roads if related_nodes & {str(road.properties.get("from_node")), str(road.properties.get("to_node"))}]
        areas.append({
            "conflict_area_id": f"CA_{crosswalk_id}", "crosswalk_id": crosswalk_id,
            "crosswalk_edge_ids": [edge.feature_id for edge in crosswalks],
            "intersecting_vehicle_lanes": intersecting, "participants": ["car", "person", "scooter"],
            "source": "derived", "confidence": min(float(edge.properties.get("confidence") or 0) for edge in crosswalks),
            "derived": True, "centerline_authoritative": True, "polygon_authoritative": False,
            "width_m": crosswalk_width_m, "width_source": "assumed_fixed",
            "geometry_note": f"{crosswalk_width_m:g} m buffered area around observed crosswalk centerline; not a surveyed crosswalk polygon",
            "geometry": {"type": "Polygon", "coordinates": [polygon]},
        })
    return {"metadata": {"status": "exploratory derived conflict areas", "assumed_crosswalk_width_m": crosswalk_width_m, "polygon_authoritative": False}, "conflict_areas": areas}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build crosswalk/vehicle conflict areas.")
    parser.add_argument("--network", type=Path, default=DATA / "campus_transport_network.geojson")
    parser.add_argument("--policy", type=Path, default=ROOT / "config" / "mobility_policy.json")
    parser.add_argument("--output", type=Path, default=DATA / "conflict_areas.json")
    parser.add_argument("--width", type=float, default=3.0, help="Assumed crosswalk width in metres (default: 3).")
    args = parser.parse_args()
    payload = build(load_feature_collection(args.network), load_policy(args.policy), args.width)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {len(payload['conflict_areas'])} conflict areas -> {args.output}")


if __name__ == "__main__":
    main()
