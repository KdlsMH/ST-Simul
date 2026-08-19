"""SPEED-1..SPEED-12 tests for the context-aware speed/yield behavior model.

Mirrors the existing test style (test_od_mobility.py, test_agent_statistics.py):
build minimal fixtures (synthetic entities, synthetic GraphPath) and drive the
real RiskEngine/InteractionManager/SimulationEngine/campus_behavior code
directly, rather than re-deriving physics.
"""

from pathlib import Path

import pytest

from simulation import campus_behavior
from simulation.campus_behavior import CampusBehaviorConfig
from simulation.interaction_manager import InteractionManager
from simulation.mobility_graph import GraphPath
from simulation.risk_engine import RiskEngine
from simulation.run_recorder import SimulationRunRecorder
from simulation.simulation_engine import SimulationEngine
from simulation.trip_manager import TripManager

DATA = Path(__file__).resolve().parents[1] / "simulation" / "data"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "simulation" / "config" / "campus_behavior_config.json"


def make_entity(entity_id, entity_type, x, z, speed, heading, **extra):
    return {
        "id": entity_id, "type": entity_type, "x": x, "z": z, "speed": speed, "heading": heading,
        "desired_speed": speed, "active": True, "trip_status": "MOVING", "interaction_state": "NONE",
        **extra,
    }


def make_path(edge_kinds, segment_length=10.0):
    count = len(edge_kinds)
    cumulative = tuple(index * segment_length for index in range(count + 1))
    return GraphPath(
        path_id="TEST", origin="A", destination="B", allowed_types=("scooter",),
        node_ids=tuple(f"N{i}" for i in range(count + 1)), edge_ids=tuple(f"E{i}" for i in range(count)),
        segment_edge_ids=tuple(f"E{i}" for i in range(count)), edge_kinds=tuple(edge_kinds),
        road_ids=tuple(None for _ in range(count)), speed_limits=tuple(20.0 for _ in range(count)),
        points=tuple((float(i * segment_length), 0.0) for i in range(count + 1)),
        segment_lengths=tuple(segment_length for _ in range(count)), cumulative_lengths=cumulative,
        total_length=cumulative[-1],
    )


@pytest.fixture
def config():
    return CampusBehaviorConfig(CONFIG_PATH)


# SPEED-1 -- Agent Type Speed Difference ------------------------------------------------

def test_speed1_free_flow_speed_differs_by_agent_type():
    import random
    from simulation.mobility_graph import MobilityGraph
    from simulation.od_manager import ODManager

    graph = MobilityGraph(DATA / "mobility_graph.json")
    rng = random.Random(1)
    od = ODManager(DATA / "od_demand.json", graph, rng)
    trips = TripManager(graph, od, rng)
    scenario = {"speed_multiplier": 1.0}
    path = trips.create_path("car", "EXTERNAL_MAIN_ROAD_SOUTH", "PARKING_A")

    def mean_speed(agent_type, samples=200):
        return sum(trips.desired_speed(agent_type, path, scenario) for _ in range(samples)) / samples

    car_speed = mean_speed("car")
    scooter_speed = mean_speed("scooter")
    person_speed = mean_speed("person")
    assert person_speed < scooter_speed < car_speed, (person_speed, scooter_speed, car_speed)


# SPEED-2 -- No pedestrian ahead: car reaches free-flow desired speed -------------------

def test_speed2_car_reaches_free_flow_speed_with_no_interference():
    # Isolates the claim precisely: on a straight, uninterrupted CAMPUS_ROAD
    # segment far from any turn/crosswalk, _base_target must not clamp the
    # target below desired_speed. A real routed trip also passes through
    # turns/crosswalks/parking connections -- legitimate, separate context
    # effects -- so it is not used here to avoid conflating the two.
    engine = SimulationEngine(seed=1)
    engine.start(counts={"car": 1, "person": 0, "scooter": 0}, scenario_name="normal")
    entity = next(iter(engine.entities.values()))
    straight_path = make_path(["allowed_road"] * 5, segment_length=50.0)
    entity["current_segment"] = 2
    entity["route_distance"] = 100 + 25  # mid-segment, far from any edge
    entity["road_context"] = "CAMPUS_ROAD"
    entity["edge_kind"] = "allowed_road"
    target = engine._base_target(entity, straight_path)
    assert target >= 0.95 * float(entity["desired_speed"])


