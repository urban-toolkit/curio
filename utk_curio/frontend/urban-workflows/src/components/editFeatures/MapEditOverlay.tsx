/**
 * What a Map Editor node does on an Autark map it feeds and is linked to
 * (#662): it hears the pointer on the map, read through the map's own
 * camera, where the layer the node works on is picked, drawn into and
 * reshaped (`utils/editFeatures/mapEditBus`), and holds the tip with its
 * buttons. It is mounted only on a map a Map Editor node feeds.
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
 * A feature of several rows, as an OSM building of several parts is, shows
 * the corners of every part. A drag changes the part it is on alone, and a
 * move moves every part, each keeping its shape: the edits name each part
 * by its own row (`featureParts`), and the other parts keep their shapes.
 *
 * A gesture that would make an area autk-db refuses, and with it the whole
 * layer (`areaCheck`), is refused when it ends: nothing is written, a shape
 * dragged goes back as it was, a shape drawn keeps its corners, and the tip
 * says why until the next press on the map, Backspace or Escape while
 * drawing, or a change of mode.
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
import { kindOf, type EditedFeature } from "../../utils/editFeatures/layerModel";
import { editMap, editMapLayerId, editMapPositions, useMapEdit } from "../../utils/editFeatures/mapEditBus";
import { editSelection, selectedIdsIn, toggledIds, type SentSelection } from "../../utils/editFeatures/mapEditSelection";
import { partsOf, withoutPart } from "../../utils/editFeatures/geometryParts";
import { handlesOf, toRings, type Handle } from "../../utils/editFeatures/geometryRings";
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

/**
 * What a press started. A corner or a midpoint is of one row of the picked
 * feature, by its place among the layer's features; a move takes every row.
 */
type Gesture =
  | { kind: "click"; start: XY; moved: boolean; shift: boolean }
  | { kind: "corner" | "mid"; row: number; ring: number; index: number; shape?: Geometry }
  | { kind: "move"; origins: [number, Geometry][]; at: XY };

