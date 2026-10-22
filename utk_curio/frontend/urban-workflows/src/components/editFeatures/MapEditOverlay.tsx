/**
 * What a Map Edits node does on an Autark map it feeds and is linked to
 * (#662): an overlay over the map's canvas, drawn through the map's own
 * camera, where the layer the node works on is picked, drawn into and
 * reshaped (`utils/editFeatures/mapEditBus`). It is mounted only on a map a
 * Map Edits node feeds.
 *
 * The map keeps its own gestures: a drag pans it and the wheel zooms it, in
 * every mode. A click is the node's:
 *
 * - pick: a click picks the feature under it (shift-click adds it, or takes it
 *   out): the map's selection, which the interaction edge carries to the node
 *   as a selection crosses between two views (`mapEditSelection`);
 * - draw: a click places a point, or a corner of a line or an area, and a
 *   double-click, Enter or Finish ends it; Backspace takes back a corner and
 *   Escape gives up;
 * - reshape: drag a corner, click or drag a midpoint to add one, alt-click a
 *   part of a feature of several to remove it, alt-click a corner to
 *   delete it; move: drag the picked feature to move it whole.
 *
 * Only what the action is about is drawn here: what the node selects (its
 * pick, or the features a rule matches), which comes back on the interaction
 * edge, the handles and the shape being drawn. The map draws the layers, with
 * the edits made, again after each one.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFlowContext } from "../../providers/FlowProvider";
import type { SelectionId } from "../../utils/references/selectionTags";
import type { Geometry } from "../../utils/editFeatures/editFeatures";
import { kindOf, type EditedFeature } from "../../utils/editFeatures/layerModel";
import { editMap, editMapLayerId, useMapEdit } from "../../utils/editFeatures/mapEditBus";
import { editSelection, selectedIdsIn, toggledIds } from "../../utils/editFeatures/mapEditSelection";
import { partsOf, withoutPart } from "../../utils/editFeatures/geometryParts";
import { toRings } from "../../utils/editFeatures/geometryRings";
import {
  cameraKey,
  cameraView,
  drawnSize,
  fromAbove,
  hitAt,
  isFromAbove,
  projectionOf,
  setBuildingsFlat,
  shifted,
  showView,
  tiltedAgain,
  type CameraView,
  type XY,
} from "../../utils/editFeatures/mapEditGeometry";
import { isTypingTarget } from "../canvasKeyBindings";
import styles from "./MapEditOverlay.module.css";

/** How many matched or picked features are outlined at most. */
const MAX_OUTLINED = 3000;

type Gesture =
  | { kind: "click"; start: XY; moved: boolean; shift: boolean }
  | { kind: "corner" | "mid"; ring: number; index: number; shape?: Geometry }
  | { kind: "move"; origin: Geometry; at: XY };

/** The id the shape drawn but not yet added goes by, among the outlines. */
const DRAFT = "__drawn__";

