from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPOSITORY = ROOT.parents[1]

REFERENCE_LONGITUDE = 127.4764043
REFERENCE_LATITUDE = 34.9700548
EARTH_RADIUS_METERS = 6_378_137.0
NODE_SNAP_METERS = 0.75
CROSSWALK_ACCESS_SNAP_METERS = 1.5
MAX_COMPONENT_ACCESS_METERS = 30.0
MAX_CROSSWALK_ACCESS_METERS = 15.0
GENERATED_PREFIXES = ("MEASURED_SIDEWALK_", "MEASURED_CROSSWALK_", "PEDESTRIAN_ACCESS_")


Point = tuple[float, float]


def project(point: Sequence[float]) -> Point:
    longitude, latitude = float(point[0]), float(point[1])
    latitude_radians = math.radians(REFERENCE_LATITUDE)
    x = math.radians(longitude - REFERENCE_LONGITUDE) * EARTH_RADIUS_METERS * math.cos(latitude_radians)
    z = math.radians(latitude - REFERENCE_LATITUDE) * EARTH_RADIUS_METERS
    return round(x, 3), round(z, 3)


def line_parts(geometry: dict) -> Iterable[list[Sequence[float]]]:
    geometry_type = geometry.get("type")
    if geometry_type == "LineString":
        yield geometry.get("coordinates") or []
    elif geometry_type == "MultiLineString":
        yield from geometry.get("coordinates") or []


def polygon_rings(geometry: dict) -> Iterable[list[Sequence[float]]]:
    geometry_type = geometry.get("type")
    if geometry_type == "Polygon":
        coordinates = geometry.get("coordinates") or []
        if coordinates:
            yield coordinates[0]
    elif geometry_type == "MultiPolygon":
        for polygon in geometry.get("coordinates") or []:
            if polygon:
                yield polygon[0]


def signed_area(ring: Sequence[Point]) -> float:
    return sum(
        ring[index][0] * ring[(index + 1) % len(ring)][1]
        - ring[(index + 1) % len(ring)][0] * ring[index][1]
        for index in range(len(ring))
    ) / 2.0


def centroid(ring: Sequence[Point]) -> Point:
    area = signed_area(ring)
    if abs(area) < 1e-9:
        return sum(point[0] for point in ring) / len(ring), sum(point[1] for point in ring) / len(ring)
    factor = 1.0 / (6.0 * area)
    x = z = 0.0
    for index, first in enumerate(ring):
        second = ring[(index + 1) % len(ring)]
        cross = first[0] * second[1] - second[0] * first[1]
        x += (first[0] + second[0]) * cross
        z += (first[1] + second[1]) * cross
    return x * factor, z * factor


def point_in_ring(point: Point, ring: Sequence[Point]) -> bool:
    x, z = point
    inside = False
    previous = ring[-1]
    for current in ring:
        if (current[1] > z) != (previous[1] > z):
            crossing_x = (previous[0] - current[0]) * (z - current[1]) / (previous[1] - current[1]) + current[0]
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def principal_direction(ring: Sequence[Point], center: Point) -> Point:
    xx = zz = xz = 0.0
    for x, z in ring:
        dx, dz = x - center[0], z - center[1]
        xx += dx * dx
        zz += dz * dz
        xz += dx * dz
    angle = 0.5 * math.atan2(2.0 * xz, xx - zz)
    return math.cos(angle), math.sin(angle)


def line_edge_intersection(center: Point, direction: Point, first: Point, second: Point) -> float | None:
    edge = second[0] - first[0], second[1] - first[1]
    denominator = direction[0] * edge[1] - direction[1] * edge[0]
    if abs(denominator) < 1e-9:
        return None
    offset = first[0] - center[0], first[1] - center[1]
    t = (offset[0] * edge[1] - offset[1] * edge[0]) / denominator
    u = (offset[0] * direction[1] - offset[1] * direction[0]) / denominator
    return t if -1e-8 <= u <= 1.0 + 1e-8 else None


