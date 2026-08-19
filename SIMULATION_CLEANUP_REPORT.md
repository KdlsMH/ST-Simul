# Simulation Cleanup Report

## 1. 삭제한 반복 실험 기능

Traffic repeated-run layer, EXP1–EXP5 condition generation, 30-seed iteration, resume/force runners, exploratory/research condition runners, cross-run summaries, confidence intervals, merge/paired comparison, result manifests, and generated result trees were removed. A single deterministic `SIMULATION_SEED` remains only for reproducing one live Internal simulation.

## 2. 삭제한 파일

- Entire `backend/experiments/` tree: 32 condition JSON files, defaults/profiles, manifests, validation output, assumption report, six CLI wrappers, and results directory.
- Entire `backend/simulation/experiments/` tree: `run.py`, `run_condition.py`, `run_exploratory_condition.py`, `exp_suite.py`, `merge.py`, `compare.py`, `condition.py`, `research_preflight.py`, `smoke_test.py`, configs, seed set, caches, and result directories.
- Dedicated documents: `README_EXPERIMENTS.md`, `RESEARCH_EXPERIMENT_PIPELINE.md`, `SIMULATION_EXPERIMENT_GUIDE.md`.
- Dedicated tests: `test_exp_suite.py`, `test_research_pipeline.py`, `test_scenario_runner.py`.
- Unused frontend backups/rewrite utilities: `App.jsx.bak`, `App_backup.jsx`, `fix_city.py`, `update_app.py`, `update_city.py`, `update_solar.py`.

## 3. 수정한 파일

Core changes are in `simulation_engine.py`, `statistics_manager.py`, `risk_engine.py`, `interaction_manager.py` (retained spatial grid), `mobility_graph.py`, `trip_manager.py`, `od_manager.py`, `behavior_manager.py`, `runtime_network.py`, `main.py`, and `providers/internal_provider.py`. Frontend changes are in the simulation store/socket rendering path, Traffic entities, coordinate transform, and Safety panel. Runtime/network/risk/SUMO documents and tests were updated; `backend/pytest.ini` was added.

## 4. 제거한 API

No traffic experiment HTTP endpoints existed, so no live endpoint was removed. The retained API is health, status, Start/Pause/Resume/Reset, speed, scenario, entities, Agent detail, events, timeline, statistics, network/quality, and `/ws/simulation`.

## 5. 제거한 Config

All EXP/condition/seed-set/default-assumption files under the two removed experiment trees were deleted. `sample_scenario.json`, OD demand, mobility policy, behavior profiles, risk config, network, conflict areas, coordinate transform, traffic lights, and SUMO config remain.

## 6. 제거한 Tests

Only tests importing repeated-run packages were removed. Route, graph, OD, lifecycle, movement, interaction, car-following, crosswalk, TTC, PET, near miss, hard braking, statistics, API/WebSocket, controls, network, and SUMO fallback tests remain. New coverage verifies bounded event memory and compact entity delta merging.

## 7. 제거한 Dependencies

No dependency was exclusive to the removed traffic layer. Therefore no runtime/test package was removed speculatively. npm reports five existing dependency-tree advisories; forced upgrades were not applied because they may be breaking.

## 8. 제거한 Frontend 기능

There was no traffic Batch/Run-count/seed/aggregate UI to remove. Live Scenario, counts, speed, controls, Agent selection/detail, trajectory, timeline, risk events, route digitizer, and network debug tools remain. Unused backup and rewrite files were removed.

## 9. Backend 최적화 내용

- The FastAPI lifespan owns one asynchronous simulation task; request handlers do not run the tick loop.
- Scenario reconfiguration resets time, risk, conflict-area, entities, and live statistics consistently.
- Single-run counters retain safety/mobility totals without holding all event records.
- Despawn releases live trajectory state; completed Trip totals stay in scalar counters.
- Important lifecycle actions use normal logging; per-tick updates do not log.

## 10. Frontend 최적화 내용

