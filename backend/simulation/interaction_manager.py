from __future__ import annotations

import math
from typing import Dict, Iterable, Optional

try:
    from .campus_behavior import CampusBehaviorConfig, pedestrian_density_factor
    from .risk_engine import RiskEngine
    from .spatial_index import UniformSpatialGrid
except ImportError:
    from campus_behavior import CampusBehaviorConfig, pedestrian_density_factor
    from risk_engine import RiskEngine
    from spatial_index import UniformSpatialGrid


STATE_PRIORITY = {"NONE": 0, "APPROACHING": 1, "FOLLOWING": 2, "CROSSING": 3, "AVOIDING": 4, "BRAKING": 5, "CONFLICT": 6}


class InteractionManager:
    """Translate microscopic pair interactions into per-agent speed constraints.

    Collision/TTC/PET geometry is computed once by RiskEngine.calculate_pair;
    this class only turns those already-computed metrics into a desired-speed
    factor per pair type, using thresholds centralized in
    CampusBehaviorConfig (config/campus_behavior_config.json) instead of
    inline magic numbers.
    """

    def __init__(self, risk_engine: RiskEngine, campus_behavior: Optional[CampusBehaviorConfig] = None) -> None:
        self.risk_engine = risk_engine
        self.campus_behavior = campus_behavior
        self.spatial_index = UniformSpatialGrid(cell_size=max(5.0, risk_engine.interaction_search_radius))

    @staticmethod
    def _set_state(entity: Dict, state: str) -> None:
        if STATE_PRIORITY[state] > STATE_PRIORITY.get(str(entity.get("interaction_state", "NONE")), 0):
            entity["interaction_state"] = state

    @staticmethod
    def _distance(first: Dict, second: Dict) -> float:
        return math.hypot(float(second["x"]) - float(first["x"]), float(second["z"]) - float(first["z"]))

    def _pedestrian_gap(self, agent_type: str, key: str, default: float) -> float:
        if not self.campus_behavior:
            return default
        return float(self.campus_behavior.pedestrian_influence_clearance_m.get(agent_type, {}).get(key, default))

    def _pedestrian_ttc(self, agent_type: str, key: str, default: float) -> float:
        if not self.campus_behavior:
            return default
        return float(self.campus_behavior.pedestrian_influence_ttc_sec.get(agent_type, {}).get(key, default))

    def _apply_pedestrian_factor(self, agent: Dict, factor: float) -> None:
        agent["pedestrian_interaction_factor"] = min(float(agent.get("pedestrian_interaction_factor", 1.0)), max(0.0, factor))
        if agent.get("in_crosswalk"):
            agent["crosswalk_pedestrian_yield_triggered"] = agent.get("crosswalk_pedestrian_yield_triggered", False) or factor < 0.9

    def _pedestrian_clearance_factor(self, agent_type: str, clearance: float, ttc: Optional[float]) -> float:
        """caution_start m -> 1.0, stop_at m -> 0.0, linear in between; TTC can force a harder cut."""
        caution_start = self._pedestrian_gap(agent_type, "caution_start", 9.0)
        stop_at = self._pedestrian_gap(agent_type, "stop_at", 0.5)
        span = max(1e-6, caution_start - stop_at)
        factor = max(0.0, min(1.0, (clearance - stop_at) / span))
        if ttc is not None:
            yield_ttc = self._pedestrian_ttc(agent_type, "yield", 2.0)
            caution_ttc = self._pedestrian_ttc(agent_type, "caution", 4.0)
            if ttc <= yield_ttc:
                factor = 0.0
            elif ttc <= caution_ttc:
                factor = min(factor, (ttc - yield_ttc) / max(1e-6, caution_ttc - yield_ttc))
        return factor

    def speed_constraints(self, entities: Iterable[Dict], base_targets: Dict[str, float]) -> Dict[str, float]:
        active = [entity for entity in entities if entity.get("active") and entity.get("trip_status") == "MOVING"]
        targets = dict(base_targets)
        for entity in active:
            entity["interaction_state"] = "NONE"
            entity["pedestrian_interaction_factor"] = 1.0
            entity["crosswalk_pedestrian_yield_triggered"] = False
            if entity["type"] in ("car", "scooter"):
                entity["nearby_pedestrian_count"] = 0

        density_radius = self.campus_behavior.pedestrian_density_radius_m if self.campus_behavior else 10.0
        density_curve = self.campus_behavior.pedestrian_density_curve if self.campus_behavior else [(0, 1.0)]
        min_gap = self.campus_behavior.following_min_gap_m if self.campus_behavior else {}
        lookahead = self.campus_behavior.following_lookahead_m if self.campus_behavior else {}

        for first, second in self.spatial_index.pairs(active, self.risk_engine.interaction_search_radius):
            metrics = self.risk_engine.calculate_pair(
                first, second, self.risk_engine.prediction_horizon, self.risk_engine.intersection_time_tolerance,
                self.risk_engine.collision_radius,
            )
            if metrics is None or metrics["distance"] > self.risk_engine.interaction_search_radius:
                continue
            interaction = metrics["interaction_state"]
            clearance = max(0.0, float(metrics.get("distance", 0)) - float(metrics.get("collision_envelope", 0)))
            self._set_state(first, interaction)
            self._set_state(second, interaction)
            types = {first["type"], second["type"]}

            if types & {"car", "scooter"} and "person" in types and metrics["distance"] <= density_radius:
                for vehicle in (first, second):
                    if vehicle["type"] in ("car", "scooter"):
                        vehicle["nearby_pedestrian_count"] = int(vehicle.get("nearby_pedestrian_count", 0)) + 1

            # Car-following: constrain only the rear vehicle. The heading
            # projection avoids stopping a parallel/opposite lane vehicle.
            if first["type"] == second["type"] == "car" and interaction == "FOLLOWING":
                self._apply_following(first, second, targets, "car", min_gap.get("car", 6.0), lookahead.get("car", 9.0))

            # Scooter-following: a scooter behind a slower scooter or car in
            # roughly the same lane of travel slows/stops rather than passing
            # through it. No overtaking maneuver is modeled (see project brief).
            if first["type"] == "scooter" and second["type"] in ("scooter", "car") and interaction == "FOLLOWING":
                self._apply_following(first, second, targets, "scooter", min_gap.get("scooter", 2.0), lookahead.get("scooter", 6.0))
            elif second["type"] == "scooter" and first["type"] in ("scooter", "car") and interaction == "FOLLOWING":
                self._apply_following(second, first, targets, "scooter", min_gap.get("scooter", 2.0), lookahead.get("scooter", 6.0))

            if types == {"car", "scooter"} and (metrics["approaching"] or metrics["predicted_path_intersection"]):
                car = first if first["type"] == "car" else second
                factor = max(0.0, min(1.0, (clearance - 1.0) / 8.0))
                if metrics.get("ttc") is not None and metrics["ttc"] <= 2.0:
                    factor = 0.0
                targets[car["id"]] = min(targets[car["id"]], float(car["desired_speed"]) * factor)
                self._set_state(car, "BRAKING" if factor < 0.45 else "APPROACHING")
                scooter = second if car is first else first
                if metrics["predicted_path_intersection"]:
                    targets[scooter["id"]] = min(targets[scooter["id"]], float(scooter["desired_speed"]) * 0.55)
                    self._set_state(scooter, "AVOIDING")

            if types == {"car", "person"} and (metrics["approaching"] or metrics["predicted_path_intersection"]):
                car = first if first["type"] == "car" else second
                person = second if car is first else first
                if person.get("in_crosswalk") or person.get("pedestrian_state") in {"CROSSING", "JAYWALKING"} or metrics["predicted_path_intersection"]:
                    factor = self._pedestrian_clearance_factor("car", clearance, metrics.get("ttc"))
                    density = pedestrian_density_factor(int(car.get("nearby_pedestrian_count", 0)), density_curve)
                    factor = min(factor, density) if factor > 0 else factor
                    targets[car["id"]] = min(targets[car["id"]], float(car["desired_speed"]) * factor)
                    self._set_state(car, "BRAKING")
                    self._apply_pedestrian_factor(car, factor)

            if types == {"person", "scooter"}:
                scooter = first if first["type"] == "scooter" else second
                if metrics["approaching"] or metrics["predicted_path_intersection"] or clearance < 3:
                    factor = self._pedestrian_clearance_factor("scooter", clearance, metrics.get("ttc"))
                    density = pedestrian_density_factor(int(scooter.get("nearby_pedestrian_count", 0)), density_curve)
                    factor = min(factor, density) if factor > 0 else factor
                    targets[scooter["id"]] = min(targets[scooter["id"]], float(scooter["desired_speed"]) * factor)
                    self._set_state(scooter, "AVOIDING")
                    self._apply_pedestrian_factor(scooter, factor)

            # Pedestrian separation: a following pedestrian yields briefly
            # instead of occupying the exact same point.
            if first["type"] == second["type"] == "person" and metrics["distance"] < 1.2:
                slower = first if first["id"] > second["id"] else second
                targets[slower["id"]] = min(targets[slower["id"]], 0.25)
                self._set_state(slower, "AVOIDING")

            if metrics.get("minimum_clearance", metrics["minimum_distance"]) <= self.risk_engine.near_miss_distance and metrics["approaching"]:
                self._set_state(first, "CONFLICT")
                self._set_state(second, "CONFLICT")
        return targets

    @staticmethod
    def _apply_following(follower: Dict, leader: Dict, targets: Dict[str, float], agent_type: str, min_gap: float, lookahead: float) -> None:
        heading = math.radians(float(follower["heading"]))
        forward = math.sin(heading), math.cos(heading)
        offset = float(leader["x"]) - float(follower["x"]), float(leader["z"]) - float(follower["z"])
        longitudinal = offset[0] * forward[0] + offset[1] * forward[1]
        lateral = abs(offset[0] * forward[1] - offset[1] * forward[0])
        lateral_limit = 2.5 if agent_type == "car" else 1.5
        if 0 < longitudinal < lookahead and lateral < lateral_limit:
            # Same proportional-gap formula as the original car-following
            # model (now config-driven via following_lookahead_m instead of
            # a hardcoded 9), extended to scooters. min_gap only selects the
            # reported behavior_state, not the numeric target.
            targets[follower["id"]] = min(targets[follower["id"]], max(0.0, float(leader["speed"]) * (longitudinal / lookahead)))
            InteractionManager._set_state(follower, "BRAKING" if longitudinal <= min_gap else "FOLLOWING")
