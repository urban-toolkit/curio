import React, { useMemo, useRef, useState } from "react";
import { internalsSymbol, useStore, type ReactFlowState } from "reactflow";

import { useFlowContext } from "../../providers/FlowProvider";
import type {
  ScenarioBox,
  ScenarioCanvasView,
  StandInEnd,
} from "../../utils/scenarios/scenarioCanvasView";
import { nodeLabel, outputStatus } from "./scenarioLabels";
import { useScenarioActions } from "./useScenarioActions";
import styles from "./ScenarioLayers.module.css";

/** A collapsed scenario's box: its size, and the height of each port's row. */
export const BOX_WIDTH = 260;
const BOX_HEADER = 40;
const BOX_SECTION = 22;
const BOX_ROW = 24;
const BOX_PAD = 8;
/** Room a frame leaves around its scenario's nodes. */
const FRAME_PAD = 18;

export interface BoxLayout {
  width: number;
  height: number;
  /** Section titles and rows, as offsets from the box's top. */
  contextTitle?: number;
  outcomeTitle?: number;
  context: Map<string, number>;
  outcomes: Map<string, number>;
}

/**
 * Where a box's rows go. A stand-in edge ends at its row's port, so the box
 * and the edges read this one layout.
 */
export function boxLayout(box: ScenarioBox): BoxLayout {
  let y = BOX_HEADER;
  const layout: BoxLayout = { width: BOX_WIDTH, height: 0, context: new Map(), outcomes: new Map() };
  if (box.parts.context.length > 0) {
    layout.contextTitle = y;
    y += BOX_SECTION;
    for (const id of box.parts.context) {
      layout.context.set(id, y);
      y += BOX_ROW;
    }
  }
  if (box.parts.outcomes.length > 0) {
    layout.outcomeTitle = y;
    y += BOX_SECTION;
    for (const id of box.parts.outcomes) {
      layout.outcomes.set(id, y);
      y += BOX_ROW;
    }
  }
  layout.height = y + BOX_PAD;
  return layout;
}

type Geometry = { x: number; y: number; width: number; height: number; internal: any };

const transformOf = (s: ReactFlowState) => s.transform;
const internalsOf = (s: ReactFlowState) => s.nodeInternals;

function geometryOf(internals: ReactFlowState["nodeInternals"], id: string): Geometry | null {
  const internal: any = internals.get(id);
  if (!internal) return null;
  const at = internal.positionAbsolute ?? internal.position;
  return { x: at.x, y: at.y, width: internal.width ?? 0, height: internal.height ?? 0, internal };
}

/** The point a node's handle sits at, or the middle of the side a handle of that kind sits on. */
function handlePoint(geo: Geometry, kind: "source" | "target", handle?: string | null) {
  const bounds = geo.internal?.[internalsSymbol]?.handleBounds?.[kind] as
    | Array<{ id?: string | null; x: number; y: number; width: number; height: number }>
    | undefined;
  const found = bounds?.find((b) => (b.id ?? null) === (handle ?? null)) ?? bounds?.[0];
  if (found) return { x: geo.x + found.x + found.width / 2, y: geo.y + found.y + found.height / 2 };
  return { x: kind === "source" ? geo.x + geo.width : geo.x, y: geo.y + geo.height / 2 };
}

function curve(a: { x: number; y: number }, b: { x: number; y: number }) {
  const bend = Math.max(40, Math.abs(b.x - a.x) / 2);
  return `M ${a.x} ${a.y} C ${a.x + bend} ${a.y}, ${b.x - bend} ${b.y}, ${b.x} ${b.y}`;
}

export interface ScenarioLayersProps {
  view: ScenarioCanvasView<any, any>;
  labelOf: (id: string) => string;
  statusOf: (id: string) => { text: string; tone: "done" | "error" | "stale" | "none" };
  onExpand: (id: string) => void;
  onCollapse: (id: string) => void;
  onMoveBox: (id: string, at: { x: number; y: number }) => void;
  /** False in a read-only view: boxes stay where they are. */
  editable: boolean;
}