def representative_centerline(ring: Sequence[Point]) -> tuple[Point, Point]:
    values = list(ring[:-1] if ring[0] == ring[-1] else ring)
    center = centroid(values)
    direction = principal_direction(values, center)
    intersections: list[float] = []
    for index, first in enumerate(values):
        value = line_edge_intersection(center, direction, first, values[(index + 1) % len(values)])
        if value is not None and not any(abs(value - known) < 1e-6 for known in intersections):
            intersections.append(value)
    intersections.sort()
    intervals = []
    for start, end in zip(intersections, intersections[1:]):
        midpoint = (start + end) / 2.0
        sample = center[0] + midpoint * direction[0], center[1] + midpoint * direction[1]
        if point_in_ring(sample, values):
            intervals.append((end - start, start, end))
    if not intervals:
        raise ValueError("crosswalk polygon does not contain a usable centerline")
    _, start, end = max(intervals)
    return (
        (round(center[0] + start * direction[0], 3), round(center[1] + start * direction[1], 3)),
        (round(center[0] + end * direction[0], 3), round(center[1] + end * direction[1], 3)),
    )


def feature_id(feature: dict) -> str:
    properties = feature.get("properties") or {}
    return str(properties.get("id") or feature.get("id") or "")


def closest_point(point: Point, first: Point, second: Point) -> Point:
    dx, dz = second[0] - first[0], second[1] - first[1]
    denominator = dx * dx + dz * dz
    if denominator <= 1e-12:
        return first
    ratio = max(0.0, min(1.0, ((point[0] - first[0]) * dx + (point[1] - first[1]) * dz) / denominator))
    return round(first[0] + ratio * dx, 3), round(first[1] + ratio * dz, 3)


def nearest_edge_projection(point: Point, edges: Sequence[dict]) -> tuple[float, Point, dict] | None:
    choices = []
    for edge in edges:
        coordinates = [tuple(value[:2]) for value in (edge.get("geometry") or {}).get("coordinates") or []]
        for first, second in zip(coordinates, coordinates[1:]):
            projected = closest_point(point, first, second)
            choices.append((math.dist(point, projected), projected, edge))
    return min(choices, key=lambda value: value[0]) if choices else None


def orientation(first: Point, second: Point, third: Point) -> int:
    value = (second[1] - first[1]) * (third[0] - second[0]) - (second[0] - first[0]) * (third[1] - second[1])
    return 0 if abs(value) < 1e-8 else 1 if value > 0 else 2


def segments_intersect(first: Point, second: Point, third: Point, fourth: Point) -> bool:
    return orientation(first, second, third) != orientation(first, second, fourth) and orientation(third, fourth, first) != orientation(third, fourth, second)


def line_intersects_edges(line: Sequence[Point], edges: Sequence[dict]) -> bool:
    for edge in edges:
        coordinates = [tuple(value[:2]) for value in (edge.get("geometry") or {}).get("coordinates") or []]
        if any(segments_intersect(a, b, c, d) for a, b in zip(line, line[1:]) for c, d in zip(coordinates, coordinates[1:])):
            return True
    return False


def node_feature(node_id: str, point: Point, kind: str, **extra: object) -> dict:
    return {
        "type": "Feature",
        "id": node_id,
        "properties": {
            "id": node_id,
            "feature_type": "node",
            "kind": kind,
            "source": extra.pop("source", "GIS-derived"),
            "confidence": extra.pop("confidence", 0.75),
            "derived": bool(extra.pop("derived", False)),
            "authoritative": False,
            **extra,
        },
        "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
    }


def edge_feature(
    edge_id: str,
    source_node: str,
    target_node: str,
    coordinates: Sequence[Point],
    kind: str,
    source: str,
    confidence: float,
    derived: bool,
    **extra: object,
) -> dict:
    return {
        "type": "Feature",
        "id": edge_id,
        "properties": {
            "id": edge_id,
            "feature_type": "edge",
            "kind": kind,
            "allowed_types": ["person"] if kind == "sidewalk" else ["person", "scooter"],
            "from_node": source_node,
            "to_node": target_node,
            "bidirectional": True,
            "speed_limit": 5 if kind == "sidewalk" else 10,
            "source": source,
            "confidence": confidence,
            "derived": derived,
            "authoritative": False,
            **extra,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(point[0], 3), round(point[1], 3)] for point in coordinates],
        },
    }


