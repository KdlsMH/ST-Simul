import { useCallback, useSyncExternalStore } from "react";
import { createSimulationStore, parseSimulationMessage } from "./simulationStoreCore.mjs";

export const simulationStore = createSimulationStore();
export { parseSimulationMessage };

export function useSimulationStore(selector = (state) => state) {
  const getSelectedState = useCallback(() => selector(simulationStore.getState()), [selector]);
  return useSyncExternalStore(simulationStore.subscribe, getSelectedState, getSelectedState);
}