# SPEED-3 -- Car with a pedestrian ahead: NORMAL -> CAUTION -> YIELD --------------------

def test_speed3_car_progressively_yields_as_pedestrian_gets_closer(config):
    risk = RiskEngine(DATA / "risk_config.json")
    interactions = InteractionManager(risk, config)

    def factor_and_state(gap):
        car = make_entity("car_1", "car", 0, 0, 5, 0)
        person = make_entity("person_1", "person", 0, gap, 1.0, 180, in_crosswalk=True, pedestrian_state="CROSSING")
        targets = interactions.speed_constraints([car, person], {"car_1": 5, "person_1": 1.0})
        factor = targets["car_1"] / 5.0
        return factor, campus_behavior.behavior_state_from(car["interaction_state"], factor)

    far_factor, far_state = factor_and_state(25.0)
    near_factor, near_state = factor_and_state(2.5)
    assert near_factor < far_factor
    severity = {"NORMAL": 0, "CAUTION": 1, "YIELD": 2, "STOP": 3}
    assert severity[near_state] >= severity[far_state]
    assert near_state in {"YIELD", "STOP"}


# SPEED-4 -- Pedestrian crossing directly ahead: car must fully stop ---------------------

def test_speed4_car_stops_for_pedestrian_directly_crossing(config):
    risk = RiskEngine(DATA / "risk_config.json")
    interactions = InteractionManager(risk, config)
    car = make_entity("car_1", "car", 0, -1.0, 5, 0)
    person = make_entity("person_1", "person", 0, 0.2, 1.2, 90, in_crosswalk=True, pedestrian_state="CROSSING")
    targets = interactions.speed_constraints([car, person], {"car_1": 5, "person_1": 1.2})
    factor = targets["car_1"] / 5.0
    assert targets["car_1"] < 0.5
    assert campus_behavior.behavior_state_from(car["interaction_state"], factor) in {"YIELD", "STOP"}


# SPEED-5 -- Smooth restart after yielding: no instant 0 -> max jump --------------------

def test_speed5_speed_ramps_up_gradually_not_instantly():
    engine = SimulationEngine(seed=4)
    engine.start(counts={"car": 1, "person": 0, "scooter": 0}, scenario_name="normal")
    entity = next(iter(engine.entities.values()))
    entity["speed"] = 0.0
    max_acceleration = float(entity["behavior_profile"]["max_acceleration"])
    engine.step(0.2)
    # Cannot exceed the acceleration cap in a single step regardless of how
    # far below desired_speed the entity started.
    assert entity["speed"] <= max_acceleration * 0.2 + 1e-6
    assert entity["speed"] < float(entity["desired_speed"])


# SPEED-6 -- Road context speed factor mechanism (SHARED_ZONE vs CAMPUS_ROAD) -----------

def test_speed6_shared_zone_context_has_a_lower_speed_factor_than_campus_road(config):
    # This derived network carries no road-width/lane-class source data, so
    # MAIN_ROAD vs NARROW_ROAD/ALLEY are not distinguishable among
    # allowed_road edges (see campus_behavior_config.json's road_context_note).
    # This test instead verifies the road-context-speed-factor mechanism
    # itself using the one genuinely-derivable "tight/shared" context this
    # network does support: SHARED_ZONE (shared_path).
    campus = campus_behavior.road_context_speed_factor("CAMPUS_ROAD", config)
    shared = campus_behavior.road_context_speed_factor("SHARED_ZONE", config)
    assert shared < campus

    path = make_path(["allowed_road", "allowed_road"])
    context_road = campus_behavior.road_context_for(path, 5.0, 0, "scooter", config)
    assert context_road == "CAMPUS_ROAD"
    path_shared = make_path(["shared_path", "shared_path"])
    context_shared = campus_behavior.road_context_for(path_shared, 5.0, 0, "scooter", config)
    assert context_shared == "SHARED_ZONE"


def test_speed6b_crosswalk_approach_is_geometrically_detected_ahead_of_time(config):
    path = make_path(["allowed_road", "crosswalk", "allowed_road"], segment_length=10.0)
    context = campus_behavior.road_context_for(path, 2.0, 0, "car", config)
    assert context == "CROSSWALK_APPROACH"
    context_on = campus_behavior.road_context_for(path, 12.0, 1, "car", config)
    assert context_on == "CROSSWALK"


