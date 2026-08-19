# 캠퍼스 OD 교통 시뮬레이션 구현 보고서

## 1. 기존 왕복 이동이 발생했던 원인

`build_routes_from_road_zones.py`가 모든 도로 중심선을 `[A, B, A]`로 만들고 `loop=true`를 기록했다. 기존 `simulation_engine.py`는 `route_distance %= total_length`를 사용했으며, non-loop 경로도 끝에서 `route_distance=0`으로 되돌렸다. 목적지 도착이나 객체 lifecycle이 없었으므로 A→B→A가 영구 반복됐다. 상세 분석은 `SIMULATION_MOVEMENT_ANALYSIS.md`에 기록했다.

## 2. 변경한 이동 시스템

기존 API와 R3F Canvas 연결은 유지하면서 내부 이동을 `OD 선택 → 타입별 최단 경로 → 가감속 이동 → 도착 → 체류/제거 → 다음 Trip`으로 변경했다. 원본 `routes.geojson`도 `[A,B]`, `loop=false`로 재생성하여 데이터 자체의 왕복 구간을 제거했다.

객체가 도로 조각 끝에 도착해도 좌표를 0으로 wrap하지 않는다. 내부 POI이면 숨김 상태로 체류하고, 외부 POI이면 despawn한 뒤 demand에 따라 새 ID의 Agent가 들어온다.

## 3. Origin-Destination 구조

모든 Agent payload에는 `agent_id`, `agent_type`, `trip_id`, `origin`, `destination`, `current_route`, `current_segment`, `current_position`, `previous_position`, `speed`, `heading`, `trip_status`, `spawn_time`, `arrival_time`, `dwell_time`, `behavior_profile`이 포함된다.

`od_demand.json`은 08:00~10:00 등교, 11:30~13:30 점심, 16:00~19:00 하교, 일반 주간 profile을 제공한다. `rush_hour`, `lunch_time`, `leaving_campus`는 해당 profile을 강제로 선택하고 `class_change`는 건물 간 이동 수요를 사용한다.

## 4. Route Graph 구조

`mobility_graph.json`은 106 Node, 364 Edge, 14 POI로 생성된다. Edge는 `road`, `shared_path_derived`, `crosswalk`, `building_entrance`, `gate_vehicle`, `pedestrian_gate`, `parking_connection`, `parking_walk`, `scooter_parking` 등으로 구분된다.

`mobility_graph.py`의 dependency-free Dijkstra가 Agent 타입별 `allowed_types`를 필터링한다. 자동차는 보행 전용·건물 출입구 Edge를 사용할 수 없고, 보행자는 vehicle road/gate를 사용할 수 없다. 킥보드는 현재 정책상 road/shared/crosswalk/building entrance/scooter parking을 사용할 수 있다.

## 5. 건물/외부 이동 구현

기존 `common_elemetns.json`의 실제 ID를 우선 사용했다: 공과대학 1·2·3호관 `BLD_D2/D3/D4`, 도서관 `BLD_C1`, 학생회관 `BLD_E1`, 대학본부 `BLD_A1`.

건물 중심은 목적지가 아니다. GLB의 알려진 건물 위치를 시뮬레이션 좌표로 역변환하고 가장 가까운 접근 Edge에 snap한 `ENT_*_MAIN`을 사용한다. 자동차 목적지는 건물 입구가 아니라 `PARKING_A/B`다. `GATE_MAIN/BACK`, `EXTERNAL_MAIN_ROAD_SOUTH`, `EXTERNAL_BACK_GATE`도 graph에 연결했다.

대표 실행:

- Person: `EXTERNAL_MAIN_ROAD_SOUTH → BLD_D4`, `BLD_D4 → BLD_C1`, `BLD_C1 → BLD_E1`, `BLD_E1 → EXTERNAL_MAIN_ROAD_SOUTH`
- Car: `EXTERNAL_MAIN_ROAD_SOUTH → PARKING_A`, 주차 체류 후 `PARKING_A → EXTERNAL_MAIN_ROAD_SOUTH → DESPAWNED`
- Scooter: `EXTERNAL_MAIN_ROAD_SOUTH → BLD_D4`, `BLD_E1 → BLD_C1`, `BLD_C1 → SCOOTER_PARKING_01`

