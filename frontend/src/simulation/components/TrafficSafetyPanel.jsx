import React, { useState } from "react";
import { AlertTriangle, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { simulationStore, useSimulationStore } from "../stores/simulationStore";
import { SIMULATION_API_URL } from "../utils/apiConfig";
import { RouteEditorPanel } from "./RouteEditorPanel";

const SCENARIO_GROUPS = [
  {
    label: "기본 시나리오",
    options: [
      ["normal", "일반"], ["morning_rush", "오전 등교"], ["rush_hour", "혼잡 시간"], ["class_change", "수업 교체"],
      ["lunch_time", "점심 시간"], ["leaving_campus", "하교 시간"], ["jaywalking", "무단횡단"],
      ["scooter_speeding", "킥보드 과속"], ["scooter_wrong_way", "킥보드 역주행"],
      ["crosswalk_conflict", "횡단보도 상충"], ["rain", "우천"], ["night", "야간"],
      ["high_pedestrian_density", "보행자 밀집"], ["high_scooter_density", "킥보드 밀집"],
      ["vehicle_congestion", "차량 정체"], ["emergency_vehicle", "긴급차량"],
    ],
  },
  {
    label: "EXP1 · 킥보드 침투율",
    options: [
      ["EXP1_P00", "EXP1 P00 (0%)"], ["EXP1_P10", "EXP1 P10 (10%)"], ["EXP1_P20", "EXP1 P20 (20%)"],
      ["EXP1_P30", "EXP1 P30 (30%)"], ["EXP1_P40", "EXP1 P40 (40%)"],
    ],
  },
  {
    label: "EXP2 · 보행자 밀도 × 침투율",
    options: [
      ["EXP2_LOW_P00", "EXP2 LOW P00"], ["EXP2_LOW_P10", "EXP2 LOW P10"], ["EXP2_LOW_P20", "EXP2 LOW P20"],
      ["EXP2_LOW_P30", "EXP2 LOW P30"], ["EXP2_LOW_P40", "EXP2 LOW P40"],
      ["EXP2_NORMAL_P00", "EXP2 NORMAL P00"], ["EXP2_NORMAL_P10", "EXP2 NORMAL P10"], ["EXP2_NORMAL_P20", "EXP2 NORMAL P20"],
      ["EXP2_NORMAL_P30", "EXP2 NORMAL P30"], ["EXP2_NORMAL_P40", "EXP2 NORMAL P40"],
      ["EXP2_HIGH_P00", "EXP2 HIGH P00"], ["EXP2_HIGH_P10", "EXP2 HIGH P10"], ["EXP2_HIGH_P20", "EXP2 HIGH P20"],
      ["EXP2_HIGH_P30", "EXP2 HIGH P30"], ["EXP2_HIGH_P40", "EXP2 HIGH P40"],
    ],
  },
  {
    label: "EXP3 · 킥보드 이동 정책",
    options: [
      ["EXP3_BASELINE", "EXP3 Baseline"], ["EXP3_ROAD_ONLY", "EXP3 Road Only"], ["EXP3_SHARED_PATH", "EXP3 Shared Path"],
    ],
  },
  {
    label: "EXP4 · 킥보드 속도",
    options: [
      ["EXP4_SPEED_10", "EXP4 10 km/h"], ["EXP4_SPEED_15", "EXP4 15 km/h"],
      ["EXP4_SPEED_20", "EXP4 20 km/h"], ["EXP4_SPEED_25", "EXP4 25 km/h"],
    ],
  },
  {
    label: "EXP5 · 위험 행동 · 횡단보도",
    options: [
      ["EXP5_BASELINE", "EXP5 Baseline"], ["EXP5_WRONG_WAY", "EXP5 역주행"], ["EXP5_JAYWALKING", "EXP5 고빈도 무단횡단"],
      ["EXP5_CROSSWALK_RIDING", "EXP5 횡단보도 정속주행"], ["EXP5_CROSSWALK_DISMOUNT", "EXP5 횡단보도 하차도보"],
    ],
  },
];

const STATUS_LABEL = { running: "실행 중", paused: "일시정지", stopped: "정지" };
const RISK_LABEL = { normal: "정상", caution: "주의", warning: "경고", danger: "위험" };

const AGENT_TYPE_LABEL = { car: "자동차", person: "보행자", scooter: "킥보드" };
const ROUTE_DEBUG_ENABLED = import.meta.env.DEV || String(import.meta.env.VITE_SIMULATION_DEBUG).toLowerCase() === "true";

function formatDuration(seconds = 0) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  return minutes ? `${minutes}분 ${remainder}초` : `${remainder}초`;
}

