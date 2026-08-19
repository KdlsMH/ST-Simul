from simulation.statistics_manager import StatisticsManager


def test_agent_statistics_record_raw_safety_minima_and_full_trajectory():
    manager = StatisticsManager()
    first = {"id": "car_1", "type": "car", "x": 1, "y": 0, "z": 2, "speed": 3, "heading": 45, "trip_status": "MOVING", "active": True, "risk_level": "warning", "state": "BRAKING", "current_edge": "VL_1"}
    second = {"id": "person_1", "type": "person", "x": 2, "y": 0, "z": 2, "speed": 1, "heading": 90, "trip_status": "MOVING", "active": True, "risk_level": "warning", "state": "CROSSING", "current_edge": "CW_1"}
    manager.register(first, 0); manager.register(second, 0)
    event = {"event_id": "risk_1", "object_ids": ["car_1", "person_1"], "risk_score": 87, "ttc": 1.2, "pet": 0.8, "safety_event": "NEAR_MISS", "simulation_time": 0}
    manager.record_events([event], {"car_1": first, "person_1": second}, 0.1, 0)
    assert first["metrics"]["minimum_ttc"] == 1.2
    assert first["metrics"]["minimum_pet"] == 0.8
    assert first["metrics"]["maximum_risk"] == 87
    assert first["metrics"]["conflict_count"] == 1
    assert manager.trajectory("car_1")[0]["edge_id"] == "VL_1"


def test_live_statistics_keep_counts_but_bound_event_memory():
    manager = StatisticsManager()
    first = {"id": "car_1", "type": "car", "x": 0, "z": 0, "active": True, "risk_level": "warning"}
    second = {"id": "person_1", "type": "person", "x": 1, "z": 0, "active": True, "risk_level": "warning"}
    manager.register(first, 0); manager.register(second, 0)
    events = [{"event_id": f"risk_{index}", "object_ids": ["car_1", "person_1"], "risk_score": 80, "ttc": 2.0, "pet": None, "minimum_clearance": 0.5, "safety_event": "TRAFFIC_CONFLICT", "simulation_time": 0} for index in range(600)]
    manager.record_events(events, {"car_1": first, "person_1": second}, .1, 0)
    snapshot = manager.aggregate([first, second], 10)
    assert snapshot["conflict_count"] == 600
    assert snapshot["min_ttc"] == 2.0
    assert len(manager.safety_events) == 500