/**
 * Draws what `scenarioCanvasView` adds to the canvas (#662) beside React Flow,
 * in its coordinates: frames and stand-in edges behind the nodes, boxes and the
 * frames' headers in front. None of it is in React Flow's store.
 */
export function ScenarioLayers({ view, labelOf, statusOf, onExpand, onCollapse, onMoveBox, editable }: ScenarioLayersProps) {
  const [tx, ty, zoom] = useStore(transformOf);
  const internals = useStore(internalsOf);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null);
  const dragStart = useRef<{ id: string; clientX: number; clientY: number; moved: boolean } | null>(null);

  const boxes = useMemo(
    () =>
      view.boxes.map((box) => {
        const moved = drag && drag.id === box.scenario.id;
        return { box, x: box.x + (moved ? drag.dx : 0), y: box.y + (moved ? drag.dy : 0), layout: boxLayout(box) };
      }),
    [view.boxes, drag],
  );

  const frames = view.frames
    .map(({ scenario, members }) => {
      const geos = members.map((id) => geometryOf(internals, id)).filter((g): g is Geometry => !!g && g.width > 0);
      if (geos.length === 0) return null;
      const left = Math.min(...geos.map((g) => g.x)) - FRAME_PAD;
      const top = Math.min(...geos.map((g) => g.y)) - FRAME_PAD;
      const right = Math.max(...geos.map((g) => g.x + g.width)) + FRAME_PAD;
      const bottom = Math.max(...geos.map((g) => g.y + g.height)) + FRAME_PAD;
      return { scenario, left, top, width: right - left, height: bottom - top };
    })
    .filter((f): f is NonNullable<typeof f> => !!f);

  const endPoint = (end: StandInEnd, kind: "source" | "target") => {
    if ("node" in end) {
      const geo = geometryOf(internals, end.node);
      return geo && geo.width > 0 ? handlePoint(geo, kind, end.handle) : null;
    }
    const placed = boxes.find((b) => b.box.scenario.id === end.box);
    if (!placed) return null;
    const row = (end.port === "context" ? placed.layout.context : placed.layout.outcomes).get(end.of);
    if (row === undefined) return null;
    return {
      x: placed.x + (end.port === "outcome" ? placed.layout.width : 0),
      y: placed.y + row + BOX_ROW / 2,
    };
  };

  const paths = view.standIns
    .map((edge) => {
      const a = endPoint(edge.source, "source");
      const b = endPoint(edge.target, "target");
      return a && b ? { id: edge.id, d: curve(a, b) } : null;
    })
    .filter((p): p is { id: string; d: string } => !!p);

  const plane = { transform: `translate(${tx}px, ${ty}px) scale(${zoom})` };

  const startDrag = (id: string) => (event: React.PointerEvent) => {
    if (!editable || event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragStart.current = { id, clientX: event.clientX, clientY: event.clientY, moved: false };
  };
  const moveDrag = (event: React.PointerEvent) => {
    const start = dragStart.current;
    if (!start) return;
    const dx = (event.clientX - start.clientX) / zoom;
    const dy = (event.clientY - start.clientY) / zoom;
    if (!start.moved && Math.hypot(dx, dy) < 3) return;
    start.moved = true;
    setDrag({ id: start.id, dx, dy });
  };
  // Where the pointer is let go, not where the last drawn move put the box.
  const endDrag = (box: ScenarioBox) => (event: React.PointerEvent) => {
    const start = dragStart.current;
    dragStart.current = null;
    if (start?.moved && start.id === box.scenario.id) {
      onMoveBox(box.scenario.id, {
        x: box.x + (event.clientX - start.clientX) / zoom,
        y: box.y + (event.clientY - start.clientY) / zoom,
      });
    }
    setDrag(null);
  };

  if (view.boxes.length === 0 && view.frames.length === 0) return null;

  return (
    <>
      <div className={styles.behind} aria-hidden="true">
        <div className={styles.plane} style={plane}>
          {frames.map((f) => (
            <div
              key={f.scenario.id}
              className={styles.frame}
              data-scenario-frame={f.scenario.id}
              style={{
                left: f.left,
                top: f.top,
                width: f.width,
                height: f.height,
                borderColor: f.scenario.color,
                background: `${f.scenario.color}12`,
              }}
            />
          ))}
          <svg className={styles.edges}>
            {paths.map((p) => (
              <path key={p.id} d={p.d} className={styles.standIn} data-scenario-stand-in="true" />
            ))}
          </svg>
        </div>
      </div>
      <div className={styles.front}>
        <div className={styles.plane} style={plane}>
          {frames.map((f) => (
            <div
              key={f.scenario.id}
              className={styles.frameHeader}
              style={{ left: f.left, top: f.top - 28 }}
            >
              <span className={styles.chip} style={{ background: f.scenario.color }}>
                {f.scenario.name}
              </span>
              <button
                type="button"
                className={styles.headerButton}
                data-testid={`scenario-collapse-${f.scenario.id}`}
                onClick={() => onCollapse(f.scenario.id)}
              >
                Collapse
              </button>
            </div>
          ))}
          {boxes.map(({ box, x, y, layout }) => (
            <div
              key={box.scenario.id}
              className={styles.box}
              data-scenario-box={box.scenario.id}
              data-testid={`scenario-box-${box.scenario.id}`}
              title="Double-click to expand"
              style={{ left: x, top: y, width: layout.width, height: layout.height, borderColor: box.scenario.color }}
              onDoubleClick={() => onExpand(box.scenario.id)}
              onPointerDown={startDrag(box.scenario.id)}
              onPointerMove={moveDrag}
              onPointerUp={endDrag(box)}
            >
              <div className={styles.boxHeader} style={{ background: box.scenario.color }}>
                <span className={styles.boxName}>{box.scenario.name}</span>
                <span className={styles.boxCount}>
                  {box.parts.levers.length} node{box.parts.levers.length === 1 ? "" : "s"}
                </span>
              </div>
              {layout.contextTitle !== undefined && (
                <div className={styles.section} style={{ top: layout.contextTitle }}>
                  Fixed context
                </div>
              )}
              {[...layout.context].map(([id, top]) => (
                <div key={`c-${id}`} className={styles.row} style={{ top }}>
                  <span className={styles.portIn} style={{ borderColor: box.scenario.color }} />
                  <span className={styles.rowLabel}>{labelOf(id)}</span>
                </div>
              ))}
              {layout.outcomeTitle !== undefined && (
                <div className={styles.section} style={{ top: layout.outcomeTitle }}>
                  Outcomes
                </div>
              )}
              {[...layout.outcomes].map(([id, top]) => {
                const status = statusOf(id);
                return (
                  <div key={`o-${id}`} className={styles.row} style={{ top }} data-scenario-outcome={id}>
                    <span className={styles.rowLabel}>{labelOf(id)}</span>
                    <span className={styles.status} data-tone={status.tone}>
                      {status.text}
                    </span>
                    <span className={styles.portOut} style={{ borderColor: box.scenario.color }} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

/** The layers on the canvas, reading the flow for labels and outputs. */
export function CanvasScenarioLayers({ view, editable }: { view: ScenarioCanvasView<any, any>; editable: boolean }) {
  const { nodes, nodeExecStatus } = useFlowContext();
  const actions = useScenarioActions();
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  return (
    <ScenarioLayers
      view={view}
      editable={editable}
      labelOf={(id) => nodeLabel(byId.get(id), id)}
      statusOf={(id) => outputStatus(byId.get(id), nodeExecStatus ?? {})}
      onExpand={(id) => actions.setCollapsed(id, false)}
      onCollapse={(id) => actions.setCollapsed(id, true)}
      onMoveBox={actions.moveBox}
    />
  );
}