function MiniMetric({ label, value, tone = "normal" }) {
  const toneClass = tone === "danger" ? "text-red-600" : tone === "warning" ? "text-amber-600" : "text-[var(--colors-ink)]";
  return (
    <div className="border-b border-[var(--colors-hairline)] py-2">
      <div className="text-[11px] font-[700] text-[var(--colors-ink-subtle)]">{label}</div>
      <div className={`mt-0.5 text-lg font-[800] ${toneClass}`}>{value}</div>
    </div>
  );
}

export function TrafficSafetyPanel() {
  const snapshot = useSimulationStore((state) => state);
  const [scenario, setScenario] = useState("normal");
  const [counts, setCounts] = useState({ car: 30, person: 100, scooter: 30 });
  const [speed, setSpeed] = useState(1);
  const [eventsEnabled, setEventsEnabled] = useState(true);
  const [requestError, setRequestError] = useState(null);

  const call = async (path, body) => {
    setRequestError(null);
    try {
      const response = await fetch(`${SIMULATION_API_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);
      return response.json();
    } catch (error) {
      setRequestError(error.message);
      return null;
    }
  };

  const start = async () => {
    await call("/api/simulation/scenario", { scenario, counts, risk_events_enabled: eventsEnabled });
    await call("/api/simulation/start", { scenario, counts });
  };
  const updateCount = (type, value) => setCounts((current) => ({ ...current, [type]: Math.max(0, Number(value) || 0) }));
  const setSimulationSpeed = (value) => {
    const multiplier = Number(value);
    setSpeed(multiplier);
    call("/api/simulation/speed", { multiplier });
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between border-b border-[var(--colors-hairline)] pb-3">
        <div>
          <div className="text-sm font-[800]">캠퍼스 교통 시뮬레이션</div>
          <div className="mt-1 text-[12px] text-[var(--colors-ink-subtle)]">{STATUS_LABEL[snapshot.status]} · {snapshot.connectionStatus}</div>
        </div>
        <span className={`px-2 py-1 text-[11px] font-[800] ${snapshot.connectionStatus === "연결됨" ? "text-emerald-700" : "text-amber-700"}`}>
          {snapshot.connectionStatus === "연결됨" ? "● 연결됨" : `△ ${snapshot.connectionStatus}`}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-x-3">
        <MiniMetric label="자동차" value={`${snapshot.statistics.car_count}대`} />
        <MiniMetric label="보행자" value={`${snapshot.statistics.person_count}명`} />
        <MiniMetric label="킥보드" value={`${snapshot.statistics.scooter_count}대`} />
        <MiniMetric label="정상 / 주의" value={`${snapshot.statistics.normal_count} / ${snapshot.statistics.caution_count}`} />
        <MiniMetric label="경고" value={`${snapshot.statistics.warning_count}`} tone="warning" />
        <MiniMetric label="위험" value={`${snapshot.statistics.danger_count}`} tone="danger" />
        <MiniMetric label="완료 Trip" value={Object.values(snapshot.statistics.completed_trips || {}).reduce((sum, value) => sum + Number(value || 0), 0)} />
        <MiniMetric label="현재 위험" value={snapshot.statistics.current_risks || 0} tone="warning" />
        <MiniMetric label="Near Miss" value={snapshot.statistics.near_miss_count || 0} tone="danger" />
        <MiniMetric label="Conflict" value={snapshot.statistics.conflict_count || 0} tone="warning" />
        <MiniMetric label="Collision" value={snapshot.statistics.collision_count || 0} tone="danger" />
        <MiniMetric label="Hard Braking" value={snapshot.statistics.hard_braking_count || 0} tone="warning" />
        <MiniMetric label="Min TTC" value={snapshot.statistics.min_ttc == null ? "-" : `${Number(snapshot.statistics.min_ttc).toFixed(2)}s`} />
        <MiniMetric label="Min PET" value={snapshot.statistics.min_pet == null ? "-" : `${Number(snapshot.statistics.min_pet).toFixed(2)}s`} />
        <MiniMetric label="Risk Exposure" value={`${Number(snapshot.statistics.risk_exposure_time || 0).toFixed(1)}s`} />
      </div>
      <div className="flex items-center justify-between text-[12px] font-[700] text-[var(--colors-ink-muted)]">
        <span>시뮬레이션 {snapshot.simulationTime.toFixed(1)}초 · {snapshot.demandProfile}</span><span>속도 ×{speed}</span>
      </div>
      {snapshot.statistics.network_coverage && (
        <div className="rounded-md bg-[var(--colors-surface-2)] p-3 text-[11px]">
          <div className="mb-2 flex items-center justify-between font-[800]">
            <span>Campus Network Coverage</span>
            <span>{snapshot.statistics.network_runtime?.mode || "-"}</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-[var(--colors-ink-subtle)]">
            {["car", "person", "scooter"].map((type) => {
              const coverage = snapshot.statistics.network_coverage[type] || {};
              return <div key={type}><div className="font-[800] text-[var(--colors-ink)]">{AGENT_TYPE_LABEL[type]}</div><div>실주행 {coverage.visited_percent || 0}%</div><div>계획 {coverage.planned_percent || 0}%</div></div>;
            })}
          </div>
          {snapshot.statistics.network_runtime?.derived_allowed && <div className="mt-2 text-amber-700">파생 경로 개발 모드 · 실측 승인 데이터 아님</div>}
        </div>
      )}

      <div className="space-y-3 border-t border-[var(--colors-hairline)] pt-4">
        <label className="block text-[12px] font-[800] text-[var(--colors-ink-subtle)]">
          시나리오
          <select value={scenario} onChange={(event) => setScenario(event.target.value)} className="mt-1 h-9 w-full rounded-md border border-[var(--colors-hairline)] bg-[var(--colors-surface-1)] px-2 text-sm text-[var(--colors-ink)]">
            {SCENARIO_GROUPS.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </optgroup>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-3 gap-2">
          {[["car", "자동차"], ["person", "보행자"], ["scooter", "킥보드"]].map(([type, label]) => (
            <label key={type} className="text-[11px] font-[700] text-[var(--colors-ink-subtle)]">{label}
              <input type="number" min="0" max="500" value={counts[type]} onChange={(event) => updateCount(type, event.target.value)} className="mt-1 h-8 w-full rounded-md border border-[var(--colors-hairline)] bg-[var(--colors-surface-1)] px-2 text-sm text-[var(--colors-ink)]" />
            </label>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex flex-1 items-center gap-2 text-[12px] font-[700] text-[var(--colors-ink-subtle)]">
            <input type="checkbox" checked={eventsEnabled} onChange={(event) => setEventsEnabled(event.target.checked)} /> 위험 이벤트
          </label>
          <select aria-label="시뮬레이션 속도" value={speed} onChange={(event) => setSimulationSpeed(event.target.value)} className="h-8 rounded-md border border-[var(--colors-hairline)] bg-[var(--colors-surface-1)] px-2 text-xs">
            {[0.5, 1, 2, 4, 8, 10].map((value) => <option key={value} value={value}>×{value}</option>)}
          </select>
        </div>
        <div className="grid grid-cols-4 overflow-hidden rounded-md border border-[var(--colors-hairline)]">
          <button type="button" onClick={start} className="flex h-9 items-center justify-center gap-1 border-r border-[var(--colors-hairline)] text-xs font-[800]"><Play size={13} />시작</button>
          <button type="button" onClick={() => call("/api/simulation/pause")} className="flex h-9 items-center justify-center gap-1 border-r border-[var(--colors-hairline)] text-xs font-[800]"><Pause size={13} />정지</button>
          <button type="button" onClick={() => call("/api/simulation/resume")} className="flex h-9 items-center justify-center gap-1 border-r border-[var(--colors-hairline)] text-xs font-[800]"><SkipForward size={13} />재개</button>
          <button type="button" onClick={async () => { await call("/api/simulation/reset"); simulationStore.reset(); }} className="flex h-9 items-center justify-center gap-1 text-xs font-[800]"><RotateCcw size={13} />초기화</button>
        </div>
        {requestError && <div className="text-[12px] font-[700] text-red-600">오류: {requestError}</div>}
      </div>

      <div className="border-t border-[var(--colors-hairline)] pt-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-[800]">선택 Agent</div>
          {snapshot.selectedAgentId && <button type="button" onClick={() => simulationStore.selectAgent(null)} className="text-[11px] font-[700] text-[var(--colors-ink-subtle)]">선택 해제</button>}
        </div>
        {!snapshot.selectedAgentId && <div className="py-4 text-center text-[12px] text-[var(--colors-ink-subtle)]">3D 화면의 자동차·보행자·킥보드를 클릭하세요.</div>}
        {snapshot.selectedAgentId && !snapshot.selectedAgentDetails && !snapshot.selectionError && <div className="py-4 text-center text-[12px] text-[var(--colors-ink-subtle)]">Agent 정보를 불러오는 중입니다.</div>}
        {snapshot.selectionError && <div className="text-[12px] font-[700] text-red-600">{snapshot.selectionError}</div>}
        {snapshot.selectedAgentDetails && (() => {
          const agent = snapshot.selectedAgentDetails;
          const metrics = agent.metrics || {};
          return (
            <div className="space-y-3 rounded-md bg-[var(--colors-surface-2)] p-3 text-[12px]">
              <div className="flex items-center justify-between"><span className="text-sm font-[900]">{agent.id}</span><span className="font-[800]">{AGENT_TYPE_LABEL[agent.type] || agent.type}</span></div>
              <div className="grid grid-cols-[80px_1fr] gap-x-2 gap-y-1">
                <span className="text-[var(--colors-ink-subtle)]">From</span><span className="font-[700]">{agent.origin_name}</span>
                <span className="text-[var(--colors-ink-subtle)]">To</span><span className="font-[700]">{agent.destination_name}</span>
                <span className="text-[var(--colors-ink-subtle)]">속도</span><span>{(Number(agent.speed || 0) * 3.6).toFixed(1)} km/h</span>
                <span className="text-[var(--colors-ink-subtle)]">상태</span><span>{agent.trip_status} · {agent.interaction_state || "NONE"}</span>
                <span className="text-[var(--colors-ink-subtle)]">경로</span><span className="truncate" title={agent.current_route}>{agent.current_route}</span>
                <span className="text-[var(--colors-ink-subtle)]">행동 유형</span><span>{agent.behavior_profile?.name || "-"}</span>
              </div>
              <div className="border-t border-[var(--colors-hairline)] pt-2">
                <div className="mb-1 font-[800]">Safety</div>
                <div className="grid grid-cols-2 gap-1">
                  <span>Risk {RISK_LABEL[agent.risk_level] || agent.risk_level}</span><span>TTC {agent.current_ttc == null ? "-" : `${agent.current_ttc}s`}</span>
                  <span>PET {metrics.minimum_pet == null ? "-" : `${metrics.minimum_pet}s`}</span><span>Conflicts {metrics.conflict_count || 0}</span>
                  <span>Near Miss {metrics.near_miss_count || 0}</span><span>Hard Brake {metrics.hard_brake_count || 0}</span>
                </div>
              </div>
              <div className="border-t border-[var(--colors-hairline)] pt-2">
                <div className="mb-1 font-[800]">Trip</div>
                <div className="grid grid-cols-2 gap-1">
                  <span>거리 {Math.round(metrics.trip_distance || 0)}m</span><span>시간 {formatDuration(metrics.travel_time)}</span>
                  <span>평균 {((metrics.average_speed || 0) * 3.6).toFixed(1)} km/h</span><span>대기 {formatDuration(metrics.waiting_time)}</span>
                </div>
              </div>
            </div>
          );
        })()}
      </div>

      <div className="border-t border-[var(--colors-hairline)] pt-4">
        <div className="mb-2 text-sm font-[800]">Simulation Timeline</div>
        <div className="max-h-36 space-y-1 overflow-y-auto text-[11px]">
          {(snapshot.timeline || []).length === 0 && <div className="text-[var(--colors-ink-subtle)]">기록된 이벤트가 없습니다.</div>}
          {(snapshot.timeline || []).slice(0, 30).map((item, index) => <div key={`${item.type}-${item.event_id || item.trip_id || item.agent_id}-${index}`} className="flex justify-between border-b border-[var(--colors-hairline)] py-1"><span>{item.type} · {item.agent_id || (item.object_ids || []).join(" ↔ ")}</span><span>{Number(item.simulation_time || 0).toFixed(1)}s</span></div>)}
        </div>
      </div>

      {ROUTE_DEBUG_ENABLED && <RouteEditorPanel />}

      <div className="border-t border-[var(--colors-hairline)] pt-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-[800]"><AlertTriangle size={14} /> 실시간 위험 이벤트</div>
        <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {snapshot.riskEvents.length === 0 && <div className="py-4 text-center text-[12px] text-[var(--colors-ink-subtle)]">감지된 이벤트가 없습니다.</div>}
          {snapshot.riskEvents.slice(0, 20).map((event) => (
            <div key={event.event_id} className="border-l-2 border-[var(--colors-hairline)] bg-[var(--colors-surface-2)] px-3 py-2 text-[12px]" style={{ borderLeftColor: event.risk_level === "danger" ? "#dc2626" : "#f59e0b" }}>
              <div className="flex items-center justify-between gap-2"><span className="font-[800]">{RISK_LABEL[event.risk_level] || event.risk_level} · {event.location_id || "위치 미상"}</span><span className="font-[800]">{event.risk_score}점</span></div>
              <div className="mt-1 text-[var(--colors-ink-subtle)]">{(event.object_ids || []).join(" ↔ ")}</div>
              <div className="mt-1 text-[var(--colors-ink-muted)]">TTC {event.ttc == null ? "-" : `${event.ttc}s`} · PET {event.pet == null ? "-" : `${event.pet}s`} · 최소거리 {event.minimum_distance ?? event.distance}m</div>
              <div className="mt-1 text-[var(--colors-ink-muted)]">외곽간격 {event.minimum_clearance == null ? "-" : `${event.minimum_clearance}m`} · {event.prediction_model || "linear"}</div>
              <div className="mt-1 font-[700] text-[var(--colors-ink-subtle)]">{event.interaction_state || "CONFLICT"} · {event.safety_event || "TRAFFIC_CONFLICT"}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