## 6. 자동차 이동 규칙

- road/vehicle gate/parking connection만 route에 사용
- 앞차의 진행 방향 투영 거리와 lateral gap으로 following speed 제한
- 교차로/큰 회전 전 감속, speed limit 적용
- 횡단 보행자와 예상 교차 경로가 있으면 제동
- 킥보드 접근·진로 교차 시 거리에 비례해 제동
- acceleration/deceleration 제한과 `BRAKING/CONFLICT` 상태 기록
- 외부→주차장→체류→외부 lifecycle

## 7. 보행자 이동 규칙

- shared path/crosswalk/building entrance/pedestrian gate 사용
- `WALKING`, `WAITING_CROSSWALK`, `CROSSING`, `JAYWALKING`, `ENTERING_BUILDING`, `LEAVING_BUILDING`, `DWELLING` 상태 제공
- 신호가 적색이면 횡단보도 대기(무단횡단 scenario 제외)
- 가까운 보행자와 겹치지 않도록 separation speed constraint
- 건물 도착 시 유형별 dwell 후 기존 출발지와 다른 다음 목적지 선택

## 8. 킥보드 이동 규칙

- road/shared/crosswalk/허용 entrance/scooter parking 사용
- 횡단보도와 큰 회전에서 감속
- 보행자 접근 시 감속·회피, 차량과 예상 경로가 교차하면 감속
- 우천/강풍 감속, 과속·역방향 scenario 및 metric 지원
- 건물 또는 킥보드 주차 지점에서 dwell 후 다음 Trip

## 9. 객체 간 Interaction 구현

- Car→Crosswalk + Person→Crosswalk: 보행자 `CROSSING` 또는 예상 경로 교차 시 Car target speed 감소/정지
- Car↔Scooter 교차: 두 velocity ray의 교차점과 도착 시간 차이를 계산하고 Car braking, Scooter avoiding 적용
- Scooter→Person: 거리·접근 여부에 따라 Scooter 감속, 충돌 예상 시 conflict
- Car behind Car: 같은 heading의 전방/측방 투영으로 minimum gap과 선행차 속도를 반영

Interaction state는 `NONE`, `APPROACHING`, `FOLLOWING`, `CROSSING`, `CONFLICT`, `BRAKING`, `AVOIDING`이다.

## 10. Risk Engine 변경사항

거리만으로 위험을 만들지 않도록 접근 여부 또는 예상 경로 교차를 요구한다. distance, relative velocity, approaching, predicted path intersection, TTC, predicted minimum distance를 계산한다.

이벤트는 `COLLISION`, `NEAR_MISS`, `TRAFFIC_CONFLICT`, `UNSAFE_CROSSING`, `SUDDEN_BRAKING`, `VEHICLE_YIELDING`, `SCOOTER_YIELDING`을 기록한다. 임계값은 `risk_config.json`의 프로젝트 가정이며 논문 parameter 복제가 아니다.

## 11. 논문별 실제 적용 내용

`RESEARCH_TO_IMPLEMENTATION.md`에 원문 링크, 확인된 개념, 구현 파일, 확인하지 않은 수치를 복제하지 않았다는 범위를 기록했다.

- Vehicle–Scooter framework: interaction/crossing/following/braking 개념
- SUMO: microscopic entity와 provider/TraCI 교체 경계
- Vehicle–Scooter risk: 사용자 요청 개념에 따른 상대운동/TTC/conflict 분류, parameter 복제 주장 없음
- Pedestrian safety framework: collision뿐 아니라 conflict와 pedestrian characteristics를 포함하는 평가 개념
- CityFlow: 개별 Agent timestep 관리, car-following constraint, agent metric/trajectory 개념

## 12. 수정 파일

