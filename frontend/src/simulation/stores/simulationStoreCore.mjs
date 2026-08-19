const EMPTY_STATS = {
  car_count: 0,
  person_count: 0,
  scooter_count: 0,
  normal_count: 0,
  caution_count: 0,
  warning_count: 0,
  danger_count: 0,
  active_agents: { car: 0, person: 0, scooter: 0 },
  completed_trips: { car: 0, person: 0, scooter: 0 },
  average_travel_time: { car: 0, person: 0, scooter: 0 },
  risk_events: { car_person: 0, car_scooter: 0, person_scooter: 0 },
  near_miss_count: 0,
  conflict_count: 0,
  collision_count: 0,
  min_ttc: null,
  min_pet: null,
  min_clearance: null,
  hard_braking_count: 0,
  risk_exposure_time: 0,
  avg_travel_time: null,
  avg_waiting_time: null,
  completed_trip_count: 0,
  throughput: 0,
  current_risks: 0,
};

function validEntity(entity) {
  return Boolean(
    entity &&
      typeof entity.id === "string" &&
      ["car", "person", "scooter"].includes(entity.type) &&
      [entity.x, entity.y ?? 0, entity.z, entity.speed ?? 0, entity.heading ?? 0].every((value) =>
        Number.isFinite(Number(value)),
      ),
  );
}

export function parseSimulationMessage(raw, previousState = {}) {
  let payload;
  try {
    payload = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    return null;
  }
  if (!payload || !["simulation_update", "simulation_delta"].includes(payload.type)) return null;
  const entities = payload.type === "simulation_delta" ? new Map(previousState.entities || []) : new Map();
  if (payload.type === "simulation_update" && !Array.isArray(payload.entities)) return null;
  for (const id of payload.entity_removed || []) entities.delete(id);
  for (const entity of payload.entities || payload.entity_updates || []) {
    const merged = entities.has(entity.id) ? { ...entities.get(entity.id), ...entity } : { ...entity };
    if (validEntity(merged)) entities.set(merged.id, merged);
  }
  return {
    simulationTime: Number.isFinite(Number(payload.simulation_time)) ? Number(payload.simulation_time) : previousState.simulationTime || 0,
    status: ["running", "paused", "stopped"].includes(payload.status) ? payload.status : previousState.status || "stopped",
    entities,
    entityList: Array.from(entities.values()),
    riskEvents: Array.isArray(payload.risk_events) ? payload.risk_events.filter((event) => event?.event_id) : [],
    statistics: payload.statistics ? { ...EMPTY_STATS, ...payload.statistics } : previousState.statistics || { ...EMPTY_STATS },
    trafficLights: Array.isArray(payload.traffic_lights) ? payload.traffic_lights : previousState.trafficLights || [],
    weather: payload.weather || previousState.weather || {},
    demandProfile: payload.demand_profile || previousState.demandProfile || "daytime",
    timeline: Array.isArray(payload.timeline) ? payload.timeline : previousState.timeline || [],
  };
}

export function createSimulationStore() {
  let state = {
    connectionStatus: "연결 끊김",
    lastError: null,
    simulationTime: 0,
    status: "stopped",
    entities: new Map(),
    entityList: [],
    riskEvents: [],
    statistics: { ...EMPTY_STATS },
    trafficLights: [],
    weather: {},
    demandProfile: "daytime",
    timeline: [],
    selectedAgentId: null,
    selectedAgentDetails: null,
    selectionError: null,
  };
  const listeners = new Set();
  const emit = () => listeners.forEach((listener) => listener());
  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    setConnectionStatus(connectionStatus, lastError = null) {
      state = { ...state, connectionStatus, lastError };
      emit();
    },
    applyMessage(raw) {
      const parsed = parseSimulationMessage(raw, state);
      if (!parsed) return false;
      const timelineRestarted =
        parsed.simulationTime < state.simulationTime ||
        (parsed.status === "stopped" && parsed.simulationTime === 0);
      const byId = new Map(
        (timelineRestarted ? [] : state.riskEvents).map((event) => [event.event_id, event]),
      );
      parsed.riskEvents.forEach((event) => byId.set(event.event_id, event));
      state = { ...state, ...parsed, riskEvents: Array.from(byId.values()).slice(-100).reverse() };
      emit();
      return true;
    },
    selectAgent(selectedAgentId) {
      state = {
        ...state,
        selectedAgentId: selectedAgentId || null,
        selectedAgentDetails: selectedAgentId === state.selectedAgentId ? state.selectedAgentDetails : null,
        selectionError: null,
      };
      emit();
    },
    setSelectedAgentDetails(selectedAgentDetails, selectionError = null) {
      state = { ...state, selectedAgentDetails, selectionError };
      emit();
    },
    reset() {
      state = { ...state, simulationTime: 0, status: "stopped", entities: new Map(), entityList: [], riskEvents: [], timeline: [], statistics: { ...EMPTY_STATS }, selectedAgentId: null, selectedAgentDetails: null, selectionError: null };
      emit();
    },
  };
}
