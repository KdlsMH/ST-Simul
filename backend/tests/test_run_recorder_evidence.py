"""Evidence-integrity tests for the Run Recorder.

These complement (not duplicate) the closed-form TTC/PET math tests in
test_risk_engine.py and test_pet.py. Scope here:

1. A recorded run's files are internally self-consistent and physically
   plausible (via simulation.tools.validate_run_evidence).
2. A known-correct RiskEngine output survives the Recorder's persistence
   pipeline unchanged (no rounding/mapping corruption between "computed" and
   "written to disk").
3. Reproducibility actually holds when driven with a fixed dt/seed, and does
   NOT hold if the step schedule differs -- documenting precisely what
   "same seed" does and does not guarantee for this real-time engine.
"""

import json
from pathlib import Path

from simulation.risk_engine import RiskEngine
from simulation.run_recorder import SimulationRunRecorder
from simulation.simulation_engine import SimulationEngine
from simulation.tools.validate_run_evidence import validate_run

RISK_CONFIG = Path(__file__).resolve().parents[1] / "simulation" / "data" / "risk_config.json"


def _engine(counts=None, scenario="normal", seed=1, output_root=None):
    engine = SimulationEngine(seed=seed)
    engine.recorder = SimulationRunRecorder(engine, output_root=output_root)
    engine.start(counts=counts or {"car": 3, "person": 3, "scooter": 3}, scenario_name=scenario)
    return engine


