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
 *   leaving hides it a moment later, and the pointer may cross over onto it.
 *   Leaving the tooltip hides it the same way, whoever opened it. One at the
 *   pointer (a chart's) lets the pointer through to the marks under it;
 * - a press on a target hides it, and it stays off while the pointer stays on
 *   that target; a press inside the tooltip keeps it. A press on a chart
 *   leaves its marks' tooltips on;
 * - a wheel, a drag, Escape or the window losing focus hide it, and so does a
 *   scroll of what holds the element it is placed beside;
 * - focus from the keyboard shows it at once, until blur or Escape, and the
 *   focused control is the one it describes. The layer tells keyboard focus
 *   from a click's by which came last, a key or a press: jsdom's
 *   :focus-visible does not decide it as Chrome does;
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

/** The side *target* asks for. */
function sideOf(target: Element): TooltipSide {
  const asked = target.getAttribute("data-tooltip-side") as TooltipSide | null;
  return asked && SIDES.includes(asked) ? asked : "top";
}

/** The tooltip *target* asks for, or null when it says nothing. */
function requestFor(target: Element, pointer: { x: number; y: number } | null): TooltipRequest | null {
  const content = contentOf(target);
  if (!content) return null;
  const side = sideOf(target);
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
  const described = shown ? (shown.request.describes ?? shown.request.target) : null;

  useEffect(() => {
    /** What the pointer is over, and where it is. */
    let hovered: Element | null = null;
    let pointer: { x: number; y: number } | null = null;
    /** A target a press closed: its tooltip stays off while the pointer stays on it. */
    let pressed: Element | null = null;
    /** The target this layer last asked a tooltip for; it lets go of no other, an editor's included. */
    let current: Element | null = null;
    /** Whether the pointer is on the tooltip, whoever opened it. */
    let onTip = false;
    /** Whether a mouse button is held: a drag asks for no tooltip on its way. */
    let buttonDown = false;
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
      const el = hovered && hovered.isConnected ? hovered : null;
      if (el && inTooltip(el)) {
        onTip = true;
        tooltipStore.keep();
        return;
      }
      if (onTip) {
        // Off the tooltip: it goes a moment later, whoever opened it (an
        // editor's included), unless what the pointer is on now asks for it.
        onTip = false;
        tooltipStore.leave();
      }
      if (!el) {
        letGo();
        return;
      }
      const target = targetOf(el);
      if (pressed && target !== pressed) pressed = null;
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
      if (event.pointerType === "touch") return;
      buttonDown = event.buttons !== 0;
      if (buttonDown) return;
      hovered = event.target instanceof Element ? event.target : null;
      pointer = { x: event.clientX, y: event.clientY };
      settle();
    };
    // On the way up, so a chart that rewrites its tooltip at a move has done so.
    const onMove = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      buttonDown = event.buttons !== 0;
      if (buttonDown) return;
      hovered = event.target instanceof Element ? event.target : hovered;
      pointer = { x: event.clientX, y: event.clientY };
      settle();
    };
    const onOut = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.relatedTarget) return;
      // Out of the window, from the tooltip or from anything else.
      hovered = null;
      settle();
    };
    const onDown = (event: PointerEvent) => {
      keyboard = false;
      const el = event.target instanceof Element ? event.target : null;
      if (event.pointerType !== "touch") buttonDown = true;
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
      // A chart's marks each say their own: a press on one leaves the others on.
      const target = targetOf(el);
      pressed = target && sideOf(target) !== "pointer" ? target : null;
      tooltipStore.hide();
    };
    const onUp = (event: PointerEvent) => {
      if (event.pointerType === "touch") stopHold();
      else buttonDown = false;
    };
    const onKey = (event: KeyboardEvent) => {
      keyboard = true;
      if (event.key === "Escape") tooltipStore.hide();
    };
    const onFocus = (event: FocusEvent) => {
      if (!keyboard) return;
      const focused = event.target instanceof Element ? event.target : null;
      const target = targetOf(focused);
      const request = target ? requestFor(target, null) : null;
      // It describes the control with the focus: the target, or a control in it.
      if (request) tooltipStore.show({ ...request, describes: focused }, "focus");
    };
    const onBlur = (event: FocusEvent) => {
      const target = targetOf(event.target);
      if (target) tooltipStore.blurred(target);
    };
    const hide = () => tooltipStore.hide();
    // A scroll moves what it scrolls: a tooltip beside something in it goes,
    // and one beside anything else stays (a chat that scrolls as it streams).
    const onScroll = (event: Event) => {
      const open = tooltipStore.getState().shown;
      if (!open) return;
      const beside = open.request.anchorElement ?? open.request.target;
      const scrolled = event.target;
      if (!beside || !(scrolled instanceof Node) || scrolled.contains(beside)) tooltipStore.hide();
    };

    // A target's tooltip changed under the pointer, or appeared (a chart
    // writes its mark's tooltip at the move that reaches the mark); or the
    // target of one the keyboard opened changed what it says. During a drag
    // the pointer last seen is from before the press, so nothing is asked for.
    const observer = new MutationObserver((records) => {
      const el = hovered;
      if (el && !buttonDown && records.some((record) => record.target instanceof Element && record.target.contains(el))) {
        settle();
      }
      for (const record of records) {
        const changed = record.target;
        if (!(changed instanceof Element)) continue;
        // One that no longer asks for a tooltip says nothing: the one open for it goes.
        tooltipStore.refresh(changed, changed.matches(TARGET) ? contentOf(changed) : null);
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
    document.addEventListener("scroll", onScroll, passive);
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
      document.removeEventListener("scroll", onScroll, passive);
      document.removeEventListener("dragstart", hide, capture);
      window.removeEventListener("blur", hide);
    };
  }, []);

  // The element it describes names the tooltip while it shows.
  useLayoutEffect(() => {
    if (!described) return undefined;
    describe(described, id, true);
    return () => describe(described, id, false);
  }, [described, id]);

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
    // Measured at the window's corner, with all the room it may take: at its
    // last place near the right edge it would wrap narrower than it is.
    el.style.left = "0px";
    el.style.top = "0px";
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
  // One at the pointer sits just above it: the pointer goes through to the marks.
  const through = shown.request.side === "pointer" ? ` ${styles.through}` : "";
  return createPortal(
    <div
      ref={ref}
      id={id}
      role="tooltip"
      data-curio-tooltip=""
      className={`${styles.tooltip} ${content.kind === "text" ? styles.text : styles.rich}${through}`}
      style={{ maxWidth: caps.maxWidth, maxHeight: caps.maxHeight }}
    >
      {content.kind === "text" ? content.text : content.node}
    </div>,
    document.body,
  );
}

export default TooltipLayer;