/** A handle of one row of the picked feature: the row's place among the features, and its part, the row's place among the feature's rows. */
type PartHandle = Handle & { row: number; part: number };

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
  // Why the last gesture was refused, which the tip says until the next press
  // on the map, Backspace or Escape while drawing, or a change of mode.
  const [refusal, setRefusal] = useState<string | null>(null);
  // The shapes a drag gives rows of the picked feature, by each row's place among the features.
  const [dragShapes, setDragShapes] = useState<Record<number, Geometry> | null>(null);
  const gesture = useRef<Gesture | null>(null);
  // The row the last click that picked landed on: the part a new part joins.
  const pickedRow = useRef<EditedFeature | null>(null);
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
  useEffect(() => {
    setDraft([]);
    setRefusal(null);
  }, [mode, kind, active?.table]);

  const projection = active && map ? projectionOf(map, active.geographic) : null;
  const features = active?.features ?? [];
  const shown = useMemo(
    () => features.map((f, row) => (dragShapes?.[row] ? { ...f, geometry: dragShapes[row] } : f)),
    [features, dragShapes],
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
  // The picked feature's rows, its parts, by their places among the features:
  // an OSM building of several parts is a row for each.
  const pickedId = selected.length === 1 ? selected[0] : null;
  const pickedRows = useMemo(
    () => (pickedId === null ? [] : features.flatMap((f, row) => (f.id !== null && String(f.id) === String(pickedId) ? [row] : []))),
    [features, pickedId],
  );
  // The corners and midpoints of each of its parts, while their points are moved.
  const handles = useMemo(() => {
    if (mode !== "reshape") return null;
    const corners: PartHandle[] = [];
    const midpoints: PartHandle[] = [];
    pickedRows.forEach((row, part) => {
      const geometry = shown[row]?.geometry;
      if (!geometry) return;
      const own = handlesOf(toRings(geometry));
      corners.push(...own.corners.map((handle) => ({ ...handle, row, part })));
      midpoints.push(...own.midpoints.map((handle) => ({ ...handle, row, part })));
    });
    return corners.length > 0 ? { corners, midpoints } : null;
  }, [mode, pickedRows, shown]);

  // The picked feature, while it is reshaped or moved, is drawn by the tools,
  // each of its parts, and skipped where its layer draws it.
  const changing = (mode === "reshape" || mode === "move") && pickedRows.length > 0 ? pickedId : null;
  const changingKey = changing === null ? null : String(changing);
  // Where its layer draws it, once the map has read back the rows it drew.
  const [hiddenPositions, setHiddenPositions] = useState<number[]>([]);
  useEffect(() => {
    let live = true;
    if (changing !== null && active?.key) {
      void editMapPositions(mapId, active.table, active.key, changing).then((positions) => {
        if (live) setHiddenPositions(positions);
      });
    } else {
      setHiddenPositions((now) => (now.length === 0 ? now : []));
    }
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, mapId, active?.table, active?.key, changingKey]);
  const changed = useMemo(
    () => (changingKey === null ? [] : pickedRows.flatMap((row) => (shown[row]?.geometry ? [shown[row].geometry as Geometry] : []))),
    [shown, pickedRows, changingKey],
  );

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
    let refused: string | null;
    if (kind === "lines" && draft.length >= 2) refused = session.onDrawn({ type: "LineString", coordinates: draft }, pickedRow.current);
    else if (kind === "areas" && draft.length >= 3) refused = session.onDrawn({ type: "Polygon", coordinates: [[...draft, draft[0]]] }, pickedRow.current);
    else return;
    setRefusal(refused ?? null);
    // A shape refused keeps its corners, to take one back with Backspace or give up with Esc.
    if (!refused) setDraft([]);
  }, [session, kind, draft]);

  // The latest of everything the listeners read, so they are added once.
  // How big the map draws the layer's points and lines, for what a click reaches.
  const size = drawnSize(map, active?.table ? editMapLayerId(mapId, active.table) : undefined);
  const live = useRef({ session, active, projection, features, shown, pickedRows, handles, mode, kind, draft, finishDraft, dragShapes, size, pick });
  live.current = { session, active, projection, features, shown, pickedRows, handles, mode, kind, draft, finishDraft, dragShapes, size, pick };

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
      const { projection: p, handles: k, mode: m, features: rows, shown: all, pickedRows: picked, size: z } = live.current;
      // Heard on the window, ahead of the page's own listeners: a press on this map only.
      if (!p || event.button !== 0 || !host.contains(event.target as Node)) return;
      // The overlay's own buttons are buttons.
      if ((event.target as Element).closest?.("[data-map-edit-ui]")) return;
      // A new press: the tip no longer says why the last gesture was refused.
      setRefusal(null);
      const s = local(event);
      // A press on a corner or a midpoint, where the map shows it: a corner
      // of one part of the picked feature.
      const handle = k ? handleAt(k, s, p) : null;
      const shape = handle ? all[handle.row]?.geometry : null;
      if (handle && shape) {
        stop(event);
        if (event.altKey && handle.kind === "corner") {
          const own = toRings(shape);
          const rings = own.rings.map((rr) => [...rr]);
          const min = own.closed[handle.ring] ? 3 : kindOf(shape) === "points" ? 1 : 2;
          if (rings[handle.ring].length > min) {
            rings[handle.ring].splice(handle.index, 1);
            setRefusal(live.current.session?.onReshape([{ row: rows[handle.row], geometry: own.rebuild(rings) }], "delete") ?? null);
          }
          return;
        }
        gesture.current = { kind: handle.kind, row: handle.row, ring: handle.ring, index: handle.index };
        return;
      }
      // Moving points, an alt-click inside one piece of a part whose shape is
      // several takes that piece away (a corner's own alt-click deletes the corner).
      if (m === "reshape" && event.altKey) {
        const row = picked.find((r) => all[r]?.geometry && hitAt([all[r]], s, p, z) !== null);
        const own = row === undefined ? null : all[row].geometry;
        const pieces = partsOf(own);
        const hit = pieces.length > 1 ? pieces.findIndex((piece) => hitAt([{ ...all[row as number], geometry: piece }], s, p, z) !== null) : -1;
        const rest = hit >= 0 ? withoutPart(own, hit) : null;
        if (row !== undefined && rest) {
          stop(event);
          setRefusal(live.current.session?.onReshape([{ row: rows[row], geometry: rest }], "remove") ?? null);
          return;
        }
      }
      // Moving a feature whole, every part of it, is a shift-drag on it; a
      // plain drag pans the map.
      const under = m === "move" && event.shiftKey && picked.length > 0 ? hitAt(all, s, p, z) : null;
      if (under && under.id !== null && String(under.id) === String(all[picked[0]].id)) {
        stop(event);
        const origins = picked.flatMap((row): [number, Geometry][] => (all[row].geometry ? [[row, all[row].geometry as Geometry]] : []));
        gesture.current = { kind: "move", origins, at: p.toData(s[0], s[1]) };
        host.style.cursor = "grabbing";
        return;
      }
      // A press the map may turn into a pan: a click only if it stays put.
      gesture.current = { kind: "click", start: s, moved: false, shift: event.shiftKey };
    };
    const onMove = (event: PointerEvent) => {
      const { projection: p, handles: k, mode: m, features: rows, shown: all, pickedRows: picked } = live.current;
      if (!p) return;
      const s = local(event);
      if (m === "draw") setHover(p.toData(s[0], s[1]));
      const g = gesture.current;
      if (!g) {
        // A corner shows it can be dragged and a midpoint that it adds one;
        // moving it whole, the picked feature that it can be grabbed with shift held.
        const handle = k ? handleAt(k, s, p) : null;
        const grab = m === "move" && event.shiftKey && hitAt(picked.map((row) => all[row]), s, p, live.current.size) !== null;
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
      const at = p.toData(s[0], s[1]);
      if (g.kind === "move") {
        // Every part by the same offset, each keeping its shape.
        setDragShapes(Object.fromEntries(g.origins.map(([row, origin]) => [row, shifted(origin, at[0] - g.at[0], at[1] - g.at[1])])));
        return;
      }
      // The part's shape the drag started on, with a midpoint's corner once added.
      const geometry = rows[g.row]?.geometry;
      if (!geometry || !picked.includes(g.row)) return;
      const base = toRings(g.shape ?? geometry);
      const rings = base.rings.map((rr) => [...rr]);
      if (g.kind === "corner") rings[g.ring][g.index] = at;
      else {
        // A midpoint adds its corner once; the rest of the drag moves it.
        rings[g.ring].splice(g.index + 1, 0, at);
        gesture.current = { kind: "corner", row: g.row, ring: g.ring, index: g.index + 1, shape: base.rebuild(rings) };
      }
      setDragShapes({ [g.row]: base.rebuild(rings) });
    };
    const onUp = (event: PointerEvent) => {
      const g = gesture.current;
      gesture.current = null;
      if (g?.kind === "move") host.style.cursor = "grab";
      const { projection: p, session: s, mode: m, kind: k, features: rows, shown: all, dragShapes: dragged, size: z } = live.current;
      if (!g || !p || !s) return;
      // A click on a midpoint adds its corner there, to that part; no drag is needed.
      if (g.kind === "mid") {
        const geometry = rows[g.row]?.geometry;
        if (geometry) {
          const base = toRings(geometry);
          const rings = base.rings.map((rr) => [...rr]);
          const a = rings[g.ring][g.index], b = rings[g.ring][(g.index + 1) % rings[g.ring].length];
          rings[g.ring].splice(g.index + 1, 0, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
          setRefusal(s.onReshape([{ row: rows[g.row], geometry: base.rebuild(rings) }], "drag") ?? null);
        }
        setDragShapes(null);
        return;
      }
      if (g.kind !== "click") {
        // The parts the drag changed, in the layer's order: one change. A
        // change refused leaves them as they were, the drag's shapes dropped.
        const changed = Object.entries(dragged ?? {}).flatMap(([row, geometry]) => (rows[Number(row)] ? [{ row: rows[Number(row)], geometry }] : []));
        if (changed.length > 0) setRefusal(s.onReshape(changed, g.kind === "move" ? "move" : "drag") ?? null);
        setDragShapes(null);
        return;
      }
      if (g.moved) return;
      const at = p.toData(g.start[0], g.start[1]);
      if (m === "draw") {
        if (k === "points") setRefusal(s.onDrawn({ type: "Point", coordinates: at }, pickedRow.current) ?? null);
        else setDraft((current) => [...current, at]);
        return;
      }
      // A click picks the feature under it, by the row it lands on.
      const found = hitAt(all, g.start, p, z);
      pickedRow.current = found ? rows[all.indexOf(found)] ?? null : null;
      if (m === "reshape" || m === "move") {
        if (found) live.current.pick(found.id, false);
        return;
      }
      live.current.pick(found?.id ?? null, g.shift);
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
      else if (event.key === "Escape") {
        setDraft([]);
        setRefusal(null);
      } else if (event.key === "Backspace" && live.current.draft.length > 0) {
        setDraft((current) => current.slice(0, -1));
        setRefusal(null);
      } else handled = false;
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
  // The corners a drag moves, where the map shows them, in its own pixels:
  // each with its part, the row's place among the feature's rows, and its
  // ring and index in that part's shape.
  const corners = (handles?.corners ?? []).map(({ part, ring, index, at }) => {
    const [x, y] = p.toScreen(at);
    return { part, ring, index, x: tenth(x), y: tenth(y) };
  });
  const noun = active.noun;
  // Whether a part's shape is several pieces, one of which an alt-click takes away.
  const pieces = pickedRows.some((row) => partsOf(shown[row]?.geometry).length > 1);
  // The shape being drawn: what it is and how many points it has, then how to go on.
  const progress = mode === "draw" && draft.length > 0 ? `New ${noun} · ${draft.length} point${draft.length === 1 ? "" : "s"}. ` : "";
  // Why the last gesture was refused, in place of how to go on, until the next press.
  const tip =
    progress +
    (refusal ?? (mode === "draw"
      ? kind === "points"
        ? `Click the map to place a ${noun}. Drag to pan.`
        : "Click the map to add points. Double-click or press Enter to finish, or Esc to cancel."
      : mode === "reshape"
        ? kind === "points"
          ? `Drag the ${noun} to move it.`
          : `Drag a corner to move it. Click or drag a midpoint to add one, and alt-click a corner to delete it.${pieces ? " Alt-click inside a part to remove it." : ""}`
        : mode === "move"
          ? `Shift-drag the ${noun} to move it. Drag to pan.`
          : `Click ${withArticle(noun)} to pick it, and shift-click to add one. Drag to pan.`));
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
