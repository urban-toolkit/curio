/**
 * What a Map Edits node does on an Autark map it feeds and is linked to
 * (#662): it hears the pointer on the map, read through the map's own
 * camera, where the layer the node works on is picked, drawn into and
 * reshaped (`utils/editFeatures/mapEditBus`), and holds the tip with its
 * buttons. It is mounted only on a map a Map Edits node feeds.
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
 * Nothing is drawn over the map. What the node selects (its pick, or the
 * features a rule matches), which comes back on the interaction edge, the map
 * lights with Autark's own highlight, and the drawing tools are layers of the
 * map itself (`mapEditLayers`): the shape being drawn and its corners, a shape
 * waiting to be added, and the picked feature while it is reshaped or moved,
 * with its corners and midpoints, which a press takes where the map shows
 * them. The map draws the layers, with the edits made, again after each one.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFlowContext } from "../../providers/FlowProvider";
import type { SelectionId } from "../../utils/references/selectionTags";
import { withArticle, type Geometry } from "../../utils/editFeatures/editFeatures";
import { kindOf } from "../../utils/editFeatures/layerModel";
import { editMap, editMapLayerId, editMapPositions, useMapEdit } from "../../utils/editFeatures/mapEditBus";
import { editSelection, selectedIdsIn, toggledIds, type SentSelection } from "../../utils/editFeatures/mapEditSelection";
import { partsOf, withoutPart } from "../../utils/editFeatures/geometryParts";
import { handlesOf, toRings } from "../../utils/editFeatures/geometryRings";
import { showMapEditTools, type MapEditTools } from "../../utils/editFeatures/mapEditLayers";
import {
  cameraKey,
  cameraView,
  drawnSize,
  fromAbove,
  handleAt,
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

type Gesture =
  | { kind: "click"; start: XY; moved: boolean; shift: boolean }
  | { kind: "corner" | "mid"; ring: number; index: number; shape?: Geometry }
  | { kind: "move"; origin: Geometry; at: XY };

/** A screen position to a tenth of a pixel. */
const tenth = (v: number) => Math.round(v * 10) / 10;

