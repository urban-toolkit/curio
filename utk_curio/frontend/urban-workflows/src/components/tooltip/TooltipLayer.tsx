/**
 * The one Curio tooltip, for every hover in the app. Mounted once (index.tsx).
 *
 * An element asks for one with `data-tooltip="text"`, or with the content it
 * registered through useTooltipContent (`data-tooltip-content`), and may ask
 * for a side with `data-tooltip-side` ("right" for a tool rail palette row,
 * "pointer" for a chart's marks). This layer listens on the document, so no
 * element needs a handler of its own, and draws one tooltip at a time in a
 * portal on document.body, placed from its target's box on screen
 * (tooltipPlacement.ts). So no card clips it and the canvas's zoom never
 * scales it. Editors show theirs through the same store (tooltipStore.ts).
 *
 * The rules:
 * - the pointer resting on a target shows it, after a wait the store keeps;
 *   leaving hides it a moment later, and the pointer may move onto it;
 * - a press on a target hides it, and it stays off until the pointer leaves
 *   that target; a press inside the tooltip keeps it;
 * - a wheel, a scroll, a drag, Escape or the window losing focus hide it;
 * - focus from the keyboard shows it at once, until blur or Escape. The layer
 *   tells keyboard focus from a click's by which came last, a key or a press:
 *   jsdom's :focus-visible does not decide it as Chrome does;
 * - a touch held a moment (TOOLTIP_HOLD_MS) shows it, and the next touch anywhere hides
 *   it; a tap stays a tap;
 * - an open tooltip follows its target's `data-tooltip` as it changes (Vega
 *   rewrites it as the pointer crosses marks), and goes when it is cleared.
 *
 * The listeners are on the way down (capture), since React Flow's pane and
 * nodes stop presses, wheels and touches from bubbling.
 */