export default function MapEditOverlay({ mapId }: { mapId: string }) {
  const { session, map } = useMapEdit(mapId);
  const active = session?.active ?? null;
  // The map's node: the selections the interaction edge brings it, and where
  // its own selection goes.
  const flow = useFlowContext() as any;
  const mapData = (flow?.nodes ?? []).find((n: any) => n.id === mapId)?.data;
  const sendSelection = mapData?.interactionsCallback ?? flow?.interactionsCallback;
  const box = useRef<HTMLDivElement>(null);
  const [, setTick] = useState(0);
  const [draft, setDraft] = useState<XY[]>([]);
  const [hover, setHover] = useState<XY | null>(null);
  const [dragShape, setDragShape] = useState<{ id: SelectionId; geometry: Geometry } | null>(null);
  const gesture = useRef<Gesture | null>(null);
  // The map's tilt before an action looked from above, put back after it.
  const tilt = useRef<CameraView | null>(null);
  const flatNow = useRef(false);

  // Draw again whenever the camera moves, and look from
  // above again when the map is tilted during the action.
  useEffect(() => {
    if (!active || !map) return;
    let frame = 0;
    let last = "";
    const loop = () => {
      if (flatNow.current) setBuildingsFlat(map, true);
      const key = cameraKey(map);
      if (key !== last) {
        last = key;
        const view = flatNow.current ? cameraView(map) : null;
        if (view && !isFromAbove(view)) {
          if (!tilt.current) tilt.current = view;
          showView(map, fromAbove(view));
        }
        setTick((t) => t + 1);
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [active, map]);

  const mode = active?.mode ?? "select";
  const kind = active?.kind ?? "points";
  useEffect(() => setDraft([]), [mode, kind, active?.table]);

  const projection = active && map ? projectionOf(map, active.geographic) : null;
  const features = active?.features ?? [];
  const shown = useMemo(
    () => features.map((f) => (dragShape && f.id !== null && String(f.id) === String(dragShape.id) ? { ...f, geometry: dragShape.geometry } : f)),
    [features, dragShape],
  );
  // What the node selects on this layer: its pick, or what a rule matches,
  // which the interaction edge brings back to the map.
  const selected = useMemo<SelectionId[]>(
    () =>
      active
        ? selectedIdsIn(mapData?.interactions, (from, layer) => from === session?.interactionId && (layer ?? active.table) === active.table, features) ?? []
        : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mapData?.interactions, session?.interactionId, active?.table, features],
  );
  const selectedKeys = useMemo(() => new Set([...selected.map(String), ...(active?.draft ? [DRAFT] : [])]), [selected, active?.draft]);
  const selectedOne = selected.length === 1 ? shown.find((f) => f.id !== null && String(f.id) === String(selected[0])) : undefined;
  const handles = selectedOne?.geometry && (mode === "reshape" || mode === "move") ? toRings(selectedOne.geometry) : null;

  /**
   * A click that picks: the map's selection, *id*'s feature alone, or with
   * shift added to what the node selects now or taken out of it; a click on
   * nothing clears it. Sent through the map's node, as its own pick is, keyed
   * by the layer's id column. Not while a shape waits to be added, nor while
   * a rule picks.
   */
  const pick = (id: SelectionId | null, additive: boolean) => {
    if (!active?.key || active.draft || active.rule) return;
    const ids = id === null ? (additive ? selected : []) : additive ? toggledIds(selected, id) : [id];
    sendSelection?.(editSelection(ids, active.key, active.table), mapId);
  };

  // Every layer is worked on in 2D, from straight above with the buildings
  // drawn flat: outlines and handles are on the ground, and a raised roof,
  // tilted or off the middle of the view, is not over its footprint. One fixed
  // view for points, lines and areas alike. The tilt and the heights come back
  // after, around where the map then looks.
  const flat = !!active;
  flatNow.current = flat;
  useEffect(() => {
    if (!flat || !map) return;
    const view = cameraView(map);
    if (!view || isFromAbove(view)) return;
    if (!tilt.current) tilt.current = view;
    showView(map, fromAbove(view));
  }, [flat, map]);
  useEffect(() => {
    const restore = () => {
      const before = tilt.current;
      tilt.current = null;
      const current = editMap(mapId);
      setBuildingsFlat(current, false);
      const now = cameraView(current);
      if (before && now) showView(current, tiltedAgain(now, before));
    };
    if (!flat) restore();
    return () => {
      if (flat) restore();
    };
  }, [flat, mapId]);

  const finishDraft = useCallback(() => {
    if (!session) return;
    if (kind === "lines" && draft.length >= 2) session.onDrawn({ type: "LineString", coordinates: draft });
    else if (kind === "areas" && draft.length >= 3) session.onDrawn({ type: "Polygon", coordinates: [[...draft, draft[0]]] });
    else return;
    setDraft([]);
  }, [session, kind, draft]);

  // The latest of everything the listeners read, so they are added once.
  // How big the map draws the layer's points and lines, for what a click reaches.
  const size = drawnSize(map, active?.table ? editMapLayerId(mapId, active.table) : undefined);
  const live = useRef({ session, active, projection, shown, selectedOne, handles, mode, kind, draft, finishDraft, dragShape, size, pick });
  live.current = { session, active, projection, shown, selectedOne, handles, mode, kind, draft, finishDraft, dragShape, size, pick };

  useEffect(() => {
    const host = box.current?.parentElement;
    if (!host || !active) return;
    const local = (event: MouseEvent): XY => {
      const p = live.current.projection;
      const rect = host.getBoundingClientRect();
      // An event the map's zoom fix sent again (autkMapZoom) is in the map's own pixels already.
      if ((event as any).__curioMapZoomCorrected === true) return [event.clientX - rect.left, event.clientY - rect.top];
      // Under React Flow's zoom the node is scaled: client pixels to the map's own.
      const sx = p && rect.width > 0 ? p.width / rect.width : 1;
      const sy = p && rect.height > 0 ? p.height / rect.height : 1;
      return [(event.clientX - rect.left) * sx, (event.clientY - rect.top) * sy];
    };
    const stop = (event: Event) => {
      event.stopPropagation();
      event.preventDefault();
    };
    const onDown = (event: PointerEvent) => {
      const { projection: p, selectedOne: one, handles: h, mode: m, shown: all, size: z } = live.current;
      // Heard on the window, ahead of the page's own listeners: a press on this map only.
      if (!p || event.button !== 0 || !host.contains(event.target as Node)) return;
      const target = event.target as Element;
      // The overlay's own buttons are buttons.
      if (target.closest?.("[data-map-edit-ui]")) return;
      const ring = target.getAttribute?.("data-ring");
      const index = target.getAttribute?.("data-index");
      if (h && one && ring !== null && index !== null && ring !== undefined) {
        stop(event);
        const r = Number(ring), i = Number(index);
        if (event.altKey && target.getAttribute("data-handle") === "corner") {
          const rings = h.rings.map((rr) => [...rr]);
          const min = h.closed[r] ? 3 : kindOf(one.geometry) === "points" ? 1 : 2;
          if (rings[r].length > min) {
            rings[r].splice(i, 1);
            live.current.session?.onReshape(one.id as SelectionId, h.rebuild(rings));
          }
          return;
        }
        gesture.current = { kind: target.getAttribute("data-handle") === "mid" ? "mid" : "corner", ring: r, index: i };
        return;
      }
      const s = local(event);
      // Moving points, an alt-click inside one part of a feature of several
      // takes that part away (a corner's own alt-click deletes the corner).
      if (m === "reshape" && event.altKey && one?.geometry && one.id !== null) {
        const parts = partsOf(one.geometry);
        const hit = parts.length > 1 ? parts.findIndex((part) => hitAt([{ ...one, geometry: part }], s, p, z) !== null) : -1;
        const rest = hit >= 0 ? withoutPart(one.geometry, hit) : null;
        if (rest) {
          stop(event);
          live.current.session?.onReshape(one.id as SelectionId, rest);
          return;
        }
      }
      // Moving a feature whole is a shift-drag on it; a plain drag pans the map.
      if (m === "move" && event.shiftKey && one?.geometry && hitAt(all, s, p, z)?.id === one.id) {
        stop(event);
        gesture.current = { kind: "move", origin: one.geometry, at: p.toData(s[0], s[1]) };
        host.style.cursor = "grabbing";
        return;
      }
      // A press the map may turn into a pan: a click only if it stays put.
      gesture.current = { kind: "click", start: s, moved: false, shift: event.shiftKey };
    };
    const onMove = (event: PointerEvent) => {
      const { projection: p, selectedOne: one, mode: m } = live.current;
      if (!p) return;
      const s = local(event);
      if (m === "draw") setHover(p.toData(s[0], s[1]));
      const g = gesture.current;
      if (!g) {
        // Moving it whole, the picked feature shows it can be grabbed with shift held.
        const grab = m === "move" && event.shiftKey && !!one?.geometry && hitAt([one], s, p, live.current.size) !== null;
        host.style.cursor = grab ? "grab" : "";
        return;
      }
      // Shift-drag would tilt and turn Autark's camera, which the view from
      // above then snaps back, a flicker each move: the map never sees it.
      if (event.shiftKey && (event.buttons & 1) === 1) stop(event);
      if (g.kind === "click") {
        if (Math.hypot(s[0] - g.start[0], s[1] - g.start[1]) > 6) g.moved = true;
        return;
      }
      // A drag of the node's own is not the map's: autk-map starts a pan on
      // a move with the button held even when it never saw the press, and
      // panning under the pointer would leave the feature where it was.
      stop(event);
      if (!one?.geometry || one.id === null) return;
      const at = p.toData(s[0], s[1]);
      if (g.kind === "move") {
        setDragShape({ id: one.id, geometry: shifted(g.origin, at[0] - g.at[0], at[1] - g.at[1]) });
        return;
      }
      // The shape the drag started on, with a midpoint's corner once added.
      const base = toRings(g.shape ?? one.geometry);
      const rings = base.rings.map((rr) => [...rr]);
      if (g.kind === "corner") rings[g.ring][g.index] = at;
      else {
        // A midpoint adds its corner once; the rest of the drag moves it.
        rings[g.ring].splice(g.index + 1, 0, at);
        gesture.current = { kind: "corner", ring: g.ring, index: g.index + 1, shape: base.rebuild(rings) };
      }
      setDragShape({ id: one.id, geometry: base.rebuild(rings) });
    };
    const onUp = (event: PointerEvent) => {
      const g = gesture.current;
      gesture.current = null;
      if (g?.kind === "move") host.style.cursor = "grab";
      const { projection: p, session: s, mode: m, kind: k, shown: all, dragShape: dragged, size: z } = live.current;
      if (!g || !p || !s) return;
      // A click on a midpoint adds its corner there; no drag is needed.
      if (g.kind === "mid") {
        const one = live.current.selectedOne;
        if (one?.geometry && one.id !== null) {
          const base = toRings(one.geometry);
          const rings = base.rings.map((rr) => [...rr]);
          const a = rings[g.ring][g.index], b = rings[g.ring][(g.index + 1) % rings[g.ring].length];
          rings[g.ring].splice(g.index + 1, 0, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
          s.onReshape(one.id as SelectionId, base.rebuild(rings));
        }
        setDragShape(null);
        return;
      }
      if (g.kind !== "click") {
        if (dragged) s.onReshape(dragged.id, dragged.geometry);
        setDragShape(null);
        return;
      }
      if (g.moved) return;
      const at = p.toData(g.start[0], g.start[1]);
      if (m === "draw") {
        if (k === "points") s.onDrawn({ type: "Point", coordinates: at });
        else setDraft((current) => [...current, at]);
        return;
      }
      if (m === "reshape" || m === "move") {
        const found = hitAt(all, g.start, p, z);
        if (found) live.current.pick(found.id, false);
        return;
      }
      live.current.pick(hitAt(all, g.start, p, z)?.id ?? null, g.shift);
    };
    const onDouble = (event: MouseEvent) => {
      // The map's own double-click pick is not the node's.
      stop(event);
      if (live.current.mode !== "draw") return;
      // Its two clicks placed two corners at one point: keep one.
      setDraft((current) => (current.length >= 2 ? current.slice(0, -1) : current));
      setTimeout(() => live.current.finishDraft(), 0);
    };
    // A click on the map is the node's, not a pick of the map's own.
    const onClick = (event: MouseEvent) => {
      if (!(event.target as Element).closest?.("[data-map-edit-ui]")) event.stopPropagation();
    };
    const onKey = (event: KeyboardEvent) => {
      if (live.current.mode !== "draw" || isTypingTarget(event.target)) return;
      let handled = true;
      if (event.key === "Enter") live.current.finishDraft();
      else if (event.key === "Escape") setDraft([]);
      else if (event.key === "Backspace" && live.current.draft.length > 0) setDraft((current) => current.slice(0, -1));
      else handled = false;
      if (handled) stop(event);
    };
    window.addEventListener("pointerdown", onDown, true);
    host.addEventListener("dblclick", onDouble, true);
    host.addEventListener("click", onClick, true);
    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("pointerup", onUp, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      host.removeEventListener("dblclick", onDouble, true);
      host.removeEventListener("click", onClick, true);
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("keydown", onKey, true);
      host.style.cursor = "";
    };
  }, [!!active]);

  if (!active) return null;
  // The box is there before the camera is, so the listeners have their host.
  if (!projection) return <div ref={box} data-testid="map-edit-overlay" className={styles.overlay} />;
  const p = projection;
  const path = (geometry: Geometry) => {
    const { rings, closed } = toRings(geometry);
    return rings.map((ring, r) => ring.map((xy, i) => `${i === 0 ? "M" : "L"}${p.toScreen(xy).map((v) => v.toFixed(1)).join(" ")}`).join(" ") + (closed[r] ? " Z" : "")).join(" ");
  };
  /** A ring around a feature too small to see on the map as it is zoomed. */
  const SMALL_PX = 14;
  const outline = (f: EditedFeature, dashed: boolean) => {
    if (!f.geometry) return null;
    const id = String(f.id);
    if (kindOf(f.geometry) === "points") {
      return toRings(f.geometry).rings.map((ring, r) => {
        const [x, y] = p.toScreen(ring[0]);
        // Around the point as the map draws it.
        const radius = Math.max(7, p.pixels(ring[0], size.pointRadius) + 2);
        return (
          <g key={`${id}-${r}`}>
            <circle className={styles.casing} cx={x} cy={y} r={radius + 2} strokeWidth={4} />
            <circle className={`${styles.outline} ${styles.point}`} cx={x} cy={y} r={radius} strokeWidth={2.5} strokeDasharray={dashed ? "3 2" : undefined} />
          </g>
        );
      });
    }
    const d = path(f.geometry);
    const screen = toRings(f.geometry).rings.flat().map(p.toScreen);
    const xs = screen.map(([x]) => x), ys = screen.map(([, y]) => y);
    const small = screen.length > 0 && Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) < SMALL_PX;
    const width = dashed ? 2 : 3.5;
    return (
      <g key={id}>
        <path className={styles.casing} d={d} strokeWidth={width + 3} />
        <path
          className={`${styles.outline} ${kindOf(f.geometry) === "areas" ? styles.area : ""}`}
          d={d}
          strokeWidth={width}
          strokeDasharray={dashed ? "5 3" : undefined}
          fillRule="evenodd"
        />
        {small ? (
          <circle
            className={styles.outline}
            cx={(Math.max(...xs) + Math.min(...xs)) / 2}
            cy={(Math.max(...ys) + Math.min(...ys)) / 2}
            r={12}
            strokeWidth={2.5}
            strokeDasharray={dashed ? "3 2" : undefined}
          />
        ) : null}
      </g>
    );
  };
  // What the node selects, and the shape drawn but not yet added, outlined on
  // the ground where the map draws them (buildings flat), in the map's
  // highlight: what a rule matches dashed, as it is kept matching later.
  const withDraft: EditedFeature[] = active.draft ? [...shown, { id: DRAFT, geometry: active.draft, properties: {}, status: "added" }] : shown;
  const outlined = withDraft.filter((f) => f.id !== null && selectedKeys.has(String(f.id))).slice(0, MAX_OUTLINED);
  const picked = active.rule ? [] : outlined;
  const matched = active.rule ? outlined : [];
  const draftScreen = draft.map(p.toScreen);
  const hoverScreen = hover && mode === "draw" && draft.length > 0 ? p.toScreen(hover) : null;
  const noun = active.noun;
  const parts = selectedOne?.geometry ? partsOf(selectedOne.geometry).length : 0;
  const tip =
    mode === "draw"
      ? kind === "points"
        ? `Click the map to place a ${noun}. Drag to pan.`
        : "Click the map to add points. Double-click or press Enter to finish, or Esc to cancel."
      : mode === "reshape"
        ? kind === "points"
          ? `Drag the ${noun} to move it.`
          : `Drag a corner to move it. Click or drag a midpoint to add one, and alt-click a corner to delete it.${parts > 1 ? " Alt-click inside a part to remove it." : ""}`
        : mode === "move"
          ? `Shift-drag the ${noun} to move it. Drag to pan.`
          : `Click a ${noun} to pick it, and shift-click to add one. Drag to pan.`;
  // Changing a shape, Done goes back to panning.
  const shaping = mode === "reshape" || mode === "move";
  const last = draftScreen[draftScreen.length - 1];

  return (
    <div ref={box} data-testid="map-edit-overlay" data-edit-mode={mode} data-edit-layer={active.table} className={`${styles.overlay} ${mode === "draw" ? styles.drawing : ""}`}>
      <svg width={p.width} height={p.height} className={styles.svg} aria-hidden="true">
        {matched.map((f) => outline(f, true))}
        {picked.map((f) => outline(f, false))}
        {handles
          ? handles.rings.map((ring, r) => (
              <g key={`ring-${r}`} className={styles.handles}>
                {mode === "reshape" && ring.length > 1
                  ? ring.slice(0, handles.closed[r] ? ring.length : ring.length - 1).map((xy, i) => {
                      const next = ring[(i + 1) % ring.length];
                      const [x, y] = p.toScreen([(xy[0] + next[0]) / 2, (xy[1] + next[1]) / 2]);
                      return <circle key={`m${i}-${selectedOne?.id}`} className={`${styles.handle} ${styles.mid}`} data-handle="mid" data-ring={r} data-index={i} cx={x} cy={y} r={4} strokeWidth={1.5} />;
                    })
                  : null}
                {mode === "reshape"
                  ? ring.map((xy, i) => {
                      const [x, y] = p.toScreen(xy);
                      return <circle key={`c${i}-${selectedOne?.id}`} className={`${styles.handle} ${styles.corner}`} data-handle="corner" data-ring={r} data-index={i} cx={x} cy={y} r={6} strokeWidth={2} />;
                    })
                  : null}
              </g>
            ))
          : null}
        {draftScreen.length > 0 ? (
          <>
            <polyline
              className={`${styles.outline} ${kind === "areas" ? styles.draft : ""}`}
              points={[...draftScreen, ...(hoverScreen ? [hoverScreen] : [])].map((pt) => pt.join(",")).join(" ")}
              strokeWidth={3}
            />
            {draftScreen.map(([x, y], i) => (
              <circle key={i} className={styles.vertex} cx={x} cy={y} r={5} strokeWidth={2.5} />
            ))}
          </>
        ) : null}
      </svg>
      {last ? (
        <span data-testid="map-edit-draft-label" className={styles.draftLabel} style={{ left: last[0] + 10, top: last[1] - 30 }}>
          New {noun} · {draft.length} point{draft.length === 1 ? "" : "s"}
        </span>
      ) : null}
      <div data-map-edit-ui="true" className={styles.toolbar}>
        <span data-testid="map-edit-tip" className={styles.tip}>
          {tip}
        </span>
        {shaping && session?.onShapeDone ? (
          <button type="button" data-testid="map-edit-done" className={`nodrag nopan ${styles.button}`} onPointerDown={(e) => e.stopPropagation()} onClick={() => session.onShapeDone?.()}>
            Done
          </button>
        ) : null}
        {mode === "draw" && kind !== "points" ? (
          <button
            type="button"
            data-testid="map-edit-finish"
            className={`nodrag nopan ${styles.button}`}
            disabled={draft.length < (kind === "areas" ? 3 : 2)}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => finishDraft()}
          >
            Finish
          </button>
        ) : null}
      </div>
    </div>
  );
}
