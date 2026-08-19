import assert from "node:assert/strict";
import test from "node:test";

import { createSimulationStore } from "./simulationStoreCore.mjs";

function update({ time, status = "running", events = [] }) {
  return {
    type: "simulation_update",
    simulation_time: time,
    status,
    entities: [],
    risk_events: events,
    statistics: {},
    traffic_lights: [],
  };
}

test("clears accumulated risk events when the backend timeline restarts", () => {
  const store = createSimulationStore();
  store.applyMessage(update({
    time: 12,
    events: [{ event_id: "risk_1", object_ids: ["car_1", "person_1"] }],
  }));
  assert.equal(store.getState().riskEvents.length, 1);

  store.applyMessage(update({ time: 0, status: "stopped" }));
  assert.equal(store.getState().riskEvents.length, 0);
});

test("keeps selected agent details separate from the websocket entity snapshot", () => {
  const store = createSimulationStore();
  store.selectAgent("scooter_014");
  store.setSelectedAgentDetails({ id: "scooter_014", trajectory: [[1, 2, 0]] });
  store.applyMessage(update({ time: 1 }));
  assert.equal(store.getState().selectedAgentId, "scooter_014");
  assert.deepEqual(store.getState().selectedAgentDetails.trajectory, [[1, 2, 0]]);
  store.selectAgent(null);
  assert.equal(store.getState().selectedAgentId, null);
});

test("merges compact entity deltas and removes despawned agents", () => {
  const store = createSimulationStore();
  store.applyMessage({
    type: "simulation_update", simulation_time: 0, status: "running",
    entities: [{ id: "car_1", type: "car", x: 0, y: 0, z: 0, speed: 1, heading: 0 }],
    risk_events: [], statistics: {}, traffic_lights: [],
  });
  store.applyMessage({
    type: "simulation_delta", simulation_time: 0.1, status: "running",
    entity_updates: [{ id: "car_1", x: 2 }, { id: "person_1", type: "person", x: 1, y: 0, z: 1, speed: 1, heading: 90 }],
    entity_removed: [], risk_events: [], statistics: {},
  });
  assert.equal(store.getState().entities.get("car_1").x, 2);
  assert.equal(store.getState().entityList.length, 2);
  store.applyMessage({ type: "simulation_delta", simulation_time: 0.2, status: "running", entity_updates: [], entity_removed: ["car_1"], risk_events: [] });
  assert.equal(store.getState().entities.has("car_1"), false);
});