class NodeRegistry:
    def __init__(self) -> None:
        self.points: dict[str, Point] = {}
        self.created: list[dict] = []
        self.counter = 0

    def register_existing(self, node_id: str, point: Point) -> None:
        self.points[node_id] = point

    def nearest(self, point: Point, candidates: Iterable[str] | None = None) -> tuple[str, float] | None:
        identifiers = list(candidates) if candidates is not None else list(self.points)
        if not identifiers:
            return None
        node_id = min(identifiers, key=lambda value: math.dist(point, self.points[value]))
        return node_id, math.dist(point, self.points[node_id])

    def sidewalk_node(self, point: Point) -> str:
        measured = [node_id for node_id in self.points if node_id.startswith("MEASURED_SIDEWALK_NODE_")]
        found = self.nearest(point, measured)
        if found and found[1] <= NODE_SNAP_METERS:
            return found[0]
        self.counter += 1
        node_id = f"MEASURED_SIDEWALK_NODE_{self.counter:04d}"
        self.points[node_id] = point
        self.created.append(node_feature(node_id, point, "sidewalk_vertex"))
        return node_id

    def crosswalk_node(self, crosswalk_id: str, side: str, point: Point, sidewalk_nodes: Sequence[str]) -> str:
        found = self.nearest(point, sidewalk_nodes)
        if found and found[1] <= CROSSWALK_ACCESS_SNAP_METERS:
            return found[0]
        node_id = f"MEASURED_CROSSWALK_NODE_{crosswalk_id}_{side}"
        self.points[node_id] = point
        self.created.append(
            node_feature(node_id, point, "crosswalk_endpoint", source="manually-digitized", confidence=0.75, derived=True, crosswalk_id=crosswalk_id)
        )
        return node_id