def _only_run_dir(output_root: Path) -> Path:
    dirs = [path for path in output_root.iterdir() if path.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def _drive(engine, steps, dt=0.1):
    for _ in range(steps):
        engine.step(dt)


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# -- 1. Recorded-run evidence validation ------------------------------------------------

def test_recorded_run_passes_internal_consistency_and_plausibility_checks(tmp_path):
    engine = _engine(counts={"car": 15, "person": 20, "scooter": 10}, seed=5, output_root=tmp_path)
    _drive(engine, 800)
    engine.stop()

    run_dir = _only_run_dir(tmp_path)
    checks = validate_run(run_dir, graph=engine.graph)
    failed = [check for check in checks if not check.passed and "(informational)" not in check.name]
    assert not failed, "\n".join(str(check) for check in failed)
    # Sanity: the run actually produced something to check, not a trivially-empty pass.
    stats = json.loads((run_dir / "simulation_statistics.json").read_text(encoding="utf-8"))
    assert stats["safety"]["conflict_count"] > 0
    assert stats["mobility"]["completed_trips"] > 0

    # partial_initial_segment must be true exactly for first trips (trip_start_time == spawned_at)
    # of agents that were part of the initial mid-route-distributed population.
    import csv
    with open(run_dir / "completed_trips.csv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            is_first_trip = row["trip_start_time"] == row["spawned_at"]
            if row["partial_initial_segment"] == "True":
                assert is_first_trip, row


# -- 2. A known-correct RiskEngine value survives the recording pipeline unchanged ------

def test_known_danger_scenario_ttc_pet_clearance_survive_the_recording_pipeline(tmp_path):
    risk = RiskEngine(RISK_CONFIG)
    first = {"id": "scooter_1", "type": "scooter", "x": 0, "z": 0, "speed": 4, "heading": 90, "active": True}
    second = {"id": "person_1", "type": "person", "x": 1, "z": 0, "speed": 0, "heading": 0, "active": True}
    events = risk.evaluate([first, second], 1.0)
    assert len(events) == 1, "expected the same danger-level collision course used in test_risk_engine.py"
    expected = events[0]
    assert expected["safety_event"] == "COLLISION"
    assert expected["risk_level"] == "danger"
    assert expected["ttc"] == 0.0

    engine = _engine(output_root=tmp_path)
    engine.recorder.on_step({"scooter_1": first, "person_1": second}, events, 1.0)
    engine.stop()

    recorded = _read_jsonl(_only_run_dir(tmp_path) / "risk_events.jsonl")
    assert len(recorded) == 1
    row = recorded[0]
    assert row["ttc"] == expected["ttc"]
    assert row["pet"] == expected["pet"]
    assert row["clearance"] == expected["minimum_clearance"]
    assert row["relative_speed"] == expected["relative_speed"]
    assert row["distance"] == expected["distance"]
    assert row["severity"] == expected["risk_level"]
    assert row["risk_score"] == expected["risk_score"]
    assert row["event_type"] == expected["safety_event"]
    assert set(row["involved_agent_ids"]) == {"scooter_1", "person_1"}


# -- 3. Reproducibility: exact given fixed dt + same seed; breaks if the step schedule differs --

def test_same_seed_and_fixed_dt_schedule_reproduces_statistics_exactly(tmp_path):
    counts = {"car": 8, "person": 8, "scooter": 8}
    engine_a = _engine(counts=counts, seed=99, output_root=tmp_path / "a")
    _drive(engine_a, 300)
    engine_a.stop()

    engine_b = _engine(counts=counts, seed=99, output_root=tmp_path / "b")
    _drive(engine_b, 300)
    engine_b.stop()

    stats_a = json.loads((_only_run_dir(tmp_path / "a") / "simulation_statistics.json").read_text(encoding="utf-8"))
    stats_b = json.loads((_only_run_dir(tmp_path / "b") / "simulation_statistics.json").read_text(encoding="utf-8"))
    stats_a.pop("run_id"), stats_b.pop("run_id")
    assert stats_a == stats_b

    trips_a = (_only_run_dir(tmp_path / "a") / "completed_trips.csv").read_text(encoding="utf-8")
    trips_b = (_only_run_dir(tmp_path / "b") / "completed_trips.csv").read_text(encoding="utf-8")
    # run_id is the only column expected to differ between the two runs.
    strip_run_id = lambda text: "\n".join(",".join(line.split(",")[1:]) for line in text.splitlines())
    assert strip_run_id(trips_a) == strip_run_id(trips_b)


def test_different_step_schedule_breaks_reproducibility_even_with_same_seed(tmp_path):
    """Documents a real limitation: this engine is real-time/wall-clock driven
    in production (see main.py's _simulation_loop, which computes dt from
    elapsed wall-clock time each tick). Same SIMULATION_SEED alone does not
    guarantee identical results between two live UI runs, because the RNG is
    advanced once per *step call*, not once per simulated second -- a
    different step/dt schedule reaching the same simulation_time produces a
    different sequence of RNG draws. Exact reproducibility requires the same
    seed AND the same step schedule (e.g. a fixed-dt script), not seed alone.
    """
    counts = {"car": 8, "person": 8, "scooter": 8}
    engine_a = _engine(counts=counts, seed=99, output_root=tmp_path / "a")
    _drive(engine_a, 300, dt=0.1)  # 30.0 simulated seconds over 300 steps
    engine_a.stop()

    engine_b = _engine(counts=counts, seed=99, output_root=tmp_path / "b")
    _drive(engine_b, 150, dt=0.2)  # same 30.0 simulated seconds over half as many steps
    engine_b.stop()

    stats_a = json.loads((_only_run_dir(tmp_path / "a") / "simulation_statistics.json").read_text(encoding="utf-8"))
    stats_b = json.loads((_only_run_dir(tmp_path / "b") / "simulation_statistics.json").read_text(encoding="utf-8"))
    assert stats_a["run_id"] != stats_b["run_id"]
    # Same total simulated duration...
    manifest_a = json.loads((_only_run_dir(tmp_path / "a") / "manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((_only_run_dir(tmp_path / "b") / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_a["duration_sec"] == manifest_b["duration_sec"] == 30.0
    # ...but a different step schedule is expected to diverge the outcome.
    del stats_a["run_id"], stats_b["run_id"]
    assert stats_a != stats_b
