# Research to Implementation Mapping

## Claim policy

This project distinguishes `concept_inspired_by_previous_work`, `implementation_specific_parameter`, `experimentally_calibrated_parameter`, and `observed_campus_parameter`. Current behavior/risk thresholds are implementation-specific. No unverified number is attributed to a paper.

## Simulation Framework for Vehicle and Electric Scooter Interaction

Source: [arXiv 2402.01104](https://arxiv.org/abs/2402.01104)

Concept inspired by previous work:

- Vehicle–scooter following, approaching, crossing and conflict.
- Predicted route intersection, braking and avoidance response.

Implementation: `interaction_manager.py`, `risk_engine.py`, `simulation_engine.py`. Project thresholds are not claimed as paper parameters.

## Microscopic Traffic Simulation using SUMO

Source: [DLR publication record](https://elib.dlr.de/127994/)

Concept inspired by previous work:

- Individual microscopic entities and intermodal networks.
- External simulator coupling and future model validation.
- Internal/SUMO provider boundary and TraCI exchange.

Implementation: `providers/`, `traci_adapter.py`, `tools/prepare_sumo.py`, `SUMO_INTEGRATION.md`.

SUMO was not installed or run in this work environment. A provider contract and authoritative-only generator exist; actual SUMO validation remains pending.

## Risk Analysis in Vehicle and Electric Scooter Interaction

Source: [IEEE DOI 10.1109/IV55156.2024.10588413](https://doi.org/10.1109/IV55156.2024.10588413)

The full parameter tables were not verified here. Applied only as a conceptual reference:

- Relative motion, TTC, minimum predicted distance, predicted conflict point and interaction classification.
- Required deceleration and raw metric retention are project implementations.

Implementation: `risk_engine.py`, `interaction_manager.py`, `conflict_area.py`, `risk_config.json`.

## Evaluation of Pedestrian Safety in a High-Fidelity Simulation Environment Framework

Source: [arXiv 2210.08731](https://arxiv.org/abs/2210.08731)

Concept inspired by previous work:

- Pedestrian conflict and crossing safety beyond collision-only evaluation.
- Near miss, unsafe crossing, yielding and sudden braking event taxonomy.

Implementation: `risk_engine.py`, `statistics_manager.py`, Crosswalk Conflict Areas and replay/timeline endpoints.

## CityFlow

Sources: [arXiv 1905.05217](https://arxiv.org/abs/1905.05217), [ACM DOI](https://doi.org/10.1145/3308558.3314139)

Concept inspired by previous work:

- Individual Agent management and scalable Agent-level evaluation.
- Per-Agent trajectory and performance/safety metrics.

CityFlow is not used as the simulation engine, and its code/equations were not copied. Implementation: `simulation_engine.py`, `statistics_manager.py`, selected-Agent and trajectory UI.