def connected_components(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> list[set[str]]:
    adjacency = {node_id: set() for node_id in nodes}
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    unseen = set(nodes)
    components = []
    while unseen:
        start = unseen.pop()
        component = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def integrate(base: dict, walkways: dict, crosswalks: dict) -> tuple[dict, dict]:
    retained = [feature for feature in base["features"] if not feature_id(feature).startswith(GENERATED_PREFIXES)]
    registry = NodeRegistry()
    legacy_pedestrian_nodes: set[str] = set()
    legacy_pedestrian_edges: list[dict] = []
    legacy_vehicle_edges: list[dict] = []
    for feature in retained:
        properties = feature.get("properties") or {}
        if properties.get("feature_type") == "node":
            registry.register_existing(feature_id(feature), tuple(feature["geometry"]["coordinates"][:2]))
        elif properties.get("feature_type") == "edge" and set(properties.get("allowed_types") or ()) & {"person"}:
            legacy_pedestrian_nodes.update((str(properties.get("from_node")), str(properties.get("to_node"))))
            legacy_pedestrian_edges.append(feature)
            if properties.get("kind") in {"shared_path", "crosswalk"} and properties.get("source") == "derived_from_vehicle_network":
                properties["fallback_only"] = True
        if properties.get("feature_type") == "edge" and properties.get("kind") in {"vehicle_lane", "allowed_road", "vehicle_gate", "parking_connection"}:
            legacy_vehicle_edges.append(feature)

    generated_edges: list[dict] = []
    sidewalk_pairs: set[tuple[str, str]] = set()
    sidewalk_graph_edges: list[tuple[str, str]] = []
    source_feature_count = 0
    skipped_short_segments = 0
    for feature_index, feature in enumerate(walkways.get("features") or [], start=1):
        properties = feature.get("properties") or {}
        source_id = str(properties.get("ufid") or properties.get("gid") or f"WALKWAY_{feature_index:03d}")
        for part_index, raw_line in enumerate(line_parts(feature.get("geometry") or {}), start=1):
            points = [project(point) for point in raw_line]
            if len(points) < 2:
                continue
            source_feature_count += 1
            node_ids = [registry.sidewalk_node(point) for point in points]
            for segment_index, (source_node, target_node) in enumerate(zip(node_ids, node_ids[1:]), start=1):
                if source_node == target_node or math.dist(registry.points[source_node], registry.points[target_node]) <= 0.1:
                    skipped_short_segments += 1
                    continue
                pair = tuple(sorted((source_node, target_node)))
                if pair in sidewalk_pairs:
                    continue
                sidewalk_pairs.add(pair)
                sidewalk_graph_edges.append((source_node, target_node))
                edge_id = f"MEASURED_SIDEWALK_{len(sidewalk_pairs):04d}"
                generated_edges.append(
                    edge_feature(
                        edge_id,
                        source_node,
                        target_node,
                        [registry.points[source_node], registry.points[target_node]],
                        "sidewalk",
                        "GIS-derived",
                        0.8,
                        False,
                        source_id=source_id,
                        source_part=part_index,
                        source_segment=segment_index,
                        width_m=properties.get("widt"),
                        name=properties.get("명칭"),
                        quality_code=properties.get("qual"),
                    )
                )

    all_sidewalk_nodes = sorted(node_id for node_id in registry.points if node_id.startswith("MEASURED_SIDEWALK_NODE_"))
    components = connected_components(all_sidewalk_nodes, sidewalk_graph_edges)
    component_connector_distances: list[float] = []
    accepted_components: list[set[str]] = []
    excluded_components = 0
    for component_index, component in enumerate(components, start=1):
        best = min(
            (
                (*nearest_edge_projection(registry.points[measured], legacy_pedestrian_edges), measured)
                for measured in component
                if nearest_edge_projection(registry.points[measured], legacy_pedestrian_edges)
            ),
            default=None,
        )
        if not best or best[0] > MAX_COMPONENT_ACCESS_METERS:
            excluded_components += 1
            continue
        distance, projected, legacy_edge, measured = best
        accepted_components.append(component)
        component_connector_distances.append(distance)
        legacy_properties = legacy_edge.get("properties") or {}
        legacy_endpoints = (str(legacy_properties.get("from_node")), str(legacy_properties.get("to_node")))
        reused = next((node_id for node_id in legacy_endpoints if node_id in registry.points and math.dist(projected, registry.points[node_id]) <= 0.1), None)
        anchor_id = reused or f"PEDESTRIAN_ACCESS_LEGACY_NODE_{component_index:03d}"
        if not reused:
            registry.points[anchor_id] = projected
            registry.created.append(
                node_feature(anchor_id, projected, "pedestrian_access_anchor", source="derived", confidence=0.4, derived=True)
            )
        edge_id = f"PEDESTRIAN_ACCESS_COMPONENT_{component_index:03d}"
        generated_edges.append(
            edge_feature(
                edge_id,
                measured,
                anchor_id,
                [registry.points[measured], projected],
                "sidewalk",
                "derived",
                0.4,
                True,
                connector_role="measured_sidewalk_to_legacy_network",
                connector_distance_m=round(distance, 3),
                fallback_only=True,
            )
        )
        for side, legacy_node in zip(("A", "B"), legacy_endpoints):
            if legacy_node not in registry.points or math.dist(projected, registry.points[legacy_node]) <= 0.1:
                continue
            generated_edges.append(
                edge_feature(
                    f"PEDESTRIAN_ACCESS_LEGACY_{component_index:03d}_{side}",
                    anchor_id,
                    legacy_node,
                    [projected, registry.points[legacy_node]],
                    "shared_path",
                    "derived",
                    0.35,
                    True,
                    connector_role="legacy_edge_anchor",
                    fallback_only=True,
                    source_edge_id=feature_id(legacy_edge),
                )
            )

    accepted_sidewalk_nodes = set().union(*accepted_components) if accepted_components else set()
    registry.created = [
        feature
        for feature in registry.created
        if not feature_id(feature).startswith("MEASURED_SIDEWALK_NODE_") or feature_id(feature) in accepted_sidewalk_nodes
    ]
    generated_edges = [
        feature
        for feature in generated_edges
        if not feature_id(feature).startswith("MEASURED_SIDEWALK_")
        or {
            str((feature.get("properties") or {}).get("from_node")),
            str((feature.get("properties") or {}).get("to_node")),
        } <= accepted_sidewalk_nodes
    ]
    sidewalk_nodes = sorted(accepted_sidewalk_nodes)
    measured_sidewalk_edges = [feature for feature in generated_edges if feature_id(feature).startswith("MEASURED_SIDEWALK_")]

    crosswalk_access_distances: list[float] = []
    crosswalk_count = 0
    crosswalk_excluded_access = 0
    crosswalk_excluded_road = 0
    for feature_index, feature in enumerate(crosswalks.get("features") or [], start=1):
        properties = feature.get("properties") or {}
        crosswalk_id = str(properties.get("id") or feature.get("id") or f"CW_MEASURED_{feature_index:03d}")
        candidates = []
        for raw_ring in polygon_rings(feature.get("geometry") or {}):
            ring = [project(point) for point in raw_ring]
            try:
                start, end = representative_centerline(ring)
            except ValueError:
                continue
            candidates.append((math.dist(start, end), start, end))
        if not candidates:
            continue
        _, start, end = max(candidates)
        access = [nearest_edge_projection(point, measured_sidewalk_edges) for point in (start, end)]
        if any(value is None or value[0] > MAX_CROSSWALK_ACCESS_METERS for value in access):
            crosswalk_excluded_access += 1
            continue
        if not line_intersects_edges([start, end], legacy_vehicle_edges):
            crosswalk_excluded_road += 1
            continue
        source_node = registry.crosswalk_node(crosswalk_id, "A", start, sidewalk_nodes)
        target_node = registry.crosswalk_node(crosswalk_id, "B", end, sidewalk_nodes)
        crosswalk_count += 1
        generated_edges.append(
            edge_feature(
                f"MEASURED_CROSSWALK_{crosswalk_id}",
                source_node,
                target_node,
                [start, end],
                "crosswalk",
                "manually-digitized",
                0.75,
                True,
                crosswalk_id=crosswalk_id,
                source_geometry="Polygon",
                centerline_method="principal-axis-clipped",
            )
        )
        for side, node_id, projection in (("A", source_node, access[0]), ("B", target_node, access[1])):
            if node_id.startswith("MEASURED_SIDEWALK_NODE_"):
                crosswalk_access_distances.append(0.0)
                continue
            distance, projected, sidewalk_edge = projection
            sidewalk_properties = sidewalk_edge.get("properties") or {}
            sidewalk_endpoints = (
                str(sidewalk_properties.get("from_node")),
                str(sidewalk_properties.get("to_node")),
            )
            reused = next((value for value in sidewalk_endpoints if value in registry.points and math.dist(projected, registry.points[value]) <= 0.1), None)
            anchor_id = reused or f"PEDESTRIAN_ACCESS_SIDEWALK_NODE_{crosswalk_id}_{side}"
            if not reused:
                registry.points[anchor_id] = projected
                registry.created.append(
                    node_feature(anchor_id, projected, "crosswalk_access_anchor", source="derived", confidence=0.5, derived=True, crosswalk_id=crosswalk_id)
                )
            crosswalk_access_distances.append(distance)
            generated_edges.append(
                edge_feature(
                    f"PEDESTRIAN_ACCESS_{crosswalk_id}_{side}",
                    node_id,
                    anchor_id,
                    [registry.points[node_id], projected],
                    "sidewalk",
                    "derived",
                    0.5,
                    True,
                    connector_role="crosswalk_to_sidewalk",
                    connector_distance_m=round(distance, 3),
                    crosswalk_id=crosswalk_id,
                )
            )
            for endpoint_side, sidewalk_node in zip(("A", "B"), sidewalk_endpoints):
                if sidewalk_node not in registry.points or math.dist(projected, registry.points[sidewalk_node]) <= 0.1:
                    continue
                generated_edges.append(
                    edge_feature(
                        f"PEDESTRIAN_ACCESS_SIDEWALK_{crosswalk_id}_{side}_{endpoint_side}",
                        anchor_id,
                        sidewalk_node,
                        [projected, registry.points[sidewalk_node]],
                        "sidewalk",
                        "derived",
                        0.5,
                        True,
                        connector_role="sidewalk_edge_anchor",
                        crosswalk_id=crosswalk_id,
                        source_edge_id=feature_id(sidewalk_edge),
                    )
                )

        scooter_access = nearest_edge_projection(start, legacy_pedestrian_edges)
        if scooter_access:
            distance, projected, legacy_edge = scooter_access
            legacy_properties = legacy_edge.get("properties") or {}
            legacy_endpoints = (str(legacy_properties.get("from_node")), str(legacy_properties.get("to_node")))
            reused = next((value for value in legacy_endpoints if value in registry.points and math.dist(projected, registry.points[value]) <= 0.1), None)
            scooter_anchor = reused or f"PEDESTRIAN_ACCESS_SCOOTER_NODE_{crosswalk_id}"
            if not reused:
                registry.points[scooter_anchor] = projected
                registry.created.append(
                    node_feature(scooter_anchor, projected, "scooter_dismount_anchor", source="derived", confidence=0.35, derived=True, crosswalk_id=crosswalk_id)
                )
            generated_edges.append(
                edge_feature(
                    f"PEDESTRIAN_ACCESS_SCOOTER_{crosswalk_id}",
                    source_node,
                    scooter_anchor,
                    [registry.points[source_node], projected],
                    "shared_path",
                    "derived",
                    0.35,
                    True,
                    connector_role="scooter_crosswalk_fallback",
                    connector_distance_m=round(distance, 3),
                    crosswalk_id=crosswalk_id,
                    fallback_only=True,
                )
            )
            for endpoint_side, legacy_node in zip(("A", "B"), legacy_endpoints):
                if legacy_node not in registry.points or math.dist(projected, registry.points[legacy_node]) <= 0.1:
                    continue
                generated_edges.append(
                    edge_feature(
                        f"PEDESTRIAN_ACCESS_SCOOTER_LEGACY_{crosswalk_id}_{endpoint_side}",
                        scooter_anchor,
                        legacy_node,
                        [projected, registry.points[legacy_node]],
                        "shared_path",
                        "derived",
                        0.3,
                        True,
                        connector_role="scooter_crosswalk_legacy_anchor",
                        crosswalk_id=crosswalk_id,
                        fallback_only=True,
                    )
                )

    metadata = dict(base.get("metadata") or {})
    metadata.update(
        {
            "pedestrian_geometry_integration": {
                "walkway_source": "docs/assets/data/walkways_wgs84.geojson",
                "crosswalk_source": "docs/assets/data/crosswalks_wgs84.geojson",
                "coordinate_reference": {"longitude": REFERENCE_LONGITUDE, "latitude": REFERENCE_LATITUDE},
                "sidewalk_geometry": "direct WGS84 line projection; duplicate segments removed",
                "crosswalk_geometry": "principal-axis centerline derived from manually digitized polygons",
                "legacy_pedestrian_edges": "retained as fallback_only for OD continuity",
                "limitations": "Access connectors and crosswalk centerlines are derived; validate against survey/CAD before absolute real-world claims.",
            }
        }
    )
    report = {
        "walkway_source_features": len(walkways.get("features") or []),
        "walkway_line_parts": source_feature_count,
        "sidewalk_nodes": len(sidewalk_nodes),
        "sidewalk_edges": len(measured_sidewalk_edges),
        "sidewalk_components_total": len(components),
        "sidewalk_components_integrated": len(accepted_components),
        "sidewalk_components_excluded": excluded_components,
        "skipped_short_segments": skipped_short_segments,
        "component_connectors": len(component_connector_distances),
        "component_connector_max_m": round(max(component_connector_distances, default=0.0), 3),
        "crosswalk_source_features": len(crosswalks.get("features") or []),
        "crosswalk_edges": crosswalk_count,
        "crosswalks_excluded_by_access_distance": crosswalk_excluded_access,
        "crosswalks_excluded_by_vehicle_alignment": crosswalk_excluded_road,
        "crosswalk_access_connectors": len([edge for edge in generated_edges if (edge.get("properties") or {}).get("connector_role") == "crosswalk_to_sidewalk"]),
        "crosswalk_access_max_m": round(max(crosswalk_access_distances, default=0.0), 3),
        "generated_nodes": len(registry.created),
        "generated_edges": len(generated_edges),
    }
    return {"type": "FeatureCollection", "metadata": metadata, "features": retained + registry.created + generated_edges}, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Integrate measured walkway lines and digitized crosswalk polygons into the simulation network.")
    parser.add_argument("--base-network", type=Path, default=DATA / "campus_transport_network.geojson")
    parser.add_argument("--walkways", type=Path, default=REPOSITORY / "docs" / "assets" / "data" / "walkways_wgs84.geojson")
    parser.add_argument("--crosswalks", type=Path, default=REPOSITORY / "docs" / "assets" / "data" / "crosswalks_wgs84.geojson")
    parser.add_argument("--output", type=Path, default=DATA / "campus_transport_network.geojson")
    parser.add_argument("--report", type=Path, default=DATA / "pedestrian_geometry_integration.json")
    args = parser.parse_args()
    base = json.loads(args.base_network.read_text(encoding="utf-8"))
    walkways = json.loads(args.walkways.read_text(encoding="utf-8"))
    crosswalks = json.loads(args.crosswalks.read_text(encoding="utf-8"))
    network, report = integrate(base, walkways, crosswalks)
    args.output.write_text(json.dumps(network, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
