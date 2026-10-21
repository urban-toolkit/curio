/**
 * The Interaction node's edit map (#662): a flat map of the input's layers in
 * the coordinates the node received them in (an Autark node hands its layers
 * on in EPSG:3395 metres; longitude-latitude is drawn with its longitudes
 * shrunk by the cosine of the latitude), where features are picked, drawn and
 * reshaped. A drawn or reshaped shape is in those same coordinates, so it is
 * written into the edit log as it is (`crs` names them).
 *
 * - Wheel to zoom, drag the map to pan.
 * - Select: click a feature of the layer being edited (shift-click adds it),
 *   or, with the lasso on, drag around the features to pick (shift adds them).
 * - Draw: click to place a point; for a line or an area, click each corner,
 *   then double-click, Enter or Finish; Backspace takes back the last corner,
 *   Escape gives up.
 * - Reshape (one feature picked): drag a corner to move it, drag a midpoint
 *   to add a corner there, alt-click a corner to delete it; with Move on, drag
 *   the feature to move it whole.
 *
 * The other layers are drawn faint, under the one being edited. Thousands of
 * features are drawn on a canvas; the handles are SVG on top of it.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import type { Geometry } from "../../utils/editFeatures/editFeatures";
import { kindOf, type EditedFeature, type GeometryKind } from "../../utils/editFeatures/layerModel";
import { LASSO_MIN_PIXELS, lassoPicks, outlineLength } from "../../utils/editFeatures/lasso";

type XY = [number, number];

export type EditMode = "select" | "draw" | "reshape" | "move";

/** A shape's corners as rings of points, and how to make the shape again from them. */
interface Rings {
  rings: XY[][];
  /** Whether a ring is an area's: closed, at least 3 corners. */
  closed: boolean[];
  rebuild: (rings: XY[][]) => Geometry;
}

/** *geometry*'s corners, rings of an area without their closing corner. */
export function toRings(geometry: Geometry): Rings {
  const c = geometry.coordinates as any;
  const open = (ring: XY[]) => (ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring);
  const close = (ring: XY[]) => [...ring, ring[0]];
  switch (geometry.type) {
    case "Point":
      return { rings: [[c as XY]], closed: [false], rebuild: (r) => ({ type: "Point", coordinates: r[0][0] }) };
    case "MultiPoint":
      return { rings: (c as XY[]).map((p) => [p]), closed: c.map(() => false), rebuild: (r) => ({ type: "MultiPoint", coordinates: r.map((ring) => ring[0]) }) };
    case "LineString":
      return { rings: [c as XY[]], closed: [false], rebuild: (r) => ({ type: "LineString", coordinates: r[0] }) };
    case "MultiLineString":
      return { rings: c as XY[][], closed: c.map(() => false), rebuild: (r) => ({ type: "MultiLineString", coordinates: r }) };
    case "Polygon":
      return { rings: (c as XY[][]).map(open), closed: c.map(() => true), rebuild: (r) => ({ type: "Polygon", coordinates: r.map(close) }) };
    case "MultiPolygon": {
      const shape = (c as XY[][][]).map((poly) => poly.length);
      const flat = (c as XY[][][]).flat().map(open);
      return {
        rings: flat,
        closed: flat.map(() => true),
        rebuild: (r) => {
          const out: XY[][][] = [];
          let at = 0;
          for (const n of shape) {
            out.push(r.slice(at, at + n).map(close));
            at += n;
          }
          return { type: "MultiPolygon", coordinates: out };
        },
      };
    }
    default:
      return { rings: [], closed: [], rebuild: () => geometry };
  }
}

function eachCoordinate(geometry: Geometry | null | undefined, visit: (xy: XY) => void) {
  const walk = (value: any) => {
    if (!Array.isArray(value)) return;
    if (typeof value[0] === "number" && typeof value[1] === "number") visit(value as XY);
    else for (const item of value) walk(item);
  };
  walk(geometry?.coordinates);
}