# SPEED-7 -- Pedestrian density lowers desired speed further -----------------------------

def test_speed7_pedestrian_density_curve_is_monotonically_non_increasing(config):
    curve = config.pedestrian_density_curve
    values = [campus_behavior.pedestrian_density_factor(count, curve) for count in (0, 1, 2, 5, 10, 20)]
    assert values == sorted(values, reverse=True)
    assert values[0] == 1.0
    assert values[-1] < 1.0


def test_speed7b_car_slows_more_with_a_dense_pedestrian_cluster_nearby(config):
    risk = RiskEngine(DATA / "risk_config.json")

    def run(pedestrian_count):
        interactions = InteractionManager(risk, config)
        car = make_entity("car_1", "car", 0, -6, 5, 0)
        crossing_person = make_entity("person_1", "person", 0, 0, 1.0, 90, in_crosswalk=True, pedestrian_state="CROSSING")
        entities = [car, crossing_person]
        targets = {"car_1": 5, "person_1": 1.0}
        for index in range(pedestrian_count - 1):
            bystander = make_entity(f"bystander_{index}", "person", 1.0 + index * 0.3, -4.0, 0.9, 90)
            entities.append(bystander)
            targets[bystander["id"]] = 0.9
        return interactions.speed_constraints(entities, targets)["car_1"]

    sparse = run(1)
    dense = run(8)
    assert dense <= sparse


# SPEED-8 -- Scooter yields to a pedestrian on a shared path ------------------------------

def test_speed8_scooter_slows_for_pedestrian_ahead(config):
    risk = RiskEngine(DATA / "risk_config.json")
    interactions = InteractionManager(risk, config)
    scooter = make_entity("scooter_1", "scooter", 0, 0, 4, 0, road_context="SHARED_ZONE")
    person = make_entity("person_1", "person", 0, 2.5, 1.0, 180)
    targets = interactions.speed_constraints([scooter, person], {"scooter_1": 4, "person_1": 1.0})
    assert targets["scooter_1"] < 4
    assert scooter["interaction_state"] in {"AVOIDING", "CONFLICT"}


# SPEED-9 -- EXP4 scooter free-flow speed scenarios remain distinct ----------------------

def test_speed9_exp4_scooter_speed_scenarios_stay_distinct():
    import random
    from simulation.mobility_graph import MobilityGraph
    from simulation.od_manager import ODManager

    graph = MobilityGraph(DATA / "mobility_graph.json")
    rng = random.Random(2)
    od = ODManager(DATA / "od_demand.json", graph, rng)
    trips = TripManager(graph, od, rng)
    path = trips.create_path("scooter", "BLD_C1", "SCOOTER_PARKING_01")

    def mean_speed(multiplier, samples=300):
        scenario = {"scooter_speed_multiplier": multiplier}
        return sum(trips.desired_speed("scooter", path, scenario) for _ in range(samples)) / samples

    # EXP4_SPEED_10/15/20/25 correspond to progressively higher scooter_speed_multiplier.
    speeds = [mean_speed(multiplier) for multiplier in (0.6, 1.0, 1.3, 1.6)]
    assert speeds == sorted(speeds)
    assert speeds[0] < speeds[-1]


# SPEED-10 -- EXP5 crosswalk policies keep their distinct base speeds --------------------

def test_speed10_exp5_crosswalk_policies_have_distinct_speeds(config):
    free_flow = 15.0 / 3.6
    ride_through_speed, ride_through_name = campus_behavior.crosswalk_target_speed_mps("scooter", "ride_through", free_flow, config)
    slow_speed, slow_name = campus_behavior.crosswalk_target_speed_mps("scooter", "slow_riding", free_flow, config)
    dismount_speed, dismount_name = campus_behavior.crosswalk_target_speed_mps("scooter", "dismount", free_flow, config)

    assert ride_through_name == "ride_through" and ride_through_speed == pytest.approx(free_flow)
    assert slow_name == "slow_riding" and slow_speed == pytest.approx(6.0 / 3.6)
    assert dismount_name == "dismount" and dismount_speed == pytest.approx(1.4)
    assert dismount_speed < slow_speed < ride_through_speed


