# 교통 시뮬레이션 합본 안내

팀원 `dev` 버전의 기존 `uni.glb` 도로·건물 렌더링은 유지하고, Legacy React Three Fiber Canvas 위에 자동차·보행자·킥보드와 위험 이벤트만 추가한 합본입니다. VWorld 엔트리의 Cesium 렌더링은 변경하지 않았습니다.

## 연결된 위치

- `backend/simulation`: 독립 FastAPI/WebSocket 시뮬레이션 서버
- `backend/simulation/data/routes.geojson`: 팀 도로 폴리곤 92개에서 생성한 로컬 미터 중심선
- `backend/simulation/data/mobility_graph.json`: 타입별 Edge와 POI를 가진 OD 경로 그래프
- `backend/simulation/data/building_entrances.json`: GLB 힌트를 접근 Edge에 snap한 임시 출입구
- `backend/simulation/data/od_demand.json`: 시간대·시나리오별 OD 수요와 체류 시간
- `backend/build_routes_from_road_zones.py`: 중심선과 신호 상태 지점 재생성기
- `backend/build_mobility_data.py`: graph, node, entrance 재생성기
- `frontend/src/simulation`: 표시 레이어, WebSocket store/hook, 안전 제어 패널
- `frontend/src/simulation/CampusTrafficSimulation.jsx`: `uni.glb` 좌표·축척 및 지형 높이 연결 어댑터
- `frontend/src/AppLegacy.jsx`: 기존 Canvas와 안전 탭에 실제 연결

## 실행

터미널 1:

```bash
cd weather
python -m pip install -r requirements.txt
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload
```

터미널 2:

```bash
cd backend
python -m pip install -r simulation/requirements.txt
python -m uvicorn simulation.main:app --host 127.0.0.1 --port 8002 --reload
```

터미널 3:

```bash
cd frontend
npm install
npm run dev:legacy
```

브라우저에서 `http://127.0.0.1:5173`을 열고 오른쪽 `안전` 탭에서 시나리오와 객체 수를 선택한 뒤 `시작`을 누릅니다.

## 경로 데이터

팀 ZIP에는 `docs/assets/data/road_zones_wgs84.geojson`의 도로 폴리곤과 `common/data/common_elemetns.json`의 ID 메타데이터만 있고 작성된 중심선·보행로 geometry는 없습니다. 합본은 다음 과정을 재현 가능하게 적용했습니다.

1. WGS84 좌표를 D4 기준점(`127.4764043`, `34.9700548`)의 동/북 방향 로컬 미터로 투영합니다.
2. 각 도로 폴리곤의 주축을 계산하고 폴리곤 내부의 가장 긴 구간으로 잘라 중심선을 만듭니다.
3. `uni.glb`의 실제 export scale(`0.6242171526`)과 `CityModel`의 중심 이동을 적용합니다.
4. 객체마다 `Topography` 메시를 아래 방향으로 raycast해 경사 지형의 높이에 맞춥니다.

원본에 보행로 geometry가 없기 때문에 보행 Edge는 도로 구역의 공간 연결을 따라 만든 `shared_path_derived`로 명시되어 있습니다. 자동차는 road/vehicle/gate/parking Edge만, 보행자는 derived shared path/crosswalk/building entrance/pedestrian gate만, 킥보드는 정책상 허용된 road/shared/crosswalk/entrance Edge를 사용합니다. 이는 이식본에서 OD 이동을 검증하기 위한 임시 geometry이며 실제 측량 보행로가 생기면 반드시 교체해야 합니다.

`routes.geojson`의 모든 Feature는 이제 `[A, B]`, `loop=false`이며, 이동 엔진은 이 조각을 직접 반복하지 않습니다. `mobility_graph.json`에서 여러 Edge를 Dijkstra로 연결한 Trip을 만들고, 끝점에서는 도착·체류·다음 Trip 또는 외부 제거를 수행합니다.

원본 도로 폴리곤이 바뀌면 다음 명령으로 다시 생성하고 검사합니다.

```bash
cd backend
python build_routes_from_road_zones.py
python build_mobility_data.py
python validate_routes.py simulation/data/routes.geojson
```

중심선과 graph 연결은 폴리곤에서 결정적으로 파생한 값입니다. 실제 측량 중심선·보행로·건물 출입구 데이터가 추후 제공되면 `routes.geojson`, `mobility_graph.json`, `building_entrances.json`을 함께 교체하는 것이 가장 정확합니다.

## 테스트

```bash
cd backend
python -m pytest -q

cd ../frontend
npm run test
npm run build
npm run build:vworld
```

환경 변수 예시는 루트와 `frontend/.env.example`에 있습니다. 신호등은 상태 계산에만 사용하며 기존 지도에는 별도 신호등 메시를 추가하지 않습니다.