import React, { useEffect, useId, useLayoutEffect, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import styles from "./TooltipLayer.module.css";
import { placeTooltip, tooltipMaxSize, type TooltipSide } from "./tooltipPlacement";
import { tooltipHoldMs, tooltipStore, type TooltipContent, type TooltipRequest } from "./tooltipStore";

const TARGET = "[data-tooltip], [data-tooltip-content]";
const SIDES: readonly TooltipSide[] = ["top", "right", "pointer"];

/** The element that holds *el*'s tooltip: the nearest one that asks for one. */
function targetOf(el: EventTarget | null): Element | null {
  return el instanceof Element ? el.closest(TARGET) : null;
}

/** What *target* asks its tooltip to say, or null when it says nothing. */
function contentOf(target: Element): TooltipContent | null {
  const id = target.getAttribute("data-tooltip-content");
  if (id) {
    const node = tooltipStore.registered(id);
    if (node !== undefined && node !== null && node !== false) return { kind: "preview", node };
  }
  const text = (target.getAttribute("data-tooltip") ?? "").trim();
  return text ? { kind: "text", text } : null;
}

/** The tooltip *target* asks for, or null when it says nothing. */
function requestFor(target: Element, pointer: { x: number; y: number } | null): TooltipRequest | null {
  const content = contentOf(target);
  if (!content) return null;
  const asked = target.getAttribute("data-tooltip-side") as TooltipSide | null;
  const side = asked && SIDES.includes(asked) ? asked : "top";
  return {
    key: target,
    target,
    anchor: () => target.getBoundingClientRect(),
    side,
    pointer: side === "pointer" ? pointer : null,
    content,
  };
}

/** Add or remove *id* among the ids *el*'s aria-describedby names, keeping the others. */
function describe(el: Element, id: string, on: boolean): void {
  const ids = (el.getAttribute("aria-describedby") ?? "").split(/\s+/).filter((token) => token && token !== id);
  if (on) ids.push(id);
  if (ids.length > 0) el.setAttribute("aria-describedby", ids.join(" "));
  else el.removeAttribute("aria-describedby");
}

export function TooltipLayer(): React.ReactElement | null {
  const state = useSyncExternalStore(tooltipStore.subscribe, tooltipStore.getState, tooltipStore.getState);
  const id = `curio-tooltip-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const ref = useRef<HTMLDivElement | null>(null);
  const shown = state.shown;
  const target = shown?.request.target ?? null;

  useEffect(() => {
    /** What the pointer is over, where it is, and a target a press closed. */
    let hovered: Element | null = null;
    let pointer: { x: number; y: number } | null = null;
    let pressed: Element | null = null;
    /** The target this layer last asked a tooltip for; it lets go of no other, an editor's included. */
    let current: Element | null = null;
    /** Which came last, a key or a press: keyboard focus shows a tooltip, a click's does not. */
    let keyboard = false;
    let hold: ReturnType<typeof setTimeout> | null = null;

    const inTooltip = (el: Element | null) => !!el && !!ref.current && ref.current.contains(el);
    const stopHold = () => {
      if (hold !== null) clearTimeout(hold);
      hold = null;
    };

    const letGo = () => {
      if (current) tooltipStore.leave(current);
      current = null;
    };

    // Where the pointer is now decides: on the tooltip it stays, on a target
    // it is asked for, anywhere else this layer's goes.
    const settle = () => {
      const el = hovered;
      if (!el || !el.isConnected) {
        letGo();
        return;
      }
      if (inTooltip(el)) {
        tooltipStore.keep();
        return;
      }
      if (pressed && !pressed.contains(el)) pressed = null;
      const target = targetOf(el);
      const request = target && !pressed ? requestFor(target, pointer) : null;
      if (!request) {
        letGo();
        return;
      }
      if (current && current !== target) tooltipStore.leave(current);
      current = target;
      tooltipStore.rest(request);
    };

    // A pointer with a button held is dragging: it asks for nothing on its way.
    const onOver = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.buttons !== 0) return;
      hovered = event.target instanceof Element ? event.target : null;
      pointer = { x: event.clientX, y: event.clientY };
      settle();
    };
    // On the way up, so a chart that rewrites its tooltip at a move has done so.
    const onMove = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.buttons !== 0) return;
      hovered = event.target instanceof Element ? event.target : hovered;
      pointer = { x: event.clientX, y: event.clientY };
      settle();
    };
    const onOut = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.relatedTarget) return;
      // Out of the window.
      hovered = null;
      settle();
    };
    const onDown = (event: PointerEvent) => {
      keyboard = false;
      const el = event.target instanceof Element ? event.target : null;
      if (inTooltip(el)) return;
      if (event.pointerType === "touch") {
        // The next touch anywhere hides one, and a touch held long enough shows one.
        tooltipStore.hide();
        stopHold();
        const target = targetOf(el);
        if (!target) return;
        hold = setTimeout(() => {
          hold = null;
          const request = target.isConnected ? requestFor(target, null) : null;
          if (request) tooltipStore.show(request, "touch");
        }, tooltipHoldMs());
        return;
      }
      pressed = targetOf(el);
      tooltipStore.hide();
    };
    const onUp = (event: PointerEvent) => {
      if (event.pointerType === "touch") stopHold();
    };
    const onKey = (event: KeyboardEvent) => {
      keyboard = true;
      if (event.key === "Escape") tooltipStore.hide();
    };
    const onFocus = (event: FocusEvent) => {
      if (!keyboard) return;
      const target = targetOf(event.target);
      const request = target ? requestFor(target, null) : null;
      if (request) tooltipStore.show(request, "focus");
    };
    const onBlur = (event: FocusEvent) => {
      const target = targetOf(event.target);
      if (target) tooltipStore.blurred(target);
    };
    const hide = () => tooltipStore.hide();

    // A target's tooltip changed under the pointer, or appeared (a chart
    // writes its mark's tooltip at the move that reaches the mark); or the
    // target of one the keyboard opened changed what it says.
    const observer = new MutationObserver((records) => {
      const el = hovered;
      if (el && records.some((record) => record.target instanceof Element && record.target.contains(el))) settle();
      for (const record of records) {
        if (record.target instanceof Element && record.target.matches(TARGET)) {
          tooltipStore.refresh(record.target, contentOf(record.target));
        }
      }
    });
    observer.observe(document.body, {
      subtree: true,
      attributes: true,
      attributeFilter: ["data-tooltip", "data-tooltip-content", "data-tooltip-side"],
    });

    const capture = { capture: true } as const;
    const passive = { capture: true, passive: true } as const;
    document.addEventListener("pointerover", onOver, capture);
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerout", onOut, capture);
    document.addEventListener("pointerdown", onDown, capture);
    document.addEventListener("pointerup", onUp, capture);
    document.addEventListener("pointercancel", onUp, capture);
    document.addEventListener("keydown", onKey, capture);
    document.addEventListener("focusin", onFocus, capture);
    document.addEventListener("focusout", onBlur, capture);
    document.addEventListener("wheel", hide, passive);
    document.addEventListener("scroll", hide, passive);
    document.addEventListener("dragstart", hide, capture);
    window.addEventListener("blur", hide);
    return () => {
      observer.disconnect();
      stopHold();
      document.removeEventListener("pointerover", onOver, capture);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerout", onOut, capture);
      document.removeEventListener("pointerdown", onDown, capture);
      document.removeEventListener("pointerup", onUp, capture);
      document.removeEventListener("pointercancel", onUp, capture);
      document.removeEventListener("keydown", onKey, capture);
      document.removeEventListener("focusin", onFocus, capture);
      document.removeEventListener("focusout", onBlur, capture);
      document.removeEventListener("wheel", hide, passive);
      document.removeEventListener("scroll", hide, passive);
      document.removeEventListener("dragstart", hide, capture);
      window.removeEventListener("blur", hide);
    };
  }, []);

  // The target names the tooltip as its description while it shows.
  useLayoutEffect(() => {
    if (!target) return undefined;
    describe(target, id, true);
    return () => describe(target, id, false);
  }, [target, id]);

  // Placed from its target's box on screen, once its own size is known.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !shown) return;
    if (shown.request.target && !shown.request.target.isConnected) {
      tooltipStore.hide();
      return;
    }
    const anchor = shown.request.anchor();
    if (!anchor) return;
    const box = el.getBoundingClientRect();
    const place = placeTooltip({
      target: anchor,
      size: { width: box.width, height: box.height },
      viewport: { width: window.innerWidth, height: window.innerHeight },
      side: shown.request.side,
      pointer: shown.request.pointer,
    });
    el.style.left = `${Math.round(place.left)}px`;
    el.style.top = `${Math.round(place.top)}px`;
    el.dataset.placement = place.placement;
  });

  if (!shown) return null;
  const { content } = shown;
  const caps = tooltipMaxSize(content.kind, { width: window.innerWidth, height: window.innerHeight });
  return createPortal(
    <div
      ref={ref}
      id={id}
      role="tooltip"
      data-curio-tooltip=""
      className={`${styles.tooltip} ${content.kind === "text" ? styles.text : styles.rich}`}
      style={{ maxWidth: caps.maxWidth, maxHeight: caps.maxHeight }}
    >
      {content.kind === "text" ? content.text : content.node}
    </div>,
    document.body,
  );
}

export default TooltipLayer;