- Store state maintains `Map<agentId, state>` plus a stable entity list.
- Compact deltas merge by Agent ID and remove despawned IDs.
- Three.js Agent Object3D instances remain keyed by Agent ID; transforms update in `useFrame`.
- Per-frame position interpolation reuses a `Vector3` rather than allocating one each frame.
- Existing memoized Agent/model components remain in place; no duplicate Agent GLB loading exists.

## 11. Risk Engine 최적화

Uniform spatial grids remain the broad phase. For distant pairs, relative motion and reachable distance are checked before route-swept-envelope calculations. Unsupported pair types and diverging/unreachable pairs exit early. RiskEngine retains only the configured recent-event deque; StatisticsManager stores scalar totals and a bounded 500-event UI buffer.

## 12. Route/Graph 최적화

Routes are still calculated only on Trip creation/destination change. Ordinary movement follows the assigned path. Deterministic shortest paths without per-trip random edge factors use an Origin/Destination/Agent-type cache; randomized route-diversity paths keep their existing behavior. The graph/network is loaded and validated once when the Provider is created.

## 13. WebSocket 최적화

Connection starts with `simulation_update` full snapshot. Subsequent ticks send `simulation_delta` with changed entity fields, removed IDs, new risk events, and current statistics/signals/timeline. In the matched 160-Agent benchmark, serialized traffic payload decreased from 369,679 bytes per full update to 42,758 bytes for the measured steady delta (about 88.4% smaller; actual size varies with state changes).

## 14. 최종 Architecture

`Campus Network → Provider (Internal or SUMO/TraCI) → OD/Trip/Graph → Car/Person/Scooter → spatial interaction → Risk Engine → FastAPI/WebSocket → React Three Fiber/Three.js`. There is no traffic repeated-run layer between these components. See `SIMULATION_ARCHITECTURE.md`.

## 15. 실행 방법

Backend: `cd backend`, install `simulation/requirements.txt`, then `python -m uvicorn simulation.main:app --reload --port 8002`. Frontend: `cd frontend`, `npm install`, then `npm run dev:legacy`. After dependencies exist, `scripts/start_simulation.ps1` starts both development services.

## 16. 테스트 결과

- `python -m compileall simulation tests`: PASS.
- Python pytest: **44 passed**, one upstream FastAPI/TestClient deprecation warning.
- Network validator: **0 errors, 8 warnings**; all 364 edges are still derived and none authoritative.
- Frontend Node tests: **141 passed**.
- Frontend Vitest JSX tests: **55 passed** across 11 files.
- Legacy production build: PASS; VWorld production build: PASS.
- Both builds warn about chunks over 500 kB; this is recorded rather than hidden.

## 17. 성능 확인 결과

Matched local benchmark, 30 Car + 100 Person + 30 Scooter, 20 ticks after warm-up:

| Metric | Before | After |
| --- | ---: | ---: |
| Average simulation tick | 110.96 ms | 51.30 ms |
| WebSocket traffic payload | 369,679 B full snapshot | 42,758 B steady delta |
| Python tracked current allocation over 5 ticks | 524,832 B | 503,078 B |
| Python tracked peak allocation over 5 ticks | 699,504 B | 677,222 B |

Tracked allocation is `tracemalloc` scope, not total process RSS. Browser FPS, React render count, and average CPU usage were not measured in a real browser and are not claimed.

An additional 500-Agent check (100/300/100) spawned in 0.94 s and completed three ticks, but tick time was 397.8–417.6 ms. It is functional, not validated for a 100 ms real-time update target.

## 18. 남아 있는 Known Issues

- Network validation warnings remain because geometry is derived, with no authoritative edges. The 3.0 m crosswalk width is assumed rather than surveyed.
- SUMO/TraCI structure and fallback tests pass, but SUMO cannot run until a real `campus.net.xml`, executable, and TraCI are available.
- Legacy and VWorld bundles contain chunks over 500 kB; future route-level code splitting is advisable.
- npm reports five dependency advisories (1 low, 1 moderate, 3 high); compatibility-safe remediation needs separate review.
- 500-Agent scale exceeds the current 100 ms tick target on the measured machine.