/** The box *features* cover, or null when they have no coordinates. */
function extentOf(geometries: (Geometry | null | undefined)[]): [number, number, number, number] | null {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const g of geometries) {
    eachCoordinate(g, ([x, y]) => {
      if (!Number.isFinite(x) || !Number.isFinite(y)) return;
      minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
    });
  }
  return Number.isFinite(minX) ? [minX, minY, maxX, maxY] : null;
}

/** Whether *xy* falls inside a ring (even-odd). */
function inRing([x, y]: XY, ring: XY[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function segmentDistance([px, py]: XY, [ax, ay]: XY, [bx, by]: XY): number {
  const dx = bx - ax, dy = by - ay;
  const t = dx === 0 && dy === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

export interface BackgroundLayer {
  name: string;
  geometries: (Geometry | null)[];
}

export default function EditCanvas({
  background,
  features,
  geographic,
  selected,
  mode,
  drawKind,
  onSelect,
  onDrawn,
  onReshape,
  lasso = false,
  onSelectMany,
  height = 420,
}: {
  /** The other layers, drawn faint under the one being edited. */
  background: BackgroundLayer[];
  /** The layer being edited, as the log leaves it. */
  features: EditedFeature[];
  /** Longitude-latitude coordinates: longitudes are shrunk by the latitude's cosine. */
  geographic: boolean;
  selected: SelectionId[];
  mode: EditMode;
  /** What Draw makes. */
  drawKind: GeometryKind;
  onSelect: (id: SelectionId | null, additive: boolean) => void;
  onDrawn: (geometry: Geometry) => void;
  onReshape: (id: SelectionId, geometry: Geometry) => void;
  /** In select mode, a drag draws a lasso that picks what it encloses, in place of a pan. */
  lasso?: boolean;
  onSelectMany?: (ids: SelectionId[], additive: boolean) => void;
  height?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(640);
  // The view: the map point at the middle of the box, and pixels per map unit.
  const [view, setView] = useState<{ cx: number; cy: number; scale: number } | null>(null);
  const [draft, setDraft] = useState<XY[]>([]);
  const [hover, setHover] = useState<XY | null>(null);
  // A corner or the whole shape being dragged: the shape as it is while dragged.
  const [dragShape, setDragShape] = useState<{ id: SelectionId; geometry: Geometry } | null>(null);
  const gesture = useRef<{ kind: "pan" | "corner" | "mid" | "move" | "lasso"; start: [number, number]; moved: boolean; ring?: number; index?: number; origin?: Geometry; at?: XY; points?: XY[] } | null>(null);
  // The lasso being drawn, in screen pixels.
  const [lassoLine, setLassoLine] = useState<XY[] | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    setWidth(Math.max(200, el.clientWidth));
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(Math.max(200, el.clientWidth)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const extent = useMemo(
    () => extentOf([...features.map((f) => f.geometry), ...background.flatMap((layer) => layer.geometries)]),
    [features, background],
  );
  const aspect = useMemo(() => {
    if (!geographic || !extent) return 1;
    return Math.cos((((extent[1] + extent[3]) / 2) * Math.PI) / 180);
  }, [geographic, extent]);

  const fit = useCallback(() => {
    if (!extent) return;
    const [minX, minY, maxX, maxY] = extent;
    const w = Math.max((maxX - minX) * aspect, 1e-9), h = Math.max(maxY - minY, 1e-9);
    setView({ cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, scale: 0.92 * Math.min(width / w, height / h) });
  }, [extent, aspect, width, height]);

  useEffect(() => {
    if (!view) fit();
  }, [view, fit]);

  const toScreen = useCallback(
    ([x, y]: XY): [number, number] => {
      if (!view) return [0, 0];
      return [width / 2 + (x - view.cx) * aspect * view.scale, height / 2 - (y - view.cy) * view.scale];
    },
    [view, width, height, aspect],
  );
  const toMap = useCallback(
    (sx: number, sy: number): XY => {
      if (!view) return [0, 0];
      return [view.cx + (sx - width / 2) / (aspect * view.scale), view.cy - (sy - height / 2) / view.scale];
    },
    [view, width, height, aspect],
  );

  const selectedKeys = useMemo(() => new Set(selected.map(String)), [selected]);
  const shown = useMemo(
    () => features.map((f) => (dragShape && f.id !== null && String(f.id) === String(dragShape.id) ? { ...f, geometry: dragShape.geometry } : f)),
    [features, dragShape],
  );

  // The canvas: the faint layers, then the layer being edited.
  useEffect(() => {
    const el = canvas.current;
    if (!el || !view) return;
    const ratio = window.devicePixelRatio || 1;
    el.width = Math.round(width * ratio);
    el.height = Math.round(height * ratio);
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const trace = (geometry: Geometry) => {
      const { rings, closed } = toRings(geometry);
      rings.forEach((ring, r) => {
        ring.forEach((xy, i) => {
          const [sx, sy] = toScreen(xy);
          if (i === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        });
        if (closed[r]) ctx.closePath();
      });
    };
    const paint = (geometry: Geometry | null, fill: string, stroke: string, lineWidth: number, radius = 3.5) => {
      if (!geometry) return;
      const kind = kindOf(geometry);
      if (kind === "points") {
        eachCoordinate(geometry, (xy) => {
          const [sx, sy] = toScreen(xy);
          ctx.beginPath();
          ctx.arc(sx, sy, radius, 0, Math.PI * 2);
          ctx.fillStyle = stroke;
          ctx.fill();
        });
        return;
      }
      ctx.beginPath();
      trace(geometry);
      if (kind === "areas") {
        ctx.fillStyle = fill;
        ctx.fill("evenodd");
      }
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lineWidth;
      ctx.stroke();
    };
    // The other layers faint: thousands of points as specks, not blots.
    for (const layer of background) for (const g of layer.geometries) paint(g, "rgba(120,128,140,0.08)", "rgba(120,128,140,0.30)", 0.6, 1.2);
    for (const f of shown) {
      if (f.id !== null && selectedKeys.has(String(f.id))) continue;
      const color = f.status === "added" ? "#1F6FEB" : f.status === "redrawn" ? "#B35F00" : "#2B2F38";
      paint(f.geometry, f.status === "added" ? "rgba(31,111,235,0.22)" : "rgba(43,47,56,0.16)", color, f.status === "input" ? 1 : 2);
    }
  }, [background, shown, selectedKeys, view, width, height, toScreen]);

  const selectedOne = selected.length === 1 ? shown.find((f) => f.id !== null && String(f.id) === String(selected[0])) : undefined;
  const handles = selectedOne?.geometry && (mode === "reshape" || mode === "move") ? toRings(selectedOne.geometry) : null;

  /** The feature of the edited layer at screen point *s*, top-most first. */
  const hit = (s: [number, number]): EditedFeature | null => {
    const at = toMap(s[0], s[1]);
    const tolerance = 7;
    for (let i = shown.length - 1; i >= 0; i -= 1) {
      const f = shown[i];
      if (!f.geometry || f.id === null) continue;
      const kind = kindOf(f.geometry);
      const { rings, closed } = toRings(f.geometry);
      if (kind === "points") {
        if (rings.some((ring) => { const [x, y] = toScreen(ring[0]); return Math.hypot(x - s[0], y - s[1]) <= tolerance; })) return f;
        continue;
      }
      if (kind === "areas" && rings.some((ring, r) => closed[r] && inRing(at, ring))) return f;
      for (const [r, ring] of rings.entries()) {
        const screen = ring.map(toScreen);
        const segments = closed[r] ? screen.length : screen.length - 1;
        for (let k = 0; k < segments; k += 1) {
          if (segmentDistance(s, screen[k], screen[(k + 1) % screen.length]) <= tolerance) return f;
        }
      }
    }
    return null;
  };

  const local = (event: React.PointerEvent | React.MouseEvent | React.WheelEvent): [number, number] => {
    const rect = (box.current as HTMLDivElement).getBoundingClientRect();
    // A canvas under React Flow's zoom is scaled: map client pixels to the box's own.
    const sx = rect.width > 0 ? width / rect.width : 1;
    const sy = rect.height > 0 ? height / rect.height : 1;
    return [(event.clientX - rect.left) * sx, (event.clientY - rect.top) * sy];
  };

  const finishDraft = useCallback(() => {
    if (drawKind === "lines" && draft.length >= 2) onDrawn({ type: "LineString", coordinates: draft });
    else if (drawKind === "areas" && draft.length >= 3) onDrawn({ type: "Polygon", coordinates: [[...draft, draft[0]]] });
    else return;
    setDraft([]);
  }, [draft, drawKind, onDrawn]);

  useEffect(() => setDraft([]), [mode, drawKind]);

  const onWheel = (event: React.WheelEvent) => {
    if (!view) return;
    event.stopPropagation();
    const s = local(event);
    const at = toMap(s[0], s[1]);
    const factor = Math.exp(-event.deltaY * 0.0015);
    const scale = view.scale * factor;
    // Keep the point under the pointer where it is.
    setView({ scale, cx: at[0] - (s[0] - width / 2) / (aspect * scale), cy: at[1] + (s[1] - height / 2) / scale });
  };

  const onPointerDown = (event: React.PointerEvent) => {
    if (!view || event.button !== 0) return;
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    const s = local(event);
    const target = event.target as Element;
    const ring = target.getAttribute("data-ring");
    const index = target.getAttribute("data-index");
    if (handles && selectedOne && ring !== null && index !== null) {
      const r = Number(ring), i = Number(index);
      if (event.altKey && target.getAttribute("data-handle") === "corner") {
        // Delete a corner: a line keeps two, an area three, a point one.
        const rings = handles.rings.map((rr) => [...rr]);
        const min = handles.closed[r] ? 3 : kindOf(selectedOne.geometry) === "points" ? 1 : 2;
        if (rings[r].length > min) {
          rings[r].splice(i, 1);
          onReshape(selectedOne.id as SelectionId, handles.rebuild(rings));
        }
        gesture.current = null;
        return;
      }
      gesture.current = { kind: target.getAttribute("data-handle") === "mid" ? "mid" : "corner", start: s, moved: false, ring: r, index: i };
      return;
    }
    if (mode === "move" && selectedOne?.geometry && hit(s)?.id === selectedOne.id) {
      gesture.current = { kind: "move", start: s, moved: false, origin: selectedOne.geometry, at: toMap(s[0], s[1]) };
      return;
    }
    // With the lasso on, a drag outlines what to pick, in place of a pan.
    if (mode === "select" && lasso) {
      gesture.current = { kind: "lasso", start: s, moved: false, points: [s] };
      return;
    }
    gesture.current = { kind: "pan", start: s, moved: false };
  };

  const onPointerMove = (event: React.PointerEvent) => {
    const s = local(event);
    if (mode === "draw") setHover(toMap(s[0], s[1]));
    const g = gesture.current;
    if (!g || !view) return;
    if (g.kind === "lasso" && g.points) {
      g.points.push(s);
      setLassoLine([...g.points]);
      return;
    }
    if (Math.hypot(s[0] - g.start[0], s[1] - g.start[1]) > 3) g.moved = true;
    if (!g.moved) return;
    if (g.kind === "pan") {
      const dx = (s[0] - g.start[0]) / (aspect * view.scale), dy = (s[1] - g.start[1]) / view.scale;
      g.start = s;
      setView({ ...view, cx: view.cx - dx, cy: view.cy + dy });
      return;
    }
    if (!selectedOne?.geometry || selectedOne.id === null) return;
    const at = toMap(s[0], s[1]);
    if (g.kind === "move" && g.origin && g.at) {
      const dx = at[0] - g.at[0], dy = at[1] - g.at[1];
      const moved = JSON.parse(JSON.stringify(g.origin)) as Geometry;
      const shift = (value: any) => {
        if (typeof value[0] === "number") {
          value[0] += dx;
          value[1] += dy;
        } else value.forEach(shift);
      };
      shift(moved.coordinates);
      setDragShape({ id: selectedOne.id, geometry: moved });
      return;
    }
    const base = toRings(selectedOne.geometry);
    const rings = base.rings.map((rr) => [...rr]);
    if (g.kind === "corner") rings[g.ring as number][g.index as number] = at;
    else rings[g.ring as number].splice((g.index as number) + 1, 0, at);
    setDragShape({ id: selectedOne.id, geometry: base.rebuild(rings) });
  };

  const onPointerUp = (event: React.PointerEvent) => {
    const g = gesture.current;
    gesture.current = null;
    const s = local(event);
    if (g?.kind === "lasso" && g.points) {
      setLassoLine(null);
      // Too short to outline anything: a click, which picks what is under it.
      if (outlineLength(g.points) < LASSO_MIN_PIXELS) onSelect(hit(g.start)?.id ?? null, event.shiftKey);
      else onSelectMany?.(lassoPicks(features, g.points, toScreen), event.shiftKey);
      return;
    }
    // A click on a midpoint adds its corner there; no drag is needed.
    if (g?.kind === "mid" && !g.moved) {
      if (selectedOne?.geometry && selectedOne.id !== null) {
        const base = toRings(selectedOne.geometry);
        const rings = base.rings.map((rr) => [...rr]);
        const ring = rings[g.ring as number], i = g.index as number;
        const a = ring[i], b = ring[(i + 1) % ring.length];
        ring.splice(i + 1, 0, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
        onReshape(selectedOne.id as SelectionId, base.rebuild(rings));
      }
      setDragShape(null);
      return;
    }
    if (g && g.kind !== "pan") {
      if (dragShape) onReshape(dragShape.id, dragShape.geometry);
      setDragShape(null);
      return;
    }
    if (g?.moved) return;
    // A click.
    if (mode === "draw") {
      const at = toMap(s[0], s[1]);
      if (drawKind === "points") onDrawn({ type: "Point", coordinates: at });
      else setDraft((current) => [...current, at]);
      return;
    }
    const found = hit(s);
    onSelect(found?.id ?? null, event.shiftKey);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (mode !== "draw") return;
    let handled = true;
    if (event.key === "Enter") finishDraft();
    else if (event.key === "Escape") setDraft([]);
    else if (event.key === "Backspace") setDraft((current) => current.slice(0, -1));
    else handled = false;
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  const draftScreen = draft.map(toScreen);
  const hoverScreen = hover && mode === "draw" && draft.length > 0 ? toScreen(hover) : null;
  const selectedShapes = shown.filter((f) => f.id !== null && selectedKeys.has(String(f.id)) && f.geometry);

  const svgPath = (geometry: Geometry) => {
    const { rings, closed } = toRings(geometry);
    return rings.map((ring, r) => ring.map((xy, i) => `${i === 0 ? "M" : "L"}${toScreen(xy).join(" ")}`).join(" ") + (closed[r] ? " Z" : "")).join(" ");
  };

  return (
    <div
      ref={box}
      className="nodrag nopan nowheel"
      data-testid="interaction-edit-map"
      data-edit-mode={mode}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={(event) => {
        if (mode === "draw") {
          event.stopPropagation();
          // The double-click's own clicks placed two corners at its point; keep one.
          setDraft((current) => (current.length >= 2 ? current.slice(0, -1) : current));
          setTimeout(finishDraft, 0);
        }
      }}
      style={{
        position: "relative",
        width: "100%",
        height,
        background: "#F2F4F7",
        borderRadius: 8,
        overflow: "hidden",
        cursor: mode === "draw" || (mode === "select" && lasso) ? "crosshair" : mode === "move" ? "move" : "default",
        outline: "none",
        touchAction: "none",
      }}
    >
      <canvas ref={canvas} style={{ position: "absolute", inset: 0, width, height }} aria-hidden="true" />
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }} role="img" aria-label="Edit map">
        {selectedShapes.map((f) =>
          kindOf(f.geometry) === "points" ? (
            toRings(f.geometry as Geometry).rings.map((ring, r) => {
              const [x, y] = toScreen(ring[0]);
              return <circle key={`${String(f.id)}-${r}`} cx={x} cy={y} r={7} fill="rgba(31,111,235,0.25)" stroke="#1F6FEB" strokeWidth={2} />;
            })
          ) : (
            <path
              key={String(f.id)}
              d={svgPath(f.geometry as Geometry)}
              fill={kindOf(f.geometry) === "areas" ? "rgba(31,111,235,0.18)" : "none"}
              stroke="#1F6FEB"
              strokeWidth={3}
              fillRule="evenodd"
            />
          ),
        )}
        {handles
          ? handles.rings.map((ring, r) => (
              <g key={`ring-${r}`}>
                {mode === "reshape" && ring.length > 1
                  ? ring.slice(0, handles.closed[r] ? ring.length : ring.length - 1).map((xy, i) => {
                      const next = ring[(i + 1) % ring.length];
                      const [x, y] = toScreen([(xy[0] + next[0]) / 2, (xy[1] + next[1]) / 2]);
                      return <circle key={`m${i}`} data-handle="mid" data-ring={r} data-index={i} cx={x} cy={y} r={4} fill="#FFFFFF" stroke="#1F6FEB" strokeWidth={1.5} opacity={0.8} style={{ cursor: "copy" }} />;
                    })
                  : null}
                {mode === "reshape"
                  ? ring.map((xy, i) => {
                      const [x, y] = toScreen(xy);
                      return <circle key={`c${i}`} data-handle="corner" data-ring={r} data-index={i} cx={x} cy={y} r={6} fill="#FFFFFF" stroke="#1F6FEB" strokeWidth={2} style={{ cursor: "grab" }} />;
                    })
                  : null}
              </g>
            ))
          : null}
        {lassoLine && lassoLine.length > 1 ? (
          <polygon data-testid="interaction-edit-lasso" points={lassoLine.map((p) => p.join(",")).join(" ")} fill="#1F6FEB1A" stroke="#1F6FEB" strokeWidth={1.5} strokeDasharray="5 4" strokeLinejoin="round" />
        ) : null}
        {draftScreen.length > 0 ? (
          <>
            <polyline
              points={[...draftScreen, ...(hoverScreen ? [hoverScreen] : [])].map((p) => p.join(",")).join(" ")}
              fill={drawKind === "areas" ? "rgba(31,111,235,0.15)" : "none"}
              stroke="#1F6FEB"
              strokeWidth={2.5}
              strokeDasharray={hoverScreen ? "0" : undefined}
            />
            {draftScreen.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r={4.5} fill="#1F6FEB" stroke="#FFFFFF" strokeWidth={1.5} />
            ))}
          </>
        ) : null}
      </svg>
      <div style={{ position: "absolute", right: 8, top: 8, display: "flex", gap: 6 }}>
        {mode === "draw" && drawKind !== "points" ? (
          <button type="button" data-testid="interaction-finish-draw" className="nodrag nopan" disabled={draft.length < (drawKind === "areas" ? 3 : 2)} onPointerDown={(e) => e.stopPropagation()} onClick={finishDraft} style={{ minHeight: 30, padding: "0 10px", borderRadius: 6, border: 0, background: "#1F6FEB", color: "#FFFFFF", fontWeight: 600 }}>
            Finish
          </button>
        ) : null}
        <button type="button" className="nodrag nopan" aria-label="Fit the map to the layers" onPointerDown={(e) => e.stopPropagation()} onClick={fit} style={{ minHeight: 30, padding: "0 10px", borderRadius: 6, border: "1px solid #C9CDD6", background: "#FFFFFF" }}>
          Fit
        </button>
      </div>
      <div style={{ position: "absolute", left: 8, bottom: 8, fontSize: 11, color: "#3D4654", background: "rgba(255,255,255,0.85)", borderRadius: 6, padding: "3px 7px" }}>
        {mode === "draw"
          ? drawKind === "points"
            ? "Click to place a point"
            : `Click each corner, then double-click or Finish${draft.length > 0 ? ` · ${draft.length} placed · Backspace takes one back` : ""}`
          : mode === "reshape"
            ? "Drag a corner · click or drag a midpoint to add one · alt-click a corner to delete it"
            : mode === "move"
              ? "Drag the picked feature to move it"
              : "Click a feature to pick it · shift-click to add · drag to pan · wheel to zoom"}
      </div>
    </div>
  );
}
