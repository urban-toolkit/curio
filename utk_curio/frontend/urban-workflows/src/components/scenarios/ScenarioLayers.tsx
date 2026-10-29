import React, { useMemo, useRef, useState } from "react";
import { internalsSymbol, useStore, type ReactFlowState } from "reactflow";

import type { SharedKind } from "../../utils/scenarios/scenarioModel";
import type {
  MembershipDots,
  ScenarioBox,
  ScenarioCanvasView,
  ScenarioFrame,
  SharedGroup,
  StandInEnd,
} from "../../utils/scenarios/scenarioCanvasView";
import styles from "./ScenarioLayers.module.css";

/** A collapsed box, a scenario's or a shared group's: its width, and its cards. */
export const BOX_WIDTH = 260;
/** A scenario box's header: the scenario's name, and how to open it. */
const SCENARIO_BOX_HEADER = 58;
/** A shared group's box has its title over it, as its frame does, and how to open it in it. */
const GROUP_BOX_HEADER = 34;
const CARD_HEIGHT = 58;
const CARD_GAP = 8;
const BOX_PAD = 10;
/** Room a frame leaves around its scenario's nodes. */
const FRAME_PAD = 18;
/** How far below a shared node its scenario circles sit. */
const DOTS_GAP = 6;
/** How far above its frame a frame's header sits. */
const FRAME_HEADER_OFFSET = 28;
/** Height of a shared node's row of circles, which the set's outline goes around. */
const DOTS_HEIGHT = 34;
/** How far in from its outline's left corner a set's title starts. */
const SET_TITLE_INSET = 16;
/** Room a scenario set's outline leaves around what it holds. */
const SET_PAD = 32;
/** Room above a scenario's top node that its frame and header take. */
export const FRAME_HEADER_ROOM = FRAME_PAD + FRAME_HEADER_OFFSET;

export interface BoxLayout {
  width: number;
  height: number;
  /** Each node's card, as its offset from the box's top. */
  rows: Map<string, number>;
}

/**
 * Where a box's cards go, one per node under its header. A stand-in edge ends
 * at its card's port, so the box and the edges read this one layout.
 */
function cardsLayout(rows: readonly string[], header: number): BoxLayout {
  const layout: BoxLayout = { width: BOX_WIDTH, height: 0, rows: new Map() };
  let y = header;
  for (const id of rows) {
    layout.rows.set(id, y);
    y += CARD_HEIGHT + CARD_GAP;
  }
  layout.height = y - (rows.length ? CARD_GAP : 0) + BOX_PAD;
  return layout;
}

/** A collapsed scenario's box: its own nodes. */
export function boxLayout(box: ScenarioBox): BoxLayout {
  return cardsLayout(box.rows, SCENARIO_BOX_HEADER);
}

/** A collapsed shared group's box: its nodes. */
export function groupBoxLayout(group: SharedGroup): BoxLayout {
  return cardsLayout(group.nodes, GROUP_BOX_HEADER);
}

const SHARED_TITLE: Record<SharedKind, string> = { context: "Shared context", outcomes: "Shared outcomes" };

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
  /** The kind of node *id* is, as its header names it: Python, Autark… */
  typeOf?: (id: string) => string;
  statusOf: (id: string) => { text: string; tone: "done" | "error" | "stale" | "none" };
  onExpand: (id: string) => void;
  /** Absent on the dashboard: a frame's header then has no Collapse. */
  onCollapse?: (id: string) => void;
  onMoveBox: (id: string, at: { x: number; y: number }) => void;
  /** False in a read-only view: boxes stay where they are. */
  editable: boolean;
  /** The name of the scenario set *id*, over its outline. */
  setNameOf?: (id: string | undefined) => string | undefined;
  /** Absent on the dashboard: a shared group then has nothing to collapse. */
  onSharedCollapse?: (set: string, kind: SharedKind, collapsed: boolean) => void;
  onSharedMove?: (set: string, kind: SharedKind, at: { x: number; y: number }) => void;
}

/**
 * Draws what `scenarioCanvasView` adds to the canvas (#662) beside React Flow,
 * in its coordinates: frames and stand-in edges behind the nodes, boxes and the
 * frames' headers in front. None of it is in React Flow's store.
 */
