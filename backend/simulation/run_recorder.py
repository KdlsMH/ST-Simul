"""Persistent, per-run recorder for a single UI-driven simulation execution.

Scope and intent
-----------------
This module implements the *SimulationRunRecorder* described in the project
brief: every time a user presses Start in the UI, one independent, permanent
research record is written to ``simulation_output/run_<...>/``. It does not
run simulations, does not repeat them, and does not aggregate results across
runs -- it only observes one live run via a small set of hook calls made by
:class:`~simulation.simulation_engine.SimulationEngine` and writes what it
observes to disk.

The recorder deliberately does not recompute TTC/PET/conflict classification.
It only reads values already produced by :mod:`simulation.risk_engine` and
:mod:`simulation.statistics_manager` and persists them. Disabling the
recorder (``SIMULATION_RECORDING_ENABLED=false``) must not change simulation
behaviour or results.

Hashing policy (documented here per project requirement)
----------------------------------------------------------
``network_hash`` and ``config_hash`` are SHA-256 digests of a *canonical* JSON
serialisation: ``json.dumps(payload, sort_keys=True, separators=(",", ":"),
ensure_ascii=True)``. Sorting object keys and using compact separators makes
the digest independent of key ordering and incidental whitespace, so two
runs with identical inputs always hash identically regardless of how the
Python dict happened to be built. The digest is stored as ``"sha256:<hex>"``.

- ``network_hash`` hashes the exact runtime graph payload
  (:pyattr:`SimulationEngine.graph_payload`, the same dict passed to
  :class:`~simulation.mobility_graph.MobilityGraph`) -- not a file path or
  modification time.
- ``config_hash`` hashes the scenario configuration plus the static risk and
  behavior policy documents that influence simulation outcomes, deliberately
  *excluding* the seed (seed is tracked as its own manifest field so that
  runs sharing a config but differing only in seed share a ``config_hash``,
  which is what the external statistical-analysis grouping in the project
  brief expects).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = Path(os.getenv("SIMULATION_RUN_OUTPUT_DIR") or (REPO_ROOT / "simulation_output"))
SIMULATION_ENGINE_VERSION = "1.0.0"  # keep aligned with FastAPI app version in main.py

RUN_DIR_PATTERN = re.compile(r"^run_\d{8}_\d{6}_[0-9a-f]{1,16}$")
RUN_ID_PATTERN = re.compile(r"^run_[0-9a-f]{6,32}$")

_fallback_logger = logging.getLogger("simulation.run_recorder")


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _iso(moment: Optional[datetime] = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _json_safe(value):
    """Recursively replace non-finite floats with ``None`` before serialising.

    ``statistics_manager`` never stores inf/NaN today, but this is a cheap
    defensive net so ``simulation_statistics.json`` can never contain the
    invalid-JSON tokens ``Infinity``/``NaN``.
    """
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _canonical_sha256(payload) -> str:
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json_if_exists(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _git_commit_hash() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=2, check=False,
        )
        value = result.stdout.strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


COMPLETED_TRIP_FIELDS = [
    "run_id", "agent_id", "agent_type", "trip_id", "origin", "destination",
    "spawned_at", "trip_start_time", "completed_at", "travel_time",
    "waiting_time", "trip_distance", "partial_initial_segment",
]

AGENT_SUMMARY_FIELDS = [
    "run_id", "agent_id", "agent_type", "spawn_time", "completed_trip_count",
    "still_active_at_finalize", "travel_time_total", "waiting_time_total",
    "trip_distance_total", "risk_event_count", "near_miss_count",
    "conflict_count", "collision_count", "hard_braking_count", "min_ttc",
    "min_clearance",
]

TRAJECTORY_REASONS = {"sampled", "risk_event", "selected_agent"}


class _AgentSummary:
    __slots__ = (
        "agent_id", "agent_type", "spawn_time", "completed_trip_count",
        "travel_time_total", "waiting_time_total", "trip_distance_total",
        "risk_event_count", "near_miss_count", "conflict_count",
        "collision_count", "hard_braking_count", "min_ttc", "min_clearance",
    )

    def __init__(self, agent_id: str, agent_type: str, spawn_time: float) -> None:
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.spawn_time = spawn_time
        self.completed_trip_count = 0
        self.travel_time_total = 0.0
        self.waiting_time_total = 0.0
        self.trip_distance_total = 0.0
        self.risk_event_count = 0
        self.near_miss_count = 0
        self.conflict_count = 0
        self.collision_count = 0
        self.hard_braking_count = 0
        self.min_ttc: Optional[float] = None
        self.min_clearance: Optional[float] = None

    def as_row(self, run_id: str, still_active: bool) -> Dict:
        return {
            "run_id": run_id, "agent_id": self.agent_id, "agent_type": self.agent_type,
            "spawn_time": round(self.spawn_time, 3), "completed_trip_count": self.completed_trip_count,
            "still_active_at_finalize": still_active,
            "travel_time_total": round(self.travel_time_total, 3),
            "waiting_time_total": round(self.waiting_time_total, 3),
            "trip_distance_total": round(self.trip_distance_total, 3),
            "risk_event_count": self.risk_event_count, "near_miss_count": self.near_miss_count,
            "conflict_count": self.conflict_count, "collision_count": self.collision_count,
            "hard_braking_count": self.hard_braking_count,
            "min_ttc": self.min_ttc, "min_clearance": self.min_clearance,
        }


class _ActiveRun:
    """Mutable state for the run currently being recorded. One at a time."""

    def __init__(self, run_id: str, run_dir: Path, manifest: Dict) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.manifest = manifest
        self.finalized = False
        self.recording_failed = False
        self.failure_notes: List[str] = []
        self.pause_history: List[Dict] = []
        self.agents: Dict[str, _AgentSummary] = {}
        self.last_trajectory_sample: Dict[str, float] = {}
        self.selected_agent_ids: set = set()

        self.logger = logging.getLogger(f"simulation.recorder.{run_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self._log_handler = logging.FileHandler(run_dir / "simulation.log", encoding="utf-8")
        self._log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(self._log_handler)

        self.risk_file = open(run_dir / "risk_events.jsonl", "a", encoding="utf-8")
        self.trajectory_file = open(run_dir / "trajectory.jsonl", "a", encoding="utf-8")
        self.trip_file = open(run_dir / "completed_trips.csv", "a", newline="", encoding="utf-8")
        self.trip_writer = csv.DictWriter(self.trip_file, fieldnames=COMPLETED_TRIP_FIELDS)
        self.trip_writer.writeheader()
        self.trip_file.flush()

    def close_streams(self) -> None:
        for handle in (self.risk_file, self.trajectory_file, self.trip_file):
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass
        try:
            self.logger.removeHandler(self._log_handler)
            self._log_handler.close()
        except OSError:
            pass


class SimulationRunRecorder:
    """Observer attached to one :class:`SimulationEngine`.

    Wiring is intentionally one-directional: the engine calls ``on_*`` hooks
    at the points where user-visible lifecycle transitions or already-computed
    statistics/events become available; the recorder never reaches back into
    the engine's decision logic. See ``SIMULATION_ARCHITECTURE.md`` /
    ``RISK_ENGINE_SPEC.md`` for what the engine itself guarantees.
    """

    def __init__(
        self,
        engine,
        output_root: Optional[Path] = None,
        provider_name: str = "InternalSimulationProvider",
        enabled: Optional[bool] = None,
        trajectory_sample_interval_sec: Optional[float] = None,
    ) -> None:
        self.engine = engine
        self.output_root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
        self.provider_name = provider_name
        self.enabled = (
            enabled if enabled is not None
            else os.getenv("SIMULATION_RECORDING_ENABLED", "true").strip().lower() not in {"0", "false", "no"}
        )
        self.trajectory_sample_interval_sec = float(
            trajectory_sample_interval_sec
            if trajectory_sample_interval_sec is not None
            else os.getenv("SIMULATION_TRAJECTORY_SAMPLE_INTERVAL_SEC", "1.0")
        )
        self._nominal_step_sec = max(0.05, float(os.getenv("SIMULATION_UPDATE_INTERVAL_MS", "100")) / 1000.0)
        self._git_commit = _git_commit_hash()
        self._lock = threading.Lock()
        self._run: Optional[_ActiveRun] = None
        if self.enabled:
            self.output_root.mkdir(parents=True, exist_ok=True)

    # -- introspection --------------------------------------------------

    @property
    def active_run_id(self) -> Optional[str]:
        return self._run.run_id if self._run and not self._run.finalized else None

    @property
    def selected_agent_ids(self) -> set:
        return set(self._run.selected_agent_ids) if self._run and not self._run.finalized else set()

    def set_selected_agents(self, agent_ids: Iterable[str]) -> None:
        if self._run and not self._run.finalized:
            self._run.selected_agent_ids = {str(value) for value in agent_ids}

    # -- lifecycle hooks --------------------------------------------------

    def on_start(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._run and not self._run.finalized:
                self._finalize_locked("superseded_by_restart", status="completed")
            try:
                self._run = self._begin_run_locked()
            except Exception as exc:  # noqa: BLE001 - recorder failures must not crash the engine
                self._run = None
                _fallback_logger.exception("Failed to start simulation run recording: %s", exc)

    def on_pause(self) -> None:
        if not (self._run and not self._run.finalized):
            return
        with self._lock:
            run = self._run
            if not run or run.finalized:
                return
            try:
                run.pause_history.append({"paused_at_sim_time": round(self.engine.simulation_time, 3), "wall_time": _iso()})
                run.logger.info("Pause: simulation_time=%.3f", self.engine.simulation_time)
            except Exception as exc:  # noqa: BLE001
                self._mark_failure_locked(exc, "on_pause")

    def on_resume(self) -> None:
        if not (self._run and not self._run.finalized):
            return
        with self._lock:
            run = self._run
            if not run or run.finalized:
                return
            try:
                run.pause_history.append({"resumed_at_sim_time": round(self.engine.simulation_time, 3), "wall_time": _iso()})
                run.logger.info("Resume: simulation_time=%.3f", self.engine.simulation_time)
            except Exception as exc:  # noqa: BLE001
                self._mark_failure_locked(exc, "on_resume")

    def on_stop(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._run and not self._run.finalized:
                self._finalize_locked("user_stop", status="completed")

    def on_reset(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._run and not self._run.finalized:
                self._finalize_locked("user_reset", status="completed")

    def on_shutdown(self) -> None:
        """Best-effort flush on graceful process shutdown; does not finalize."""
        with self._lock:
            run = self._run
            if run and not run.finalized:
                try:
                    run.logger.info("Process shutdown while run active; leaving manifest.partial.json for incomplete detection.")
                except Exception:  # noqa: BLE001
                    pass
                run.close_streams()

    # -- per-step hooks --------------------------------------------------

    def on_step(self, entities: Dict[str, Dict], events: List[Dict], simulation_time: float) -> None:
        run = self._run
        if not run or run.finalized:
            return
        try:
            written_this_step: set = set()
            for event in events:
                self._record_risk_event(run, event, entities, simulation_time, written_this_step)
            for agent_id in run.selected_agent_ids:
                entity = entities.get(agent_id)
                if entity is not None and entity.get("active"):
                    self._write_trajectory_row(run, entity, simulation_time, "selected_agent", written_this_step)
            for entity in entities.values():
                if not entity.get("active"):
                    continue
                self._touch_agent(run, entity, simulation_time)
                agent_id = entity["id"]
                if agent_id in written_this_step:
                    continue
                last = run.last_trajectory_sample.get(agent_id, -math.inf)
                if simulation_time - last >= self.trajectory_sample_interval_sec:
                    self._write_trajectory_row(run, entity, simulation_time, "sampled", written_this_step)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._mark_failure_locked(exc, "on_step")

    def on_trip_completed(self, entity: Dict, simulation_time: float) -> None:
        run = self._run
        if not run or run.finalized:
            return
        try:
            self._touch_agent(run, entity, simulation_time)
            metrics = entity.get("metrics") or {}
            spawn_time = float(entity.get("spawn_time", 0.0))
            trip_start_time = float(entity.get("trip_start_time", 0.0))
            # True only for an agent's very first trip in the run, when the
            # initial population is deliberately spawned partway (0-78%)
            # along its route instead of at the true origin (see
            # SimulationEngine._spawn_entities) so agents don't all cluster
            # at t=0. For that one trip, trip_distance measures only the
            # remaining route segment, not the full origin->destination
            # distance -- exclude these rows before averaging trip_distance
            # by origin/destination pair.
            partial_initial_segment = bool(entity.get("spawned_mid_route")) and math.isclose(trip_start_time, spawn_time, abs_tol=1e-9)
            row = {
                "run_id": run.run_id, "agent_id": entity["id"], "agent_type": entity.get("type"),
                "trip_id": entity.get("trip_id"), "origin": entity.get("origin"), "destination": entity.get("destination"),
                "spawned_at": round(spawn_time, 3),
                "trip_start_time": round(trip_start_time, 3),
                "completed_at": round(float(simulation_time), 3),
                "travel_time": round(float(metrics.get("travel_time", 0.0)), 3),
                "waiting_time": round(float(metrics.get("waiting_time", 0.0)), 3),
                "trip_distance": round(float(metrics.get("trip_distance", 0.0)), 3),
                "partial_initial_segment": partial_initial_segment,
            }
            run.trip_writer.writerow(row)
            run.trip_file.flush()
            summary = run.agents.get(entity["id"])
            if summary is not None:
                summary.completed_trip_count += 1
                summary.travel_time_total += float(metrics.get("travel_time", 0.0))
                summary.waiting_time_total += float(metrics.get("waiting_time", 0.0))
                summary.trip_distance_total += float(metrics.get("trip_distance", 0.0))
                summary.hard_braking_count += int(metrics.get("hard_brake_count", 0))
            run.logger.info("Completed trip: agent_id=%s trip_id=%s simulation_time=%.3f", entity["id"], entity.get("trip_id"), simulation_time)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._mark_failure_locked(exc, "on_trip_completed")

    # -- internal: run creation --------------------------------------------------

    def _begin_run_locked(self) -> _ActiveRun:
        engine = self.engine
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        started = _now()
        run_dir_name = f"run_{started:%Y%m%d_%H%M%S}_{run_id.rsplit('_', 1)[-1][:8]}"
        run_dir = self.output_root / run_dir_name
        for suffix in range(1, 50):
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                run_dir = self.output_root / f"{run_dir_name}_{suffix}"
        else:  # pragma: no cover - defensive only
            raise RuntimeError("could not allocate a unique run directory")

        network_hash = _canonical_sha256(getattr(engine, "graph_payload", {}))
        config_hash = _canonical_sha256(self._config_payload())

        manifest = {
            "schema_version": "1.0",
            "run_id": run_id,
            "scenario_id": engine.scenario_name,
            "seed": engine.seed,
            "provider": self.provider_name,
            "network_mode": engine.network_runtime.get("mode"),
            "started_at": _iso(started),
            "finished_at": None,
            "duration_sec": None,
            "step_sec": self._nominal_step_sec,
            "step_sec_note": "nominal wall-clock update interval; this engine advances simulation_time in real time, not a fixed integration step",
            "simulation_version": SIMULATION_ENGINE_VERSION,
            "git_commit": self._git_commit,
            "recorder_schema_version": "1.0",
            "environment": {"python_version": sys.version.split()[0], "platform": sys.platform},
            "network_hash": network_hash,
            "config_hash": config_hash,
            "status": "running",
            "termination_reason": None,
            "pause_history": [],
            "recording_failure": None,
        }
        _write_json(run_dir / "manifest.partial.json", manifest)

        run = _ActiveRun(run_id, run_dir, manifest)
        run.logger.info(
            "Recorder initialized: run_id=%s scenario=%s seed=%s network_mode=%s",
            run_id, engine.scenario_name, engine.seed, engine.network_runtime.get("mode"),
        )
        run.logger.info("Run started: network_hash=%s config_hash=%s", network_hash, config_hash)
        run.logger.info("Risk writer initialized: %s", run_dir / "risk_events.jsonl")
        return run

    def _config_payload(self) -> Dict:
        engine = self.engine
        risk_config_path = engine.data_dir / "risk_config.json"
        behavior_config_path = Path(__file__).resolve().parent / "config" / "behavior_profiles.json"
        return {
            "scenario_id": engine.scenario_name,
            "scenario": engine.scenario,
            "risk_config": _read_json_if_exists(risk_config_path),
            "behavior_profiles": _read_json_if_exists(behavior_config_path),
            "fallback_cost_multiplier": getattr(engine.graph, "fallback_cost_multiplier", None),
            "simulation_engine_version": SIMULATION_ENGINE_VERSION,
            "nominal_step_sec": self._nominal_step_sec,
        }

    # -- internal: per-event recording --------------------------------------------------

    def _touch_agent(self, run: _ActiveRun, entity: Dict, simulation_time: float) -> _AgentSummary:
        agent_id = entity["id"]
        summary = run.agents.get(agent_id)
        if summary is None:
            summary = _AgentSummary(agent_id, entity.get("type", entity.get("agent_type", "unknown")), float(entity.get("spawn_time", simulation_time)))
            run.agents[agent_id] = summary
        return summary

    def _record_risk_event(self, run: _ActiveRun, event: Dict, entities: Dict[str, Dict], simulation_time: float, written_this_step: set) -> None:
        object_ids = list(event.get("object_ids") or ())
        agent_types = list(event.get("agent_types") or ())
        first = entities.get(object_ids[0]) if object_ids else None
        second = entities.get(object_ids[1]) if len(object_ids) > 1 else None
        x = y = None
        if first and second:
            x = round((float(first.get("x", 0.0)) + float(second.get("x", 0.0))) / 2, 3)
            y = round((float(first.get("z", 0.0)) + float(second.get("z", 0.0))) / 2, 3)
        elif first:
            x, y = round(float(first.get("x", 0.0)), 3), round(float(first.get("z", 0.0)), 3)
        row = {
            "run_id": run.run_id,
            "event_id": event.get("event_id"),
            "simulation_time": event.get("simulation_time", round(simulation_time, 2)),
            "event_type": event.get("safety_event"),
            "interaction_type": event.get("interaction_type"),
            "involved_agent_ids": object_ids,
            "involved_agent_types": agent_types,
            # x/y follow the engine's own 2D ground-plane convention: x is the
            # entity's "x", y is the entity's "z" (north); height ("y" in the
            # entity dict) is not part of this convention and is always ~0.
            "x": x, "y": y,
            "ttc": event.get("ttc"),
            "pet": event.get("pet"),
            "clearance": event.get("minimum_clearance"),
            "distance": event.get("distance"),
            "relative_speed": event.get("relative_speed"),
            "severity": event.get("risk_level"),
            "risk_score": event.get("risk_score"),
            "location_id": event.get("location_id"),
        }
        run.risk_file.write(json.dumps(_json_safe(row), ensure_ascii=False) + "\n")
        run.risk_file.flush()

        safety_event = str(event.get("safety_event") or "")
        for agent_id in object_ids:
            summary = run.agents.get(agent_id)
            entity = entities.get(agent_id)
            if summary is None and entity is not None:
                summary = self._touch_agent(run, entity, simulation_time)
            if summary is None:
                continue
            summary.risk_event_count += 1
            if safety_event == "NEAR_MISS":
                summary.near_miss_count += 1
            if safety_event == "COLLISION":
                summary.collision_count += 1
            if safety_event not in {"", "NONE"}:
                summary.conflict_count += 1
            if event.get("ttc") is not None:
                value = float(event["ttc"])
                summary.min_ttc = value if summary.min_ttc is None else min(summary.min_ttc, value)
            if event.get("minimum_clearance") is not None:
                value = float(event["minimum_clearance"])
                summary.min_clearance = value if summary.min_clearance is None else min(summary.min_clearance, value)
            if entity is not None and entity.get("active"):
                self._write_trajectory_row(run, entity, simulation_time, "risk_event", written_this_step)

    def _write_trajectory_row(self, run: _ActiveRun, entity: Dict, simulation_time: float, reason: str, written_this_step: set) -> None:
        agent_id = entity["id"]
        row = {
            "run_id": run.run_id,
            "simulation_time": round(float(simulation_time), 3),
            "agent_id": agent_id,
            "agent_type": entity.get("type"),
            "x": round(float(entity.get("x", 0.0)), 3),
            "y": round(float(entity.get("z", 0.0)), 3),
            "speed": round(float(entity.get("speed", 0.0)), 3),
            "heading": round(float(entity.get("heading", 0.0)), 2),
            "reason": reason,
        }
        run.trajectory_file.write(json.dumps(_json_safe(row), ensure_ascii=False) + "\n")
        written_this_step.add(agent_id)
        run.last_trajectory_sample[agent_id] = simulation_time

    # -- internal: failure isolation --------------------------------------------------

    def _mark_failure_locked(self, exc: Exception, where: str) -> None:
        run = self._run
        _fallback_logger.exception("Recorder failure in %s: %s", where, exc)
        if run is None:
            return
        run.recording_failed = True
        note = f"{where}: {type(exc).__name__}: {exc}"
        run.failure_notes.append(note)
        try:
            run.logger.error("Recorder failure in %s: %s", where, exc)
        except Exception:  # noqa: BLE001 - logging itself must never raise further
            pass

    # -- internal: finalize --------------------------------------------------

    def _finalize_locked(self, termination_reason: str, status: str) -> None:
        run = self._run
        if run is None or run.finalized:
            return
        engine = self.engine
        try:
            finished = _now()
            duration_sec = round(float(engine.simulation_time), 3)
            statistics = engine.statistics_manager.aggregate(engine.entities.values(), duration_sec)
            statistics = self._enrich_statistics(statistics)

            run.manifest.update({
                "finished_at": _iso(finished),
                "duration_sec": duration_sec,
                "status": status,
                "termination_reason": termination_reason,
                "pause_history": run.pause_history,
                "recording_failure": ({"notes": run.failure_notes} if run.recording_failed else None),
            })

            _write_json(run.run_dir / "simulation_statistics.partial.json", statistics)
            (run.run_dir / "simulation_statistics.partial.json").rename(run.run_dir / "simulation_statistics.json")

            self._write_agent_summary(run)

            run.logger.info("Recorder finalize started: termination_reason=%s", termination_reason)
            run.close_streams()

            _write_json(run.run_dir / "manifest.partial.json", run.manifest)
            (run.run_dir / "manifest.partial.json").rename(run.run_dir / "manifest.json")

            run.finalized = True
            _fallback_logger.info("Recorder finalize completed: run_id=%s termination_reason=%s", run.run_id, termination_reason)
        except Exception as exc:  # noqa: BLE001 - never let a recording failure break the engine
            _fallback_logger.exception("Recorder finalize failed for run_id=%s: %s", getattr(run, "run_id", "?"), exc)
            run.recording_failed = True
            run.failure_notes.append(f"finalize: {type(exc).__name__}: {exc}")
            try:
                run.close_streams()
            except Exception:  # noqa: BLE001
                pass
            # manifest.partial.json is intentionally left in place: its
            # continued presence (without manifest.json) is how downstream
            # tooling recognizes an incomplete/failed run.

    def _enrich_statistics(self, statistics: Dict) -> Dict:
        engine = self.engine
        counts = (engine.scenario or {}).get("counts", {}) or {}
        completed_total = int(statistics.get("completed_trip_count") or 0)
        spawned_total = sum(engine.statistics_manager.spawned_agents.values()) or 0
        risk_events = statistics.get("risk_events", {})

        def _ratio(numerator, denominator):
            return round(numerator / denominator, 4) if denominator else None

        def _pair_or_none(key: str, type_a: str, type_b: str):
            if int(counts.get(type_a, 0)) == 0 or int(counts.get(type_b, 0)) == 0:
                return None
            return risk_events.get(key, 0)

        average_travel_time = statistics.get("average_travel_time", {})

        def _avg_or_none(agent_type: str):
            if int(counts.get(agent_type, 0)) == 0 or not statistics.get("completed_trips", {}).get(agent_type):
                return None
            return average_travel_time.get(agent_type)

        return {
            "run_id": self._run.run_id if self._run else None,
            "safety": {
                "min_ttc": statistics.get("min_ttc"),
                "min_pet": statistics.get("min_pet"),
                "near_miss_count": statistics.get("near_miss_count"),
                "conflict_count": statistics.get("conflict_count"),
                "collision_count": statistics.get("collision_count"),
                "min_clearance": statistics.get("min_clearance"),
                "hard_braking_count": statistics.get("hard_braking_count"),
                "risk_exposure_time": statistics.get("risk_exposure_time"),
                "near_miss_per_completed_trip": _ratio(statistics.get("near_miss_count", 0), completed_total),
                "conflict_per_completed_trip": _ratio(statistics.get("conflict_count", 0), completed_total),
                "hard_braking_per_completed_trip": _ratio(statistics.get("hard_braking_count", 0), completed_total),
                "risk_exposure_per_agent": _ratio(statistics.get("risk_exposure_time", 0), spawned_total),
                "risk_events_by_pair": {
                    "car_person": _pair_or_none("car_person", "car", "person"),
                    "car_scooter": _pair_or_none("car_scooter", "car", "scooter"),
                    "person_scooter": _pair_or_none("person_scooter", "person", "scooter"),
                },
                "units": {"min_ttc": "sec", "min_pet": "sec", "min_clearance": "meter", "risk_exposure_time": "sec", "risk_exposure_per_agent": "sec"},
            },
            "mobility": {
                "avg_travel_time": statistics.get("avg_travel_time"),
                "avg_waiting_time": statistics.get("avg_waiting_time"),
                "completed_trips": statistics.get("completed_trip_count"),
                "throughput": statistics.get("throughput"),
                "car_avg_travel_time": _avg_or_none("car"),
                "scooter_avg_travel_time": _avg_or_none("scooter"),
                "pedestrian_avg_travel_time": _avg_or_none("person"),
                "units": {"avg_travel_time": "sec", "avg_waiting_time": "sec", "throughput": "trips / run duration"},
            },
        }

    def _write_agent_summary(self, run: _ActiveRun) -> None:
        active_ids = set(self.engine.entities.keys())
        partial_path = run.run_dir / "agent_summary.partial.csv"
        with open(partial_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=AGENT_SUMMARY_FIELDS)
            writer.writeheader()
            for agent_id, summary in run.agents.items():
                writer.writerow(summary.as_row(run.run_id, still_active=agent_id in active_ids))
        partial_path.rename(run.run_dir / "agent_summary.csv")


# ---------------------------------------------------------------------------
# Read-only listing/lookup helpers used by the API layer (main.py)
# ---------------------------------------------------------------------------

def list_run_dirs(output_root: Path) -> List[Path]:
    if not output_root.exists():
        return []
    return sorted(
        (path for path in output_root.iterdir() if path.is_dir() and RUN_DIR_PATTERN.match(path.name)),
        key=lambda path: path.name, reverse=True,
    )


def _manifest_for(run_dir: Path) -> Optional[Dict]:
    manifest = _read_json_if_exists(run_dir / "manifest.json")
    if manifest is not None:
        return manifest
    partial = _read_json_if_exists(run_dir / "manifest.partial.json")
    if partial is not None:
        partial = dict(partial)
        partial.setdefault("status", "incomplete")
    return partial


def list_runs(output_root: Path) -> List[Dict]:
    results = []
    for run_dir in list_run_dirs(output_root):
        manifest = _manifest_for(run_dir)
        if manifest is None:
            continue
        results.append({
            "run_id": manifest.get("run_id"),
            "scenario_id": manifest.get("scenario_id"),
            "seed": manifest.get("seed"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "status": manifest.get("status"),
            "termination_reason": manifest.get("termination_reason"),
        })
    return results


def resolve_run_dir(output_root: Path, run_id: str) -> Optional[Path]:
    """Safely map a run_id to its directory.

    ``run_id`` is validated against a strict pattern before any filesystem
    interaction, and every returned path is one already produced by
    ``output_root.iterdir()`` -- the caller-supplied string is never
    concatenated into a filesystem path, which rules out path traversal.
    """
    if not run_id or not RUN_ID_PATTERN.match(run_id):
        return None
    for run_dir in list_run_dirs(output_root):
        manifest = _manifest_for(run_dir)
        if manifest and manifest.get("run_id") == run_id:
            return run_dir
    return None


def read_run_detail(output_root: Path, run_id: str) -> Optional[Dict]:
    run_dir = resolve_run_dir(output_root, run_id)
    if run_dir is None:
        return None
    manifest = _manifest_for(run_dir) or {}
    statistics = _read_json_if_exists(run_dir / "simulation_statistics.json") or _read_json_if_exists(run_dir / "simulation_statistics.partial.json")
    return {"manifest": manifest, "statistics": statistics}


def build_run_zip(run_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(run_dir)))
    return buffer.getvalue()
