import React from 'react';
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
  getStraightPath,
  getSimpleBezierPath,
  getSmoothStepPath 
} from 'reactflow';
import { useAgentDropHoverEdge } from '../../hook/useAgentDropHoverEdge';
import { EDGE_DROP_HOVER_ATTR, edgeDropHighlightStyle } from './edgeDropHighlight';
import { EdgeAgentBadges } from '../agents/attach/EdgeAgentBadges';

export default function UniDirectionalEdge({
  id,
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

  const dropHovered = useAgentDropHoverEdge(id);

  // The <g> is always rendered, never conditionally mounted: unmounting the
  // path mid-drag would swap React Flow's wide `.react-flow__edge-interaction`
  // element out from under `elementFromPoint` while the cursor is still on it.
  // It is geometrically inert - `closest('.react-flow__edge')` walks straight
  // through it and MainCanvas.css's `path.react-flow__edge-path` descendant
  // rules still match - and it gives tests a name-stable hook (#296).
  return (
    <g {...{ [EDGE_DROP_HOVER_ATTR]: dropHovered ? 'true' : undefined }}>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={edgeDropHighlightStyle(data?.keywordHighlighted ? '#1E1F23' : 'grey', dropHovered)}
      />
      <EdgeAgentBadges edgeId={id} labelX={labelX} labelY={labelY} />
    </g>
  );
}
