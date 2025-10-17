import React from "react";
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
  getStraightPath,
  getSimpleBezierPath,
  getSmoothStepPath,
} from "reactflow";

export default function BiDirectionalEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  markerStart,
  data
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  // const [edgePath, labelX, labelY] = getStraightPath({
  //   sourceX,
  //   sourceY,
  //   targetX,
  //   targetY
  // });

  // const [edgePath, labelX, labelY] = getSimpleBezierPath({
  //   sourceX,
  //   sourceY,
  //   sourcePosition,
  //   targetX,
  //   targetY,
  //   targetPosition,
  // });

  // const [edgePath, labelX, labelY] = getSmoothStepPath({
  //   sourceX,
  //   sourceY,
  //   sourcePosition,
  //   targetX,
  //   targetY,
  //   targetPosition,
  // });

  return (
    <BaseEdge
      path={edgePath}
      markerEnd={markerEnd}
      markerStart={markerStart}
      style={{stroke: data.keywordHighlighted ? 'blue' : 'red'}}
    />
  );
}
