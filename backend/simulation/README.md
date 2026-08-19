# Simulation API

이 합본의 기본 `data/routes.geojson`은 임시 데모가 아니라 팀원 버전의
`road_zones_wgs84.geojson` 92개 도로 영역에서 생성한 로컬 미터 중심선입니다.
재생성 방법과 좌표 연결 근거는 저장소 루트의
`TRAFFIC_SIMULATION_INTEGRATION.md`를 참고하세요.

SUMO 없이 동작하는 순천대학교 캠퍼스 OD/Graph 시뮬레이터입니다. 자동차, 보행자, 킥보드는 Origin과 Destination을 가진 Trip으로 이동하고, 도착·체류·다음 Trip·외부 제거 lifecycle을 거칩니다. 거리/TTC/예상 진행선 교차 기반 위험 이벤트를 WebSocket으로 보냅니다.

## 실행

```bash
cd backend
python3 -m venv .venv-simulation
source .venv-simulation/bin/activate
python -m pip install -r simulation/requirements.txt
python -m uvicorn simulation.main:app --reload --port 8002
```

기본 업데이트 주기는 100ms이며 `SIMULATION_UPDATE_INTERVAL_MS=200`처럼 변경할 수 있습니다. 최초 WebSocket 연결은 전체 Snapshot을, 이후 tick은 Agent ID 기반 compact delta를 보냅니다. Weather API가 없으면 기본 맑은 날씨로 계속 실행합니다.

```env
SIMULATION_PROVIDER=internal
SIMULATION_SEED=42
WEATHER_API_URL=http://127.0.0.1:8000
```

`SIMULATION_SEED`는 한 번 실행되는 현재 시뮬레이션의 재현을 위한 단일 정수입니다.

## API

- `GET /health`
- `GET /api/simulation/status`
- `POST /api/simulation/start`, `/pause`, `/resume`, `/reset`
- `POST /api/simulation/speed`
- `POST /api/simulation/scenario`
- `POST /api/simulation/selection` (Run Recorder에 trajectory를 매 스텝 기록할 Agent ID 목록 전달)
- `GET /api/simulation/entities`, `/events`, `/statistics`
- `GET /api/simulation/agents/{agent_id}` (개별 metrics와 최근 trajectory)
- `GET /api/simulation/runs`, `/runs/{run_id}`, `/runs/{run_id}/download` (기록된 Run 조회/다운로드, read-only)
- `WS /ws/simulation`

## Run Recorder

사용자가 `/api/simulation/start`로 Simulation을 시작할 때마다 `SimulationRunRecorder`(`run_recorder.py`)가 독립된 Run을 자동으로 기록합니다. Pause/Resume은 같은 Run을 유지하고, Reset/Stop은 해당 Run을 `completed`로 확정합니다. 결과는 기본적으로 저장소 루트의 `simulation_output/run_<timestamp>_<id>/`에 저장됩니다.

```env
SIMULATION_RECORDING_ENABLED=true
SIMULATION_RUN_OUTPUT_DIR=../simulation_output
SIMULATION_TRAJECTORY_SAMPLE_INTERVAL_SEC=1.0
```

Run 디렉터리 구성: `manifest.json`, `simulation_statistics.json`, `risk_events.jsonl`(전체 Risk Event, UI의 최근 500개 메모리와 별개), `completed_trips.csv`, `agent_summary.csv`, `trajectory.jsonl`(선택/Risk Event/다운샘플 Agent), `simulation.log`. 비정상 종료 시 `manifest.partial.json`만 남아 미완료 Run을 구분할 수 있습니다. Recorder는 TTC/PET/Risk 판정을 다시 계산하지 않고 `statistics_manager`/`risk_engine`이 이미 계산한 값만 기록하므로, Recorder를 껐다 켜도 Simulation 결과 자체는 달라지지 않습니다.

`completed_trips.csv`의 `partial_initial_segment` 컬럼에 주의하세요: Simulation 시작 시 초기 인구는 t=0에 모두 origin에 몰리지 않도록 경로의 0~78% 지점에 분산 배치됩니다. 그 결과 각 Agent의 **첫 Trip만** `trip_distance`가 실제 origin→destination 거리보다 짧게 기록됩니다(재현 경로 자체가 아니라 기록 대상 구간이 짧은 것). origin/destination별 평균 trip_distance를 계산할 때는 `partial_initial_segment=True`인 행을 제외하는 것을 권장합니다.

### 결과 근거 검증 (Evidence validation)

```bash
python -m simulation.tools.validate_run_evidence simulation_output/run_xxx --graph simulation/data/mobility_graph.json
```

Run 디렉터리 안 파일들이 서로 내부적으로 일관적인지(예: `risk_events.jsonl` 줄 수 == `simulation_statistics.json`의 `conflict_count`, `completed_trips.csv` 행 수 == `mobility.completed_trips` 등)와 물리적으로 타당한지(음수/0 소요시간 없음, 시간 순서 위반 없음, 비현실적 속도 없음, 경로 길이가 직선거리보다 짧지 않음)를 점검합니다. TTC/PET 공식 자체의 정확성은 `tests/test_risk_engine.py`·`tests/test_pet.py`가, Recorder가 그 값을 왜곡 없이 저장하는지는 `tests/test_run_recorder_evidence.py`가 검증합니다.

재현성: 동일 seed + 동일 시나리오 + 동일 step(dt) 스케줄로 실행하면 `simulation_statistics.json`·`completed_trips.csv`가 정확히 재현됩니다(`test_same_seed_and_fixed_dt_schedule_reproduces_statistics_exactly`). 다만 이 엔진은 실시간(wall-clock) 루프이므로, 동일 `SIMULATION_SEED`라도 실제 UI에서 두 번 실행하면 매 tick의 dt가 실행마다 달라져 동일한 RNG 호출 순서를 보장하지 않습니다(`test_different_step_schedule_breaks_reproducibility_even_with_same_seed`가 이 한계를 문서화). 엄격한 재현이 필요하면 고정 dt로 스크립트에서 `engine.step(dt)`를 직접 호출하십시오.

## 좌표 데이터 주의

기본 `data/routes.geojson`은 팀의 WGS84 도로 폴리곤에서 D4 기준 로컬 미터로 변환한 파생 중심선입니다. 원본 데이터에는 작성된 중심선과 보행로 geometry가 없으므로, 실제 측량 중심선이 제공되면 같은 LineString 계약으로 교체하는 것이 더 정확합니다. 신호 위치는 선택형 `data/traffic_lights.json`에서 관리합니다.

## SUMO

TraCI를 설치한 뒤 다음 변수를 지정하면 `SumoSimulationProvider`를 선택합니다. TraCI가 없으면 import 오류 없이 내부 provider로 fallback합니다.

```env
SIMULATION_PROVIDER=sumo
SUMO_BINARY=sumo
SUMO_CONFIG_PATH=simulation/sumo/campus.sumocfg
```
