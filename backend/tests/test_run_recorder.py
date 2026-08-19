import json
from pathlib import Path

import pytest

from simulation.run_recorder import SimulationRunRecorder, list_runs, read_run_detail, resolve_run_dir
from simulation.simulation_engine import SimulationEngine
from simulation.statistics_manager import METRIC_DEFAULTS


def _engine(counts=None, scenario="normal", seed=1, output_root=None):
    engine = SimulationEngine(seed=seed)
    engine.recorder = SimulationRunRecorder(engine, output_root=output_root)
    engine.start(counts=counts or {"car": 3, "person": 3, "scooter": 3}, scenario_name=scenario)
    return engine


def _only_run_dir(output_root: Path) -> Path:
    dirs = [path for path in output_root.iterdir() if path.is_dir()]
    assert len(dirs) == 1, f"expected exactly one run directory, found {dirs}"
    return dirs[0]


def _fake_entity(agent_id: str, agent_type: str) -> dict:
    return {
        "id": agent_id, "type": agent_type, "agent_type": agent_type, "active": True,
        "risk_level": "normal", "x": 0.0, "z": 0.0, "speed": 0.0, "heading": 0.0,
        "metrics": dict(METRIC_DEFAULTS),
    }


# Test 1 -- Start -> Stop
def test_start_then_stop_creates_a_completed_run(tmp_path):
    engine = _engine(output_root=tmp_path)
    for _ in range(20):
        engine.step(0.1)
    engine.stop()

    run_dir = _only_run_dir(tmp_path)
    assert (run_dir / "manifest.json").exists()
    assert not (run_dir / "manifest.partial.json").exists()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["termination_reason"] == "user_stop"
    assert manifest["run_id"] == engine.recorder.active_run_id or manifest["run_id"]
    for name in ("simulation_statistics.json", "completed_trips.csv", "agent_summary.csv", "risk_events.jsonl", "trajectory.jsonl", "simulation.log"):
        assert (run_dir / name).exists(), name
    statistics = json.loads((run_dir / "simulation_statistics.json").read_text(encoding="utf-8"))
    assert "safety" in statistics and "mobility" in statistics


# Test 2 -- Start -> Pause -> Resume -> Stop
def test_pause_resume_preserves_the_same_run_id(tmp_path):
    engine = _engine(output_root=tmp_path)
    run_id = engine.recorder.active_run_id
    assert run_id is not None
    for _ in range(10):
        engine.step(0.1)
    engine.pause()
    assert engine.recorder.active_run_id == run_id
    engine.resume()
    assert engine.recorder.active_run_id == run_id
    for _ in range(10):
        engine.step(0.1)
    engine.stop()

    run_dir = _only_run_dir(tmp_path)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "completed"
    assert len(manifest["pause_history"]) == 2
    assert "paused_at_sim_time" in manifest["pause_history"][0]
    assert "resumed_at_sim_time" in manifest["pause_history"][1]


# Test 3 -- Start -> Reset
def test_reset_finalizes_the_run_as_completed_user_reset(tmp_path):
    engine = _engine(output_root=tmp_path)
    for _ in range(10):
        engine.step(0.1)
    engine.reset()

    run_dir = _only_run_dir(tmp_path)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["termination_reason"] == "user_reset"


# Test 4 -- Completed Agent Despawn
def test_completed_trip_survives_agent_despawn(tmp_path):
    engine = _engine(counts={"car": 10, "person": 10, "scooter": 10}, seed=11, output_root=tmp_path)
    despawned_id = None
    for _ in range(1500):
        before = set(engine.entities.keys())
        engine.step(0.1)
        removed = before - set(engine.entities.keys())
        if removed:
            despawned_id = next(iter(removed))
            break
    assert despawned_id is not None, "expected at least one agent to despawn within the step budget"
    assert despawned_id not in engine.entities
    engine.stop()

    run_dir = _only_run_dir(tmp_path)
    trips_text = (run_dir / "completed_trips.csv").read_text(encoding="utf-8")
    assert despawned_id in trips_text
    summary_text = (run_dir / "agent_summary.csv").read_text(encoding="utf-8")
    assert despawned_id in summary_text


