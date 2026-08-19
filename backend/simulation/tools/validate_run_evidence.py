"""Evidence-integrity validator for a recorded SimulationRunRecorder run.

This does not re-validate TTC/PET/conflict *formulas* -- that is the job of
``tests/test_risk_engine.py`` and ``tests/test_pet.py``, which check the
underlying math against known closed-form scenarios. This module instead
checks that a recorded run's persisted files are:

1. Internally consistent with each other and with the aggregate statistics
   (did the Recorder faithfully persist what the engine actually computed,
   without dropping, duplicating, or corrupting records), and
2. Plausible as physical trip data (no negative/zero durations, no impossibly
   short/fast trips, chronological ordering holds).

Usage:
    python -m simulation.tools.validate_run_evidence <run_dir> [--graph path]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Dict, List, Optional

# Generous upper bounds on trip_distance / travel_time (m/s). travel_time
# includes any time spent stopped while trip_status=="MOVING" (see
# StatisticsManager.update_motion), so average speed is normally well below
# desired_speed; these bounds exist to catch teleportation/unit bugs, not to
# assert an exact top speed.
PLAUSIBLE_MAX_SPEED_MPS = {"car": 12.0, "person": 3.0, "scooter": 8.0}


class Check:
    __slots__ = ("name", "passed", "detail")

    def __init__(self, name: str, passed: bool, detail: str = "") -> None:
        self.name = name
        self.passed = bool(passed)
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"[{'PASS' if self.passed else 'FAIL'}] {self.name}: {self.detail}"


def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _approx(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), abs_tol=tol)


def straight_line_distance(graph, origin_poi_id: str, destination_poi_id: str) -> Optional[float]:
    try:
        origin_node = graph.nodes[graph.poi(origin_poi_id)["node_id"]]
        destination_node = graph.nodes[graph.poi(destination_poi_id)["node_id"]]
    except KeyError:
        return None
    return math.dist((float(origin_node["x"]), float(origin_node["z"])), (float(destination_node["x"]), float(destination_node["z"])))


def validate_run(run_dir: Path, graph=None) -> List[Check]:
    run_dir = Path(run_dir)
    checks: List[Check] = []

    manifest_path = run_dir / "manifest.json"
    stats_path = run_dir / "simulation_statistics.json"
    if not manifest_path.exists() or not stats_path.exists():
        checks.append(Check("finalized_files_present", False, f"missing manifest.json or simulation_statistics.json in {run_dir}"))
        return checks

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    safety = stats.get("safety", {})
    mobility = stats.get("mobility", {})

    events = _read_jsonl(run_dir / "risk_events.jsonl")
    trips = _read_csv(run_dir / "completed_trips.csv")
    agents = _read_csv(run_dir / "agent_summary.csv")

    # -- consistency: risk_events.jsonl vs simulation_statistics.json --

    checks.append(Check(
        "conflict_count_matches_event_file_length",
        len(events) == int(safety.get("conflict_count") or 0),
        f"risk_events.jsonl has {len(events)} lines, statistics.safety.conflict_count={safety.get('conflict_count')}",
    ))
    near_miss_in_file = sum(1 for event in events if event.get("event_type") == "NEAR_MISS")
    checks.append(Check(
        "near_miss_count_matches_event_file",
        near_miss_in_file == int(safety.get("near_miss_count") or 0),
        f"file has {near_miss_in_file} NEAR_MISS events, statistics says {safety.get('near_miss_count')}",
    ))
    collision_in_file = sum(1 for event in events if event.get("event_type") == "COLLISION")
    checks.append(Check(
        "collision_count_matches_event_file",
        collision_in_file == int(safety.get("collision_count") or 0),
        f"file has {collision_in_file} COLLISION events, statistics says {safety.get('collision_count')}",
    ))

    ttc_values = [event["ttc"] for event in events if event.get("ttc") is not None]
    pet_values = [event["pet"] for event in events if event.get("pet") is not None]
    clearance_values = [event["clearance"] for event in events if event.get("clearance") is not None]
    checks.append(Check("min_ttc_matches_event_file_minimum", _approx(min(ttc_values) if ttc_values else None, safety.get("min_ttc"), tol=0.005),
                         f"min over file={min(ttc_values) if ttc_values else None}, statistics.min_ttc={safety.get('min_ttc')}"))
    checks.append(Check("min_pet_matches_event_file_minimum", _approx(min(pet_values) if pet_values else None, safety.get("min_pet"), tol=0.005),
                         f"min over file={min(pet_values) if pet_values else None}, statistics.min_pet={safety.get('min_pet')}"))
    checks.append(Check("min_clearance_matches_event_file_minimum", _approx(min(clearance_values) if clearance_values else None, safety.get("min_clearance"), tol=0.005),
                         f"min over file={min(clearance_values) if clearance_values else None}, statistics.min_clearance={safety.get('min_clearance')}"))

    # -- consistency: completed_trips.csv vs simulation_statistics.json --

    checks.append(Check(
        "completed_trip_rows_match_statistics",
        len(trips) == int(mobility.get("completed_trips") or 0),
        f"completed_trips.csv has {len(trips)} rows, statistics.mobility.completed_trips={mobility.get('completed_trips')}",
    ))

    # -- consistency: agent_summary.csv vs completed_trips.csv / risk_events.jsonl --

    agent_ids_in_summary = {row["agent_id"] for row in agents}
    agent_ids_in_trips = {row["agent_id"] for row in trips}
    missing = agent_ids_in_trips - agent_ids_in_summary
    checks.append(Check("every_completed_trip_agent_is_summarized", not missing, f"agent_ids missing from agent_summary.csv: {sorted(missing)[:10]}"))

    risk_event_count_sum = sum(int(row["risk_event_count"]) for row in agents)
    checks.append(Check(
        "agent_summary_risk_event_total_matches_two_per_event",
        risk_event_count_sum == 2 * len(events),
        f"sum(agent_summary.risk_event_count)={risk_event_count_sum}, expected 2*{len(events)}={2 * len(events)}",
    ))
    near_miss_sum = sum(int(row["near_miss_count"]) for row in agents)
    checks.append(Check(
        "agent_summary_near_miss_total_matches_two_per_event",
        near_miss_sum == 2 * near_miss_in_file,
        f"sum(agent_summary.near_miss_count)={near_miss_sum}, expected {2 * near_miss_in_file}",
    ))

    # Known, documented gap (see run_recorder.py / README "남은 한계"): agent_summary's
    # hard_braking_count only accrues on trip completion, so it is a lower bound
    # on the engine-wide total, never an equality. Flagged as informational,
    # not a failure.
    hard_brake_sum = sum(int(row["hard_braking_count"]) for row in agents)
    checks.append(Check(
        "agent_summary_hard_braking_is_a_lower_bound_not_equal (informational)",
        hard_brake_sum <= int(safety.get("hard_braking_count") or 0),
        f"sum(agent_summary.hard_braking_count)={hard_brake_sum} <= statistics.hard_braking_count={safety.get('hard_braking_count')} (in-flight trips undercounted by design)",
    ))

    # -- plausibility: completed_trips.csv --

    bad_duration = [row["agent_id"] for row in trips if not (float(row["travel_time"]) > 0)]
    checks.append(Check("all_completed_trips_have_positive_travel_time", not bad_duration, f"non-positive travel_time: {bad_duration[:10]}"))

    bad_waiting = [row["agent_id"] for row in trips if float(row["waiting_time"]) < 0]
    checks.append(Check("all_completed_trips_have_nonnegative_waiting_time", not bad_waiting, f"negative waiting_time: {bad_waiting[:10]}"))

    bad_distance = [row["agent_id"] for row in trips if not (float(row["trip_distance"]) > 0)]
    checks.append(Check("all_completed_trips_have_positive_trip_distance", not bad_distance, f"non-positive trip_distance: {bad_distance[:10]}"))

    bad_order = [
        row["agent_id"] for row in trips
        if not (float(row["spawned_at"]) <= float(row["trip_start_time"]) <= float(row["completed_at"]))
    ]
    checks.append(Check("completed_trips_are_chronologically_ordered", not bad_order, f"spawned_at<=trip_start_time<=completed_at violated: {bad_order[:10]}"))

    bad_speed = []
    for row in trips:
        speed = float(row["trip_distance"]) / max(float(row["travel_time"]), 1e-9)
        limit = PLAUSIBLE_MAX_SPEED_MPS.get(row["agent_type"], math.inf)
        if speed > limit:
            bad_speed.append((row["agent_id"], round(speed, 2), limit))
    checks.append(Check("completed_trips_implied_speed_is_plausible", not bad_speed, f"implied speed exceeds plausible bound: {bad_speed[:10]}"))

    if graph is not None:
        bad_shortcuts = []
        for row in trips:
            # An agent's first trip in a run legitimately starts mid-route
            # (see SimulationEngine._spawn_entities / partial_initial_segment)
            # and is expected to be shorter than the full O-D distance.
            if row.get("partial_initial_segment") in ("True", "true", "1"):
                continue
            straight = straight_line_distance(graph, row["origin"], row["destination"])
            if straight is not None and float(row["trip_distance"]) < straight - 1.0:
                bad_shortcuts.append((row["agent_id"], round(float(row["trip_distance"]), 1), round(straight, 1)))
        checks.append(Check(
            "completed_trips_distance_is_not_shorter_than_straight_line",
            not bad_shortcuts,
            f"route shorter than straight-line origin-destination distance (excludes partial_initial_segment rows): {bad_shortcuts[:10]}",
        ))

    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--graph", type=Path, default=None, help="optional campus_transport_network.geojson-derived mobility_graph.json for straight-line distance checks")
    args = parser.parse_args()

    graph = None
    if args.graph:
        from simulation.mobility_graph import MobilityGraph
        graph = MobilityGraph(args.graph)

    checks = validate_run(args.run_dir, graph=graph)
    for check in checks:
        print(check)
    failed = [check for check in checks if not check.passed and "(informational)" not in check.name]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