export default function MapEditOverlay({
  mapId,
  sendSelection,
}: {
  mapId: string;
  /** Sends a pick as the map's own selection, as autk-map's pick is sent. */
  sendSelection: (selection: SentSelection) => void;
}) {
  const { session, map } = useMapEdit(mapId);
  const active = session?.active ?? null;
  // The map's node: the selections the interaction edge brings it.
  const flow = useFlowContext() as any;
  const mapData = (flow?.nodes ?? []).find((n: any) => n.id === mapId)?.data;
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
  const selectedOne = selected.length === 1 ? shown.find((f) => f.id !== null && String(f.id) === String(selected[0])) : undefined;
  // The picked feature's corners and midpoints, while its points are moved.
  const reshaped = selectedOne?.geometry && mode === "reshape" ? toRings(selectedOne.geometry) : null;
  const handles = reshaped ? handlesOf(reshaped) : null;

  // The picked feature, while it is reshaped or moved, is drawn by the tools,
  // each of its parts, and skipped where its layer draws it.
  const changing = (mode === "reshape" || mode === "move") && selectedOne && selectedOne.id !== null ? selectedOne.id : null;
  const changingKey = changing === null ? null : String(changing);
  const hiddenPositions = useMemo(
    () => (changing !== null && active?.key ? editMapPositions(mapId, active.table, active.key, changing) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [map, mapId, active?.table, active?.key, changingKey],
  );
  const changed = useMemo(() => {
    const parts = new Map<string, Geometry>();
    for (const f of shown) if (changingKey !== null && f.geometry && f.id !== null && String(f.id) === changingKey) parts.set(JSON.stringify(f.geometry), f.geometry);
    return [...parts.values()];
  }, [shown, changingKey]);

  // The tools, drawn by the map as layers of its own: a shape waiting to be
  // added, the feature being reshaped or moved with its handles, and the
  // shape being drawn, its corners and the pointer.
  const tools: MapEditTools | null =
    active && projection
      ? {
          shapes: [...(active.draft ? [active.draft] : []), ...changed],
          path: mode === "draw" && draft.length > 0 ? [...draft, ...(hover ? [hover] : [])] : [],
          corners: [...(mode === "draw" ? draft : []), ...(handles?.corners.map((c) => c.at) ?? [])],
          midpoints: handles?.midpoints.map((c) => c.at) ?? [],
          hidden: changing !== null && hiddenPositions.length > 0 ? { layer: editMapLayerId(mapId, active.table), positions: hiddenPositions } : null,
        }
      : null;
  const geographic = !!active?.geographic;
  useEffect(() => {
    showMapEditTools(map, tools, geographic);
  });
  // A map replaced by the next draw, or left, keeps none of them.
  useEffect(() => () => showMapEditTools(map, null, false), [map]);

  /**
   * A click that picks: the map's selection, *id*'s feature alone, or with
   * shift added to what the node selects now or taken out of it; a click on
   * nothing clears it. Sent as the map's own pick is, keyed by the layer's id
   * column. Not while a shape waits to be added, nor while a rule picks.
   */
  const pick = (id: SelectionId | null, additive: boolean) => {
    if (!active?.key || active.draft || active.rule) return;
    const ids = id === null ? (additive ? selected : []) : additive ? toggledIds(selected, id) : [id];
    sendSelection(editSelection(ids, active.key, active.table));
  };

  // Every layer is worked on in 2D, from straight above with the buildings
  // drawn flat: the tools are on the ground, and a raised roof, tilted or off
  // the middle of the view, is not over its footprint. One fixed view for
  // points, lines and areas alike. The tilt and the heights come back after,
  // around where the map then looks.
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
  const live = useRef({ session, active, projection, shown, selectedOne, reshaped, handles, mode, kind, draft, finishDraft, dragShape, size, pick });
  live.current = { session, active, projection, shown, selectedOne, reshaped, handles, mode, kind, draft, finishDraft, dragShape, size, pick };

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
      const { projection: p, selectedOne: one, reshaped: h, handles: k, mode: m, shown: all, size: z } = live.current;
      // Heard on the window, ahead of the page's own listeners: a press on this map only.
      if (!p || event.button !== 0 || !host.contains(event.target as Node)) return;
      // The overlay's own buttons are buttons.
      if ((event.target as Element).closest?.("[data-map-edit-ui]")) return;
      const s = local(event);
      // A press on a corner or a midpoint, where the map shows it.
      const handle = h && k && one ? handleAt(k, s, p) : null;
      if (h && one && handle) {
        stop(event);
        if (event.altKey && handle.kind === "corner") {
          const rings = h.rings.map((rr) => [...rr]);
          const min = h.closed[handle.ring] ? 3 : kindOf(one.geometry) === "points" ? 1 : 2;
          if (rings[handle.ring].length > min) {
            rings[handle.ring].splice(handle.index, 1);
            live.current.session?.onReshape(one.id as SelectionId, h.rebuild(rings));
          }
          return;
        }
        gesture.current = { kind: handle.kind, ring: handle.ring, index: handle.index };
        return;
      }
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
      const { projection: p, selectedOne: one, handles: k, mode: m } = live.current;
      if (!p) return;
      const s = local(event);
      if (m === "draw") setHover(p.toData(s[0], s[1]));
      const g = gesture.current;
      if (!g) {
        // A corner shows it can be dragged and a midpoint that it adds one;
        // moving it whole, the picked feature that it can be grabbed with shift held.
        const handle = k && one ? handleAt(k, s, p) : null;
        const grab = m === "move" && event.shiftKey && !!one?.geometry && hitAt([one], s, p, live.current.size) !== null;
        host.style.cursor = handle ? (handle.kind === "corner" ? "grab" : "copy") : grab ? "grab" : "";
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
  if (!projection) return <div ref={box} data-testid="map-edit-overlay" data-corners="[]" className={styles.overlay} />;
  const p = projection;
  // The corners a drag moves, where the map shows them, in its own pixels.
  const corners = (handles?.corners ?? []).map(({ ring, index, at }) => {
    const [x, y] = p.toScreen(at);
    return { ring, index, x: tenth(x), y: tenth(y) };
  });
  const noun = active.noun;
  const parts = selectedOne?.geometry ? partsOf(selectedOne.geometry).length : 0;
  // The shape being drawn: what it is and how many points it has, then how to go on.
  const progress = mode === "draw" && draft.length > 0 ? `New ${noun} · ${draft.length} point${draft.length === 1 ? "" : "s"}. ` : "";
  const tip =
    progress +
    (mode === "draw"
      ? kind === "points"
        ? `Click the map to place a ${noun}. Drag to pan.`
        : "Click the map to add points. Double-click or press Enter to finish, or Esc to cancel."
      : mode === "reshape"
        ? kind === "points"
          ? `Drag the ${noun} to move it.`
          : `Drag a corner to move it. Click or drag a midpoint to add one, and alt-click a corner to delete it.${parts > 1 ? " Alt-click inside a part to remove it." : ""}`
        : mode === "move"
          ? `Shift-drag the ${noun} to move it. Drag to pan.`
          : `Click ${withArticle(noun)} to pick it, and shift-click to add one. Drag to pan.`);
  // Changing a shape, Done goes back to panning.
  const shaping = mode === "reshape" || mode === "move";

  return (
    <div
      ref={box}
      data-testid="map-edit-overlay"
      data-edit-mode={mode}
      data-edit-layer={active.table}
      data-corners={JSON.stringify(corners)}
      data-map-width={p.width}
      data-map-height={p.height}
      className={`${styles.overlay} ${mode === "draw" ? styles.drawing : ""}`}
    >
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