# Test 5 -- Risk events beyond the 500-entry UI ring buffer
def test_risk_events_exceed_ui_ring_buffer_but_full_history_is_persisted(tmp_path):
    engine = _engine(counts={"car": 1, "person": 1, "scooter": 0}, output_root=tmp_path)
    entities = {"car_A": _fake_entity("car_A", "car"), "person_B": _fake_entity("person_B", "person")}
    total_events = 800
    for index in range(total_events):
        event = {
            "event_id": f"synthetic_{index:04d}", "object_ids": ["car_A", "person_B"],
            "agent_types": ["car", "person"], "ttc": 1.0, "pet": None, "minimum_clearance": 0.5,
            "distance": 2.0, "relative_speed": 1.0, "risk_score": 70, "risk_level": "warning",
            "safety_event": "TRAFFIC_CONFLICT", "simulation_time": float(index), "location_id": None,
        }
        # Exercises the same StatisticsManager code path the engine uses,
        # without paying for 800 real risk-detection steps of physics.
        engine.statistics_manager.record_events([event], entities, 0.1, float(index))
        engine.recorder.on_step(entities, [event], float(index))
    engine.stop()

    assert len(engine.statistics_manager.safety_events) == 500  # UI ring buffer stays capped

    run_dir = _only_run_dir(tmp_path)
    with open(run_dir / "risk_events.jsonl", encoding="utf-8") as handle:
        line_count = sum(1 for _ in handle)
    assert line_count == total_events


# Test 6 -- A run with no events must not emit NaN/Infinity into JSON
def test_run_without_events_has_null_safety_minimums_and_valid_json(tmp_path):
    engine = _engine(counts={"car": 0, "person": 0, "scooter": 0}, output_root=tmp_path)
    for _ in range(5):
        engine.step(0.1)
    engine.stop()

    run_dir = _only_run_dir(tmp_path)
    raw_text = (run_dir / "simulation_statistics.json").read_text(encoding="utf-8")
    assert "NaN" not in raw_text
    assert "Infinity" not in raw_text
    statistics = json.loads(raw_text)
    assert statistics["safety"]["min_ttc"] is None
    assert statistics["safety"]["min_pet"] is None
    assert statistics["mobility"]["avg_travel_time"] is None