export function ScenarioLayers({
  view,
  labelOf,
  typeOf,
  statusOf,
  onExpand,
  onCollapse,
  onMoveBox,
  editable,
  setNameOf,
  onSharedCollapse,
  onSharedMove,
}: ScenarioLayersProps) {
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
  const groups = view.groups ?? [];
  const groupBoxes = useMemo(
    () =>
      (view.groups ?? [])
        .filter((g) => g.collapsed)
        .map((group) => {
          const moved = drag && drag.id === group.key;
          return {
            group,
            x: group.x + (moved ? drag.dx : 0),
            y: group.y + (moved ? drag.dy : 0),
            layout: groupBoxLayout(group),
          };
        }),
    [view.groups, drag],
  );
  const dotsOf = new Map<string, MembershipDots>((view.dots ?? []).map((row) => [row.node, row]));
  // The ports a stand-in edge ends at: only those cards show one.
  const ports = new Set(
    view.standIns.flatMap((edge) =>
      [edge.source, edge.target].map((end) => ("box" in end ? `${end.box}|${end.port}|${end.of}` : "")),
    ),
  );
  const hiddenInGroup = new Set(groupBoxes.flatMap((b) => b.group.nodes));

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

  // An expanded shared group's frame: around its nodes and their circles.
  const dotted = new Set((view.dots ?? []).map((row) => row.node));
  const groupFrames = groups
    .filter((g) => !g.collapsed)
    .map((group) => {
      const rects = group.nodes
        .map((id) => geometryOf(internals, id))
        .filter((g): g is Geometry => !!g && g.width > 0)
        .map((g) => ({ ...g, below: dotted.has(g.internal.id) ? DOTS_GAP + DOTS_HEIGHT : 0 }));
      if (rects.length === 0) return null;
      const left = Math.min(...rects.map((r) => r.x)) - FRAME_PAD;
      const top = Math.min(...rects.map((r) => r.y)) - FRAME_PAD;
      const right = Math.max(...rects.map((r) => r.x + r.width)) + FRAME_PAD;
      const bottom = Math.max(...rects.map((r) => r.y + r.height + r.below)) + FRAME_PAD;
      return { group, left, top, width: right - left, height: bottom - top };
    })
    .filter((f): f is NonNullable<typeof f> => !!f);

  // Each scenario set's outline: around its frames and boxes, with their
  // headers, and its shared groups.
  const setOutlines = (view.sets ?? [])
    .map((outline) => {
      const rects: { left: number; top: number; right: number; bottom: number }[] = [];
      for (const f of frames) {
        if (!outline.frames.includes(f.scenario.id)) continue;
        rects.push({ left: f.left, top: f.top - FRAME_HEADER_OFFSET, right: f.left + f.width, bottom: f.top + f.height });
      }
      for (const b of boxes) {
        if (!outline.boxes.includes(b.box.scenario.id)) continue;
        rects.push({ left: b.x, top: b.y, right: b.x + b.layout.width, bottom: b.y + b.layout.height });
      }
      for (const f of groupFrames) {
        if (!outline.groups.includes(f.group.key)) continue;
        rects.push({ left: f.left, top: f.top - FRAME_HEADER_OFFSET, right: f.left + f.width, bottom: f.top + f.height });
      }
      for (const b of groupBoxes) {
        if (!outline.groups.includes(b.group.key)) continue;
        rects.push({
          left: b.x,
          top: b.y - FRAME_HEADER_OFFSET,
          right: b.x + b.layout.width,
          bottom: b.y + b.layout.height,
        });
      }
      if (rects.length === 0) return null;
      const left = Math.min(...rects.map((r) => r.left)) - SET_PAD;
      const top = Math.min(...rects.map((r) => r.top)) - SET_PAD;
      const right = Math.max(...rects.map((r) => r.right)) + SET_PAD;
      const bottom = Math.max(...rects.map((r) => r.bottom)) + SET_PAD;
      return { set: outline.set, left, top, width: right - left, height: bottom - top };
    })
    .filter((o): o is NonNullable<typeof o> => !!o);

  const endPoint = (end: StandInEnd, kind: "source" | "target") => {
    if ("node" in end) {
      const geo = geometryOf(internals, end.node);
      return geo && geo.width > 0 ? handlePoint(geo, kind, end.handle) : null;
    }
    const placed =
      boxes.find((b) => b.box.scenario.id === end.box) ?? groupBoxes.find((b) => b.group.key === end.box);
    if (!placed) return null;
    const row = placed.layout.rows.get(end.of);
    if (row === undefined) return null;
    return {
      x: placed.x + (end.port === "out" ? placed.layout.width : 0),
      y: placed.y + row + CARD_HEIGHT / 2,
    };
  };

  // Under each shared node, its set's circles, centered on its bottom edge.
  const dotRows = (view.dots ?? [])
    .filter((row) => !hiddenInGroup.has(row.node))
    .map((row) => {
      const geo = geometryOf(internals, row.node);
      if (!geo || geo.width <= 0) return null;
      return { row, left: geo.x + geo.width / 2, top: geo.y + geo.height + DOTS_GAP };
    })
    .filter((d): d is NonNullable<typeof d> => !!d);

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
  const endDrag =
    (id: string, at: { x: number; y: number }, onMove: (at: { x: number; y: number }) => void) =>
    (event: React.PointerEvent) => {
      const start = dragStart.current;
      dragStart.current = null;
      if (start?.moved && start.id === id) {
        onMove({ x: at.x + (event.clientX - start.clientX) / zoom, y: at.y + (event.clientY - start.clientY) / zoom });
      }
      setDrag(null);
    };

  /** A node's card in a collapsed box: its kind, its title, and what it shows on the right. */
  const card = (
    boxKey: string,
    id: string,
    top: number,
    side: React.ReactNode,
    portColor: string,
    rowAttr: Record<string, string>,
  ) => {
    const title = labelOf(id);
    const kind = typeOf?.(id);
    const portTop = top + CARD_HEIGHT / 2 - 5;
    return (
      <React.Fragment key={id}>
        <div className={styles.card} style={{ top, height: CARD_HEIGHT }} {...rowAttr}>
          <div className={styles.cardTop}>
            {kind && kind !== title ? <span className={styles.cardKind}>{kind}</span> : <span />}
            {side}
          </div>
          <div className={styles.cardTitle}>{title}</div>
        </div>
        {ports.has(`${boxKey}|in|${id}`) && (
          <span className={styles.portIn} style={{ top: portTop, borderColor: portColor }} />
        )}
        {ports.has(`${boxKey}|out|${id}`) && (
          <span className={styles.portOut} style={{ top: portTop, borderColor: portColor }} />
        )}
      </React.Fragment>
    );
  };

  const circles = (id: string) => {
    const row = dotsOf.get(id);
    if (!row) return null;
    return (
      <span className={styles.cardDots} data-scenario-dots={id}>
        {row.dots.map((d) => (
          <span
            key={d.scenario}
            className={styles.cardDot}
            data-member={d.member ? "true" : "false"}
            data-scenario={d.scenario}
            style={d.member ? { background: d.color, borderColor: d.color } : { borderColor: d.color }}
          />
        ))}
      </span>
    );
  };

  if (
    view.boxes.length === 0 &&
    view.frames.length === 0 &&
    dotRows.length === 0 &&
    setOutlines.length === 0 &&
    groups.length === 0
  ) {
    return null;
  }

  return (
    <>
      <div className={styles.behind} aria-hidden="true">
        <div className={styles.plane} style={plane}>
          {setOutlines.map((o) => (
            <div
              key={o.set}
              className={styles.setOutline}
              data-scenario-set-outline={o.set}
              style={{ left: o.left, top: o.top, width: o.width, height: o.height }}
            />
          ))}
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
          {groupFrames.map((f) => (
            <div
              key={f.group.key}
              className={styles.groupFrame}
              data-shared-group={f.group.key}
              style={{ left: f.left, top: f.top, width: f.width, height: f.height }}
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
          {setOutlines.map((o) => (
            <div
              key={`title-${o.set}`}
              className={styles.setTitle}
              data-scenario-set-title={o.set}
              style={{ left: o.left + SET_TITLE_INSET, top: o.top }}
            >
              Scenario set: {setNameOf?.(o.set) ?? o.set}
            </div>
          ))}
          {dotRows.map(({ row, left, top }) => {
            const uses = row.dots.filter((d) => d.member).map((d) => d.name);
            return (
              <div
                key={`dots-${row.node}`}
                className={styles.dots}
                data-scenario-dots={row.node}
                data-tooltip={`Used by ${uses.join(", ")}`}
                style={{ left, top }}
              >
                {row.dots.map((d) => (
                  <span
                    key={d.scenario}
                    className={styles.dot}
                    data-member={d.member ? "true" : "false"}
                    data-scenario={d.scenario}
                    style={d.member ? { background: d.color, borderColor: d.color } : { borderColor: d.color }}
                  />
                ))}
              </div>
            );
          })}
          {frames.map((f) => (
            <div
              key={f.scenario.id}
              className={styles.frameHeader}
              data-scenario-header={f.scenario.id}
              style={{ left: f.left, top: f.top - FRAME_HEADER_OFFSET }}
            >
              <span className={styles.chip} style={{ background: f.scenario.color }}>
                {f.scenario.name}
              </span>
              {onCollapse && (
                <button
                  type="button"
                  className={styles.headerButton}
                  data-testid={`scenario-collapse-${f.scenario.id}`}
                  onClick={() => onCollapse(f.scenario.id)}
                >
                  Collapse
                </button>
              )}
            </div>
          ))}
          {groupFrames.map((f) => (
            <div
              key={`head-${f.group.key}`}
              className={styles.frameHeader}
              data-shared-header={f.group.key}
              style={{ left: f.left, top: f.top - FRAME_HEADER_OFFSET }}
            >
              <span className={styles.groupChip}>{SHARED_TITLE[f.group.kind]}</span>
              {onSharedCollapse && (
                <button
                  type="button"
                  className={styles.headerButton}
                  data-testid={`shared-collapse-${f.group.set}-${f.group.kind}`}
                  onClick={() => onSharedCollapse(f.group.set, f.group.kind, true)}
                >
                  Collapse
                </button>
              )}
            </div>
          ))}
          {groupBoxes.map(({ group, x, y, layout }) => (
            <React.Fragment key={group.key}>
              <div
                className={styles.frameHeader}
                data-shared-header={group.key}
                style={{ left: x, top: y - FRAME_HEADER_OFFSET }}
              >
                <span className={styles.groupChip}>{SHARED_TITLE[group.kind]}</span>
              </div>
              <div
                className={styles.groupBox}
                data-shared-box={group.key}
                data-testid={`shared-box-${group.set}-${group.kind}`}
                data-tooltip="Double-click to expand"
                style={{ left: x, top: y, width: layout.width, height: layout.height }}
                onDoubleClick={() => onSharedCollapse?.(group.set, group.kind, false)}
                onPointerDown={startDrag(group.key)}
                onPointerMove={moveDrag}
                onPointerUp={endDrag(group.key, group, (at) => onSharedMove?.(group.set, group.kind, at))}
              >
                <div className={styles.groupHint}>Double-click to expand</div>
                {[...layout.rows].map(([id, top]) =>
                  card(group.key, id, top, circles(id), "var(--curio-text-secondary)", { "data-shared-row": id }),
                )}
              </div>
            </React.Fragment>
          ))}
          {boxes.map(({ box, x, y, layout }) => (
            <div
              key={box.scenario.id}
              className={styles.box}
              data-scenario-box={box.scenario.id}
              data-testid={`scenario-box-${box.scenario.id}`}
              data-tooltip="Double-click to expand"
              style={{
                left: x,
                top: y,
                width: layout.width,
                height: layout.height,
                borderColor: box.scenario.color,
                background: `linear-gradient(${box.scenario.color}1f, ${box.scenario.color}1f), var(--curio-card-bg)`,
              }}
              onDoubleClick={() => onExpand(box.scenario.id)}
              onPointerDown={startDrag(box.scenario.id)}
              onPointerMove={moveDrag}
              onPointerUp={endDrag(box.scenario.id, box, (at) => onMoveBox(box.scenario.id, at))}
            >
              <div className={styles.boxHeader}>
                <span className={styles.boxDot} style={{ background: box.scenario.color }} />
                <span className={styles.boxName}>{box.scenario.name}</span>
              </div>
              <div className={styles.boxHint}>Double-click to expand</div>
              {[...layout.rows].map(([id, top]) => {
                const status = statusOf(id);
                const side = status.text ? (
                  <span className={styles.status} data-tone={status.tone}>
                    {status.text}
                  </span>
                ) : null;
                return card(box.scenario.id, id, top, side, box.scenario.color, { "data-scenario-row": id });
              })}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

const NO_STATUS = () => ({ text: "", tone: "none" as const });
const NOTHING = () => {};

/**
 * The dashboard's: each scenario's column of tiles framed, under a header in
 * its color (#662). No box, nothing to collapse or move.
 */
export function DashboardScenarioLayers({ frames }: { frames: ScenarioFrame[] }) {
  const view = useMemo(
    () => ({ nodes: [], edges: [], boxes: [], frames, standIns: [], dots: [], sets: [] }),
    [frames],
  );
  return (
    <ScenarioLayers
      view={view}
      editable={false}
      labelOf={(id) => id}
      statusOf={NO_STATUS}
      onExpand={NOTHING}
      onMoveBox={NOTHING}
    />
  );
}
