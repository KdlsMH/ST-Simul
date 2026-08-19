# 기존 교통 시뮬레이션 이동 분석

## 분석 범위

- 백엔드: `backend/simulation`, 경로 생성기, WebSocket/API, 위험 계산, 시나리오 및 테스트
- 프런트엔드: `frontend/src/simulation`, Legacy Campus Canvas 연결부와 좌표 변환
- 공간 데이터: 팀 도로 구역 GeoJSON, `common_elemetns.json`, 캠퍼스 GLB의 알려진 건물 ID

이 문서는 OD/Trip 구조를 적용하기 전 코드의 동작을 기준으로 작성했다.

## 왜 객체가 짧은 길을 왕복하는가

원인은 렌더링 보간이 아니라 경로 데이터 생성과 엔진의 종료 처리 조합이다.

1. `backend/build_routes_from_road_zones.py`는 각 도로 폴리곤의 장축을 잘라 시작점 A와 끝점 B를 계산한다.
2. 생성 좌표를 `[A, B, A]`로 저장한다.
3. 같은 Feature에 `loop: true`를 지정한다.
4. `simulation_engine.py`는 매 프레임 `route_distance += speed * dt`로 이동시키고, loop 경로에서는 `route_distance %= route.total_length`를 수행한다.
5. 따라서 실제 재생 순서는 `A → B → A → B → A ...`이며, 화면에서는 짧은 도로 조각을 계속 앞뒤로 다니는 것으로 보인다.
6. loop가 아닌 경로도 끝에 도착하면 기존 코드는 `route_distance = 0.0`으로 즉시 되돌린다. 즉 `loop=false`만으로는 문제가 해결되지 않는다.

기존 엔진에는 목적지 도착, 체류, 다음 목적지 선택, 외부 도착 시 제거라는 lifecycle이 없었다. `origin`, `destination`, `trip_id`, `arrival_time`, `dwell_time`도 없으므로 경로 끝은 Trip 종료가 아니라 단순 좌표 래핑 지점이었다.

## 기존 객체 생성과 이동

- `configure()`가 시나리오별 고정 객체 수를 읽고 모든 객체를 한 번에 다시 만든다.
- 타입별 `allowed_types`가 맞는 단일 LineString을 순환 할당한다.
- 시작 위치는 해당 LineString 위의 임의 progress다.
- 목적지는 없고, 객체 제거·수요 기반 재생성도 없다.
- 자동차·보행자·킥보드는 속도 범위만 다르고 동일한 단일 경로 진행 모델을 사용한다.
- `wrong_way` 킥보드는 진행 거리 부호를 반대로 할 뿐 별도의 방향 Edge를 선택하지 않는다.

## 기존 상호작용과 위험 계산

- 동일 route의 앞 객체 간격, 횡단보도 위 보행자, 신호 상태, 킥보드 주변 보행자에 따른 단순 목표 속도 조정이 있다.
- Risk Engine은 거리, 상대 속도, 접근 여부, 원형 충돌 반경 TTC, 예상 최소 거리를 계산한다.
- 그러나 상호작용 형태(`FOLLOWING`, `CROSSING`, `CONFLICT` 등), 두 진행선의 교차점, 횡단보도 안전 이벤트, Agent별 누적 지표는 없었다.
- 위험 이벤트 cooldown은 있지만 near miss, yielding, hard brake를 개별 안전 기록으로 누적하지 않았다.

## WebSocket/API와 프런트엔드

- WebSocket은 `entities`, `risk_events`, 집계 `statistics`, 신호등, 날씨를 전송한다.
- Entity에는 현재 위치·속도·heading·route progress가 있지만 Trip과 누적 metric, trajectory는 없다.
- 프런트는 position과 heading을 damping하여 부드럽게 보간한다. 이 보간은 순간 떨림을 줄이지만 `[A,B,A]`라는 경로 의미를 바꾸지 않는다.
- 객체 mesh에는 선택 이벤트가 없고, 상세 Agent 패널 및 최근 궤적 Line도 없다.

## 좌표계와 데이터 상태

- 시뮬레이션 경로 좌표: 경도 `127.4764043`, 위도 `34.9700548`를 기준으로 투영한 로컬 미터 `x=east`, `z=north`.
- Legacy Campus Canvas 연결 변환: origin `(-214.35, 24, -93.251)`, scale `0.6242171526`, `invert_z=true`.
- 팀 데이터의 `road_zones_wgs84.geojson`은 도로 폴리곤이며 작성된 이동 중심선은 아니다. 현재 중심선은 폴리곤 장축으로 유도된 임시 데이터다.
- `common_elemetns.json`에는 `BLD_`, `RD_`, `CW_` ID가 있으나 건물 entrance의 측량 좌표는 없다.
- 따라서 이번 이식본의 entrance는 알려진 GLB 건물 위치를 로컬 좌표로 변환한 뒤 가장 가까운 접근 가능 graph edge에 투영해 생성한다. 건물 중심까지 Agent를 주행시키지 않는다.
- 보행로 원본 geometry가 없으므로 임시 보행 Edge는 도로 그래프를 기반으로 명시적으로 `derived` 표시한다. 실제 캠퍼스 적용 시 측량된 보행로/출입구 중심선으로 교체해야 한다.

## 변경 설계

- 단일 LineString 반복 대신 Node/Edge graph와 타입별 Dijkstra를 사용한다.
- 모든 Agent는 OD Trip과 lifecycle(`SPAWNED → MOVING → ARRIVED → DWELLING → NEXT_TRIP`, 외부 도착 시 `DESPAWNED`)을 가진다.
- 경로 끝에서는 wrap/reset하지 않고 arrival 처리를 수행한다.
- 건물, 주차장, 게이트, 외부, 킥보드 주차 POI를 graph node에 연결한다.
- 타입별 허용 Edge와 시나리오/시간대별 OD 가중치를 분리한다.
- 상호작용 결과를 목표 속도와 Risk Engine 양쪽에 반영하고 Agent별 metrics와 trajectory를 저장한다.

