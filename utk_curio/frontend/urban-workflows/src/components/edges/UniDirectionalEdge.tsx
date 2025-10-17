import React, { useEffect } from 'react';
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
  getStraightPath,
  getSimpleBezierPath,
  getSmoothStepPath 
} from 'reactflow';

export default function UniDirectionalEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
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
    <BaseEdge path={edgePath} markerEnd={markerEnd} style={{stroke: data.keywordHighlighted ? '#1E1F23' : 'grey'}} />
  );
}