def test_speed10b_base_target_applies_scenario_crosswalk_policy_end_to_end():
    engine = SimulationEngine(seed=9)
    engine.start(counts={"car": 0, "person": 0, "scooter": 1}, scenario_name="normal")
    entity = next(iter(engine.entities.values()))
    path = engine.paths[entity["id"]]
    entity["current_segment"] = 0
    entity["edge_kind"] = "crosswalk"
    entity["desired_speed"] = 15.0 / 3.6

    engine.scenario["crosswalk_policy"] = "dismount"
    dismount_target = engine._base_target(entity, path)
    engine.scenario["crosswalk_policy"] = "ride_through"
    ride_through_target = engine._base_target(entity, path)
    assert dismount_target < ride_through_target
    assert dismount_target == pytest.approx(1.4, abs=0.05)


# SPEED-11 -- Seed reproducibility of speed/behavior variation ---------------------------

def test_speed11_same_seed_reproduces_agent_speed_variation():
    counts = {"car": 5, "person": 5, "scooter": 5}
    engine_a = SimulationEngine(seed=123)
    engine_a.start(counts=counts, scenario_name="normal")
    engine_b = SimulationEngine(seed=123)
    engine_b.start(counts=counts, scenario_name="normal")

    a_speeds = [round(float(entity["desired_speed"]), 6) for entity in engine_a.entities.values()]
    b_speeds = [round(float(entity["desired_speed"]), 6) for entity in engine_b.entities.values()]
    a_profiles = [entity["behavior_profile"]["name"] for entity in engine_a.entities.values()]
    b_profiles = [entity["behavior_profile"]["name"] for entity in engine_b.entities.values()]
    assert a_speeds == b_speeds
    assert a_profiles == b_profiles


# SPEED-12 -- Recorder reflects yield/stop/behavior data ---------------------------------

def test_speed12_recorder_persists_behavior_statistics_and_risk_event_context(tmp_path):
    import json

    engine = SimulationEngine(seed=13)
    engine.recorder = SimulationRunRecorder(engine, output_root=tmp_path)
    engine.start(counts={"car": 12, "person": 25, "scooter": 8}, scenario_name="normal")
    for _ in range(700):
        engine.step(0.1)
    engine.stop()

    run_dir = next(path for path in tmp_path.iterdir() if path.is_dir())
    statistics = json.loads((run_dir / "simulation_statistics.json").read_text(encoding="utf-8"))
    behavior = statistics["behavior"]
    assert behavior["mean_speed"]["car"] is not None
    total_yield_or_stop = sum(behavior["pedestrian_yield_count"].values()) + sum(behavior["pedestrian_full_stop_count"].values())
    assert total_yield_or_stop > 0, "expected at least one car/scooter yield or stop for a pedestrian over 70 simulated seconds"

    risk_lines = (run_dir / "risk_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert risk_lines
    sample = json.loads(risk_lines[0])
    for key in ("agent_speeds", "agent_desired_speeds", "agent_behavior_states", "agent_road_contexts", "nearby_pedestrian_count"):
        assert key in sample

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["behavior_model"]["name"] == "campus_context_aware"
    assert manifest["behavior_config_hash"].startswith("sha256:")


# Section 87 -- config_hash must react to behavior-model parameter changes --------------

def test_config_hash_reacts_to_campus_behavior_config_and_crosswalk_policy_changes():
    from simulation.run_recorder import SimulationRunRecorder, _canonical_sha256

    engine = SimulationEngine(seed=1)
    recorder = SimulationRunRecorder(engine)
    baseline_hash = _canonical_sha256(recorder._config_payload())

    engine.campus_behavior.raw["road_context_speed_factor"]["SHARED_ZONE"] = 0.11
    changed_hash = _canonical_sha256(recorder._config_payload())
    assert baseline_hash != changed_hash

    engine2 = SimulationEngine(seed=1)
    recorder2 = SimulationRunRecorder(engine2)
    before_policy = _canonical_sha256(recorder2._config_payload())
    engine2.scenario["crosswalk_policy"] = "dismount"
    after_policy = _canonical_sha256(recorder2._config_payload())
    assert before_policy != after_policy
