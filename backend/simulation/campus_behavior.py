"""Context-aware speed/yield model for the mixed campus traffic simulation.

This module adds *interpretation* on top of quantities the engine already
computes (TTC, clearance, path/edge metadata, interaction_state) -- it does
not recompute collision geometry, TTC, or PET. Those remain the sole
responsibility of risk_engine.py; this module only turns already-known
values into a desired-speed multiplier and a human-readable behavior label.

Concepts (see the project's speed-model brief):
    max_speed        -- physical/scenario speed limit (existing risk_config
                         speed_limits / scenario speed_multiplier).
    free_flow_speed   -- what an agent would drive at with no interference
                         (existing trip_manager.desired_speed()).
    desired_speed     -- free_flow_speed reduced by road context, following,
                         pedestrian proximity/density, and crosswalk policy
                         (computed here, folded into SimulationEngine._base_target
                         and InteractionManager.speed_constraints).
    current_speed     -- approaches desired_speed under the existing
                         acceleration/deceleration limits in
                         SimulationEngine.step(); this module never sets
                         current_speed directly.

All numeric thresholds live in config/campus_behavior_config.json (ASSUMED_DEFAULT,
not measured campus data) rather than as inline magic numbers, and the whole
file is folded into the Run Recorder's config_hash so a behavior-parameter
change is traceable in recorded results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from .data_loader import load_json
except ImportError:
    from data_loader import load_json


ROAD_CONTEXTS = (
    "CAMPUS_ROAD", "SHARED_ZONE", "CROSSWALK_APPROACH", "CROSSWALK",
    "PARKING_CONNECTION", "PEDESTRIAN_PRIORITY_ZONE",
)
BEHAVIOR_STATES = ("NORMAL", "CAUTION", "YIELD", "STOP")


class CampusBehaviorConfig:
    def __init__(self, path: str | Path) -> None:
        self.raw: Dict = load_json(path)
        self.road_context_speed_factor: Dict[str, float] = dict(self.raw.get("road_context_speed_factor", {}))
        self.crosswalk_approach_lookahead_m: Dict[str, float] = dict(self.raw.get("crosswalk_approach_lookahead_m", {}))
        self.crosswalk_policy_speed_kmh: Dict[str, Optional[float]] = dict(self.raw.get("crosswalk_policy_speed_kmh", {}))
        self.default_crosswalk_policy: str = self.raw.get("default_crosswalk_policy", "slow_riding")
        self.dismount_walk_speed_mps: float = float(self.raw.get("dismount_walk_speed_mps", 1.4))
        self.pedestrian_density_radius_m: float = float(self.raw.get("pedestrian_density_radius_m", 10.0))
        self.pedestrian_density_curve: List[Tuple[float, float]] = [
            (float(count), float(factor)) for count, factor in self.raw.get("pedestrian_density_curve", [[0, 1.0]])
        ]
        self.pedestrian_influence_zone_m: Dict[str, Dict[str, float]] = dict(self.raw.get("pedestrian_influence_zone_m", {}))
        self.pedestrian_influence_clearance_m: Dict[str, Dict[str, float]] = dict(self.raw.get("pedestrian_influence_clearance_m", {}))
        self.pedestrian_influence_ttc_sec: Dict[str, Dict[str, float]] = dict(self.raw.get("pedestrian_influence_ttc_sec", {}))
        self.following_min_gap_m: Dict[str, float] = dict(self.raw.get("following_min_gap_m", {}))
        self.following_lookahead_m: Dict[str, float] = dict(self.raw.get("following_lookahead_m", {}))


def pedestrian_density_factor(nearby_count: int, curve: Sequence[Tuple[float, float]]) -> float:
    """Piecewise-linear interpolation over configured [count, factor] points."""
    if not curve:
        return 1.0
    points = sorted(curve, key=lambda item: item[0])
    if nearby_count <= points[0][0]:
        return points[0][1]
    for (count_a, factor_a), (count_b, factor_b) in zip(points, points[1:]):
        if count_a <= nearby_count <= count_b:
            if count_b == count_a:
                return factor_b
            ratio = (nearby_count - count_a) / (count_b - count_a)
            return factor_a + (factor_b - factor_a) * ratio
    return points[-1][1]


def road_context_for(path, route_distance: float, segment: int, agent_type: str, config: CampusBehaviorConfig) -> str:
    """Classify the agent's current position using only edge metadata and
    route geometry that already exist in the runtime graph -- no invented
    road-width/lane classification (see config note: this derived network
    has no such source data)."""
    kinds = path.edge_kinds
    if segment >= len(kinds):
        return "CAMPUS_ROAD"
    kind = kinds[segment]
    if kind == "crosswalk":
        return "CROSSWALK"
    if kind == "parking_connection":
        return "PARKING_CONNECTION"
    if kind in {"building_entrance", "pedestrian_gate"}:
        return "PEDESTRIAN_PRIORITY_ZONE"
    lookahead = config.crosswalk_approach_lookahead_m.get(agent_type)
    if lookahead and kind in {"allowed_road", "shared_path"}:
        limit = route_distance + float(lookahead)
        for index in range(segment, len(kinds)):
            if path.cumulative_lengths[index] > limit:
                break
            if kinds[index] == "crosswalk":
                return "CROSSWALK_APPROACH"
    if kind == "shared_path":
        return "SHARED_ZONE"
    return "CAMPUS_ROAD"


def road_context_speed_factor(context: str, config: CampusBehaviorConfig) -> float:
    return float(config.road_context_speed_factor.get(context, 1.0))


def crosswalk_target_speed_mps(agent_type: str, crosswalk_policy: str, free_flow_mps: float, config: CampusBehaviorConfig) -> Tuple[float, str]:
    """Only meaningful for scooters; cars/pedestrians keep their existing
    crosswalk handling in SimulationEngine._base_target. Returns
    (target_speed_mps, effective_policy_name)."""
    policy = crosswalk_policy or config.default_crosswalk_policy
    if policy == "dismount":
        return config.dismount_walk_speed_mps, "dismount"
    if policy == "ride_through":
        return free_flow_mps, "ride_through"
    kmh = config.crosswalk_policy_speed_kmh.get("slow_riding")
    slow_mps = (float(kmh) / 3.6) if kmh is not None else free_flow_mps
    return min(free_flow_mps, slow_mps), "slow_riding"


def behavior_state_from(interaction_state: str, speed_factor: float) -> str:
    """Derive a NORMAL/CAUTION/YIELD/STOP label from values the engine
    already computed (InteractionManager.interaction_state, and the
    resulting desired-speed factor) -- no new physics."""
    if speed_factor <= 0.05:
        return "STOP"
    if interaction_state in {"BRAKING", "CONFLICT"} or speed_factor < 0.5:
        return "YIELD"
    if interaction_state in {"AVOIDING", "APPROACHING", "CROSSING"} or speed_factor < 0.9:
        return "CAUTION"
    return "NORMAL"