# Test 7 -- Abnormal termination leaves a partial manifest and preserves data written so far
def test_abnormal_termination_leaves_partial_manifest_and_recorded_data(tmp_path):
    engine = _engine(counts={"car": 5, "person": 5, "scooter": 5}, seed=2, output_root=tmp_path)
    for _ in range(50):
        engine.step(0.1)
    # Simulate a process crash: never call stop()/reset(), so finalize() never
    # runs. Explicitly closing the file handles here stands in for what the
    # OS does automatically when a real process dies -- it is not a Recorder
    # API and is only needed so pytest can clean up tmp_path on Windows.
    engine.recorder._run.close_streams()

    run_dir = _only_run_dir(tmp_path)
    assert (run_dir / "manifest.partial.json").exists()
    assert not (run_dir / "manifest.json").exists()
    partial = json.loads((run_dir / "manifest.partial.json").read_text(encoding="utf-8"))
    assert partial["status"] == "running"
    assert (run_dir / "risk_events.jsonl").exists()
    assert (run_dir / "trajectory.jsonl").exists()
    trajectory_lines = (run_dir / "trajectory.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(trajectory_lines) > 0


# Test 8 -- Same seed/scenario/network/config reproduces identical hashes
def test_same_seed_and_config_produce_identical_reproducibility_metadata(tmp_path):
    first = _engine(seed=42, output_root=tmp_path / "a")
    second = _engine(seed=42, output_root=tmp_path / "b")
    first.stop()
    second.stop()

    first_manifest = json.loads((_only_run_dir(tmp_path / "a") / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((_only_run_dir(tmp_path / "b") / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest["network_hash"] == second_manifest["network_hash"]
    assert first_manifest["config_hash"] == second_manifest["config_hash"]
    assert first_manifest["seed"] == second_manifest["seed"] == 42


# Test 9 -- Different seed is reflected in the manifest but not in config_hash
def test_different_seed_changes_seed_field_not_config_hash(tmp_path):
    first = _engine(seed=1, output_root=tmp_path / "a")
    second = _engine(seed=2, output_root=tmp_path / "b")
    first.stop()
    second.stop()

    first_manifest = json.loads((_only_run_dir(tmp_path / "a") / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((_only_run_dir(tmp_path / "b") / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest["seed"] != second_manifest["seed"]
    # config_hash intentionally excludes seed so external analysis can group
    # runs that share a scenario configuration across many seeds.
    assert first_manifest["config_hash"] == second_manifest["config_hash"]
    assert first_manifest["network_hash"] == second_manifest["network_hash"]


# Test 10 -- Network hash changes when the runtime network payload changes
def test_network_hash_changes_when_network_payload_changes(tmp_path):
    engine = _engine(output_root=tmp_path / "a")
    engine.stop()
    unmodified_hash = json.loads((_only_run_dir(tmp_path / "a") / "manifest.json").read_text(encoding="utf-8"))["network_hash"]

    engine2 = SimulationEngine(seed=1)
    engine2.graph_payload = {**engine2.graph_payload, "nodes": list(engine2.graph_payload["nodes"]) + [{"id": "SYNTHETIC_TEST_NODE", "x": 0.0, "z": 0.0}]}
    engine2.recorder = SimulationRunRecorder(engine2, output_root=tmp_path / "b")
    engine2.start(counts={"car": 3, "person": 3, "scooter": 3}, scenario_name="normal")
    engine2.stop()
    modified_hash = json.loads((_only_run_dir(tmp_path / "b") / "manifest.json").read_text(encoding="utf-8"))["network_hash"]

    assert unmodified_hash != modified_hash


# Test 11 -- Config hash changes when scenario-affecting settings change
def test_config_hash_changes_when_scenario_counts_change(tmp_path):
    baseline = _engine(counts={"car": 3, "person": 3, "scooter": 3}, output_root=tmp_path / "a")
    baseline.stop()
    changed = _engine(counts={"car": 20, "person": 3, "scooter": 3}, output_root=tmp_path / "b")
    changed.stop()

    baseline_hash = json.loads((_only_run_dir(tmp_path / "a") / "manifest.json").read_text(encoding="utf-8"))["config_hash"]
    changed_hash = json.loads((_only_run_dir(tmp_path / "b") / "manifest.json").read_text(encoding="utf-8"))["config_hash"]
    assert baseline_hash != changed_hash


# Test 12 -- Atomic finalization: .partial files are renamed away on success
def test_finalize_renames_partial_files_to_final_names(tmp_path):
    engine = _engine(output_root=tmp_path)
    engine.stop()

    run_dir = _only_run_dir(tmp_path)
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "simulation_statistics.json").exists()
    assert (run_dir / "agent_summary.csv").exists()
    assert not (run_dir / "manifest.partial.json").exists()
    assert not (run_dir / "simulation_statistics.partial.json").exists()
    assert not (run_dir / "agent_summary.partial.csv").exists()


# Test 13 -- Double finalize is idempotent
def test_double_finalize_does_not_duplicate_or_corrupt_results(tmp_path):
    engine = _engine(output_root=tmp_path)
    for _ in range(10):
        engine.step(0.1)
    engine.stop()
    run_dir = _only_run_dir(tmp_path)
    manifest_before = (run_dir / "manifest.json").read_text(encoding="utf-8")

    engine.stop()  # second finalize attempt on an already-finalized run
    engine.reset()  # a differently-triggered second finalize attempt too

    assert [path for path in tmp_path.iterdir() if path.is_dir()] == [run_dir]
    manifest_after = (run_dir / "manifest.json").read_text(encoding="utf-8")
    assert manifest_before == manifest_after


# -- Read-only API helper coverage --------------------------------------------------

def test_list_runs_and_resolve_run_dir_and_detail(tmp_path):
    engine = _engine(output_root=tmp_path)
    run_id = engine.recorder.active_run_id
    engine.stop()

    runs = list_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["status"] == "completed"

    resolved = resolve_run_dir(tmp_path, run_id)
    assert resolved == _only_run_dir(tmp_path)

    detail = read_run_detail(tmp_path, run_id)
    assert detail["manifest"]["run_id"] == run_id
    assert detail["statistics"] is not None


def test_resolve_run_dir_rejects_path_traversal_and_unknown_ids(tmp_path):
    engine = _engine(output_root=tmp_path)
    engine.stop()

    assert resolve_run_dir(tmp_path, "../../etc/passwd") is None
    assert resolve_run_dir(tmp_path, "run_doesnotexist") is None
    assert resolve_run_dir(tmp_path, "") is None


# -- Read-only HTTP API surface (main.py) --------------------------------------------------

def test_run_history_http_api():
    # main.py builds one module-level provider/engine/recorder at import
    # time (shared with other API tests via conftest's SIMULATION_RUN_OUTPUT_DIR),
    # so this only asserts that *this* run shows up correctly, not that it is
    # the only run in the shared output directory.
    from fastapi.testclient import TestClient
    from simulation.main import app

    with TestClient(app) as client:
        started = client.post("/api/simulation/start", json={"scenario": "normal", "counts": {"car": 2, "person": 2, "scooter": 2}})
        run_id = started.json()["active_run_id"]
        assert run_id
        client.post("/api/simulation/selection", json={"agent_ids": ["car_001"]})
        client.post("/api/simulation/reset")

        runs = client.get("/api/simulation/runs").json()["runs"]
        matching = next((row for row in runs if row["run_id"] == run_id), None)
        assert matching is not None
        assert matching["status"] == "completed"

        detail = client.get(f"/api/simulation/runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["manifest"]["run_id"] == run_id

        download = client.get(f"/api/simulation/runs/{run_id}/download")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"
        assert len(download.content) > 0

        assert client.get("/api/simulation/runs/run_doesnotexist").status_code == 404
        assert client.get("/api/simulation/runs/../../etc/passwd").status_code == 404
