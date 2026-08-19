# Simulation Cleanup Audit

## Scope and method

The repository was searched across Python, JavaScript/JSX, JSON, YAML, shell scripts, and Markdown for `experiment`, `batch`, multi-run loops, seed lists, aggregation, confidence intervals, result folders, and scenario comparison commands. Each candidate was classified by whether it participates in live simulation, OD/trip/graph routing, risk, Three.js, SUMO, or network authoring.

## Repeated-run layer found before cleanup

- `backend/experiments/`: 32 EXP1–EXP5 condition files, defaults, assumption manifests, validation output, six command wrappers, and a results tree.
- `backend/simulation/experiments/`: generic repeated scenario runner, EXP01 condition runner, exploratory runner, seed-set loader, merge/paired comparison, cross-run statistics, smoke runner, preflight, and result writers.
- Tests: `test_exp_suite.py`, `test_research_pipeline.py`, and `test_scenario_runner.py` directly imported the repeated-run package.
- Documents: `README_EXPERIMENTS.md`, `RESEARCH_EXPERIMENT_PIPELINE.md`, and `SIMULATION_EXPERIMENT_GUIDE.md` documented seed batches and aggregate output.
- Core hooks added only for conditions: scenario overrides, forced OD profile/coverage mix, policy-specific edge filters, speed/crosswalk condition overrides, and an unbounded full-run event list.

## Preserved after review

- `ScenarioManager`: selects one live scenario.
- Single `SIMULATION_SEED`: deterministic debugging only; no seed iteration exists.
- `StatisticsManager`: live/current-run safety and mobility counters.
- `calibration.py` and `compare_sumo_ssm.py`: provider/observation validation, not automatic scenario batches.
- Network validator, route digitizer, Internal Provider, SUMO/TraCI Provider, Risk Engine, OD/Trip/Graph, and selected-Agent trajectory.
- Energy-domain files containing words such as scenario or comparison: unrelated to traffic repeated-run execution.

## Frontend audit

The traffic UI contained no run-count, seed, batch progress, confidence interval, aggregate result, or experiment download controls. The existing Start/Pause/Resume/Reset, speed, scenario, counts, Agent detail, timeline, trajectory, and risk panels are live-simulation features and were retained.

## Dependency audit

No SciPy, statsmodels, joblib, tqdm, CSV-export, or experiment-only chart dependency was present. FastAPI, Uvicorn, Pydantic, HTTPX, pytest, React, Three.js, React Three Fiber, Drei, and existing UI dependencies remain used by runtime or tests.
