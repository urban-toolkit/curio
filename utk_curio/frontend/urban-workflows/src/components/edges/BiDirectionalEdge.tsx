import React from "react";
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
  getStraightPath,
  getSimpleBezierPath,
  getSmoothStepPath,
} from "reactflow";
import { useAgentDropHoverEdge } from "../../hook/useAgentDropHoverEdge";
import { EDGE_DROP_HOVER_ATTR, edgeDropHighlightStyle } from "./edgeDropHighlight";
import { EdgeAgentBadges } from "../agents/attach/EdgeAgentBadges";

export default function BiDirectionalEdge({
  id,
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

  const dropHovered = useAgentDropHoverEdge(id);

  // Always-mounted <g>: see the twin comment in UniDirectionalEdge (#296).
  return (
    <g {...{ [EDGE_DROP_HOVER_ATTR]: dropHovered ? 'true' : undefined }}>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        markerStart={markerStart}
        style={edgeDropHighlightStyle(data?.keywordHighlighted ? 'blue' : 'red', dropHovered)}
      />
      <EdgeAgentBadges edgeId={id} labelX={labelX} labelY={labelY} />
    </g>
  );
}