- `backend/build_routes_from_road_zones.py`
- `backend/simulation/simulation_engine.py`
- `backend/simulation/risk_engine.py`
- `backend/simulation/main.py`
- `backend/simulation/traci_adapter.py`
- `backend/simulation/data/routes.geojson`
- `backend/simulation/data/risk_config.json`
- `backend/simulation/data/sample_scenario.json`
- `backend/simulation/README.md`
- `backend/tests/test_route_manager.py`
- `backend/tests/test_simulation_api.py`
- `frontend/src/simulation/components/TrafficEntity.jsx`
- `frontend/src/simulation/components/TrafficSimulationLayer.jsx`
- `frontend/src/simulation/components/TrafficSafetyPanel.jsx`
- `frontend/src/simulation/components/ScooterEntity.jsx`
- `frontend/src/simulation/stores/simulationStoreCore.mjs`
- `frontend/src/simulation/stores/simulationStoreCore.test.mjs`
- `TRAFFIC_SIMULATION_INTEGRATION.md`

## 13. 신규 파일

- `SIMULATION_MOVEMENT_ANALYSIS.md`
- `RESEARCH_TO_IMPLEMENTATION.md`
- `LOCAL_RUN_MAC.md`
- `SIMULATION_IMPLEMENTATION_REPORT.md`
- `backend/build_mobility_data.py`
- `backend/simulation/mobility_graph.py`
- `backend/simulation/od_manager.py`
- `backend/simulation/trip_manager.py`
- `backend/simulation/interaction_manager.py`
- `backend/simulation/statistics_manager.py`
- `backend/simulation/providers/{base_provider,internal_provider,sumo_provider}.py`
- `backend/simulation/data/mobility_graph.json`
- `backend/simulation/data/nodes.geojson`
- `backend/simulation/data/building_entrances.json`
- `backend/simulation/data/od_demand.json`
- `backend/tests/test_od_mobility.py`
- `frontend/src/simulation/components/AgentTrajectory.jsx`

## 14. 테스트 결과

- Route validator: 92 non-loop 중심선 통과, loop/return geometry 0개
- Python: 21개 테스트 통과
- 대표 OD 9개 타입 제한 Dijkstra 경로 통과
- Interaction 4종(car-person, car-scooter, scooter-person, car-following) 통과
- Frontend Node tests와 Vitest 통과
- Legacy production build 통과
- VWorld production build 통과
- 로컬 브라우저: WebSocket 연결, 실행 상태/집계 갱신, `person_011` 선택 상세 및 trajectory Line 확인

기상 API를 실행하지 않은 브라우저 smoke test에서는 기존 선택형 날씨 fetch 오류만 표시됐고 Simulation API/WebSocket 및 Agent 상세 호출은 정상 동작했다.

## 15. 현재 임시 데이터

- 도로 중심선은 팀 도로 폴리곤의 principal axis를 자른 derived geometry다.
- 보행로는 원본 geometry 부재로 도로 구역 연결을 따라 만든 `shared_path_derived`다.
- 건물 출입구는 GLB 건물 center hint를 가장 가까운 접근 Edge에 snap한 값이다.
- OD weight, dwell, risk threshold는 실측/논문 복제값이 아닌 조정 가능한 demo/calibration 기본값이다.
- 주차장·게이트 외부 연결도 현재 폴리곤/GLB 기반의 이식용 파생값이다.

## 16. 실제 캠퍼스 데이터로 교체해야 하는 부분

1. 측량된 road lane, sidewalk, bike/scooter lane, crosswalk centerline
2. 실제 건물별 출입구 좌표와 allowed types
3. 주차장 입출구, drop-off, 정문/후문 외부 도로 연결
4. 방향성·차선 수·우선권·신호 phase
5. 시간표/출입·주차 계수 기반 OD 수요와 dwell calibration
6. 관측 trajectory/conflict 자료에 근거한 risk threshold 검증

교체 후 `build_mobility_data.py`의 파생 graph 대신 같은 JSON 계약으로 authored graph를 제공하면 엔진과 프런트는 유지된다.

## 17. 향후 SUMO 적용 방법

`SIMULATION_PROVIDER=sumo`로 provider를 선택하는 계약은 유지했다. 실제 적용에는 캠퍼스 graph를 SUMO `.net.xml`로 변환하고, OD 수요를 route/trip 파일로 만들고, `SUMO_CONFIG_PATH`를 지정한다. `sumo_provider.py`에서 TraCI vehicle/person API를 공통 Entity payload(`id/type/x/z/speed/heading/trip_status/risk`)로 매핑하고, 필요하면 Internal Risk/Statistics adapter에 같은 snapshot을 전달한다. WebSocket과 R3F frontend 계약은 변경하지 않는다.

