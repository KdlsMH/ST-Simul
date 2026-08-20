import React, { useMemo } from "react";
import { useSimulationStore } from "../stores/simulationStore";
import { simulationToThree } from "../utils/coordinateTransform";

export function RiskEventLayer({ coordinateConfig, resolveHeight }) {
  // Select the raw, reference-stable store fields (unchanged between actual
  // store updates) rather than deriving a new array inside the selector.
  // useSyncExternalStore requires getSnapshot() to return an Object.is-equal
  // value when called twice with no store update in between; building a new
  // Set/array on every call breaks that and causes an infinite render loop.
  const riskEvents = useSimulationStore((state) => state.riskEvents);
  const entities = useSimulationStore((state) => state.entities);

  const markers = useMemo(() => {
    const ids = new Set(riskEvents.slice(0, 10).flatMap((event) => event.object_ids || []));
    return Array.from(ids).map((id) => entities.get(id)).filter(Boolean);
  }, [riskEvents, entities]);

  return markers.map((entity) => {
    const position = simulationToThree(entity, coordinateConfig);
    const resolvedY = resolveHeight?.(position, entity);
    if (Number.isFinite(resolvedY)) position.y = resolvedY;
    return (
    <mesh key={`risk-${entity.id}`} position={[position.x, position.y + 2.8, position.z]}>
      <octahedronGeometry args={[0.38, 0]} />
      <meshBasicMaterial color={entity.risk_level === "danger" ? "#ef233c" : "#f59e0b"} />
    </mesh>
    );
  });
}
