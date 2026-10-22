/**
 * The one Curio tooltip's state and timing, shared by everything that shows
 * one: the TooltipLayer, for the `data-tooltip` of an element or the content
 * it registered with useTooltipContent; an editor's hover (useEditorTooltip);
 * a chart's marks, through their element's `data-tooltip` (vegaTooltip.ts).
 *
 * One tooltip at a time. It shows TOOLTIP_SHOW_DELAY_MS after the pointer
 * rests on what it describes, each move starting the wait again, and at once
 * while another is open or within TOOLTIP_WARM_MS of one closing. It hides
 * TOOLTIP_HIDE_DELAY_MS after the pointer leaves, so the pointer can move onto
 * it, and at once on hide(). A tooltip the keyboard's focus or a held touch
 * opened is not the pointer's to close.
 */
import type React from "react";
import type { TooltipBox, TooltipSide } from "./tooltipPlacement";

export const TOOLTIP_SHOW_DELAY_MS = 400;
export const TOOLTIP_WARM_MS = 600;
export const TOOLTIP_HIDE_DELAY_MS = 100;
/** How long a touch is held before it shows a tooltip. */
export const TOOLTIP_HOLD_MS = 500;

export interface TooltipTimings {
  show: number;
  warm: number;
  hide: number;
  hold: number;
}

const DEFAULT_TIMINGS: TooltipTimings = {
  show: TOOLTIP_SHOW_DELAY_MS,
  warm: TOOLTIP_WARM_MS,
  hide: TOOLTIP_HIDE_DELAY_MS,
  hold: TOOLTIP_HOLD_MS,
};
/** The waits now in force. */
const timings: TooltipTimings = { ...DEFAULT_TIMINGS };

/**
 * Change the waits, as a test does that reads a tooltip without timing it
 * (`setTooltipTimings({ show: 0 })`). Returns what puts them back.
 */
export function setTooltipTimings(next: Partial<TooltipTimings>): () => void {
  Object.assign(timings, next);
  return () => {
    Object.assign(timings, DEFAULT_TIMINGS);
  };
}

/** The wait a held touch takes before it shows a tooltip. */
export function tooltipHoldMs(): number {
  return timings.hold;
}

/** What a tooltip shows: plain text, or content a target registered. */
export type TooltipContent = { kind: "text"; text: string } | { kind: "preview"; node: React.ReactNode };

export interface TooltipRequest {
  /** What asks: the element itself, or a key an editor chooses. Equal keys are one tooltip. */
  key: unknown;
  /** The element the tooltip describes, which gets its aria-describedby while it shows. */
  target: Element | null;
  /** The box it is placed from, read each time it is placed. */
  anchor: () => TooltipBox | null;
  side: TooltipSide;
  /** Where the pointer is, for a tooltip that goes there. */
  pointer: { x: number; y: number } | null;
  /** What it says, or a read of it, made when it is about to show. */
  content: TooltipContent | (() => Promise<TooltipContent | null>);
}

/** What opened the tooltip on screen. */
export type TooltipVia = "pointer" | "focus" | "touch";

export interface ShownTooltip {
  request: TooltipRequest;
  content: TooltipContent;
  via: TooltipVia;
}

export interface TooltipState {
  shown: ShownTooltip | null;
}

let state: TooltipState = { shown: null };
const listeners = new Set<() => void>();
/** Content targets registered with useTooltipContent, by their `data-tooltip-content` id. */
const registered = new Map<string, React.ReactNode>();

let pending: TooltipRequest | null = null;
/** A request whose content is being read. */
let reading: TooltipRequest | null = null;
let showTimer: ReturnType<typeof setTimeout> | null = null;
let hideTimer: ReturnType<typeof setTimeout> | null = null;
let closedAt = Number.NEGATIVE_INFINITY;
/** Bumped by each show and hide, so a read that comes back late is dropped. */
let generation = 0;

function emit(next: TooltipState): void {
  state = next;
  for (const listener of listeners) listener();
}

function stopShowing(): void {
  if (showTimer !== null) clearTimeout(showTimer);
  showTimer = null;
  pending = null;
}

function stopHiding(): void {
  if (hideTimer !== null) clearTimeout(hideTimer);
  hideTimer = null;
}

function sameContent(a: TooltipContent, b: TooltipContent): boolean {
  if (a.kind === "text" && b.kind === "text") return a.text === b.text;
  return a.kind === "preview" && b.kind === "preview" && a.node === b.node;
}

function present(request: TooltipRequest, via: TooltipVia): void {
  stopShowing();
  stopHiding();
  const ticket = ++generation;
  if (typeof request.content !== "function") {
    reading = null;
    emit({ shown: { request, content: request.content, via } });
    return;
  }
  reading = request;
  request.content().then(
    (content) => {
      if (ticket !== generation) return;
      reading = null;
      if (content) emit({ shown: { request, content, via } });
      else conceal();
    },
    () => {
      if (ticket === generation) conceal();
    },
  );
}

function conceal(): void {
  stopShowing();
  stopHiding();
  generation += 1;
  reading = null;
  if (state.shown) {
    closedAt = Date.now();
    emit({ shown: null });
  }
}

export const tooltipStore = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },

  getState(): TooltipState {
    return state;
  },

  /** The pointer rests on, or moves over, what *request* describes. */
  rest(request: TooltipRequest): void {
    const shown = state.shown;
    stopHiding();
    if (shown && shown.request.key === request.key) {
      // Open already: it follows what its target says and where the pointer is.
      const content = typeof request.content === "function" ? shown.content : request.content;
      if (!sameContent(shown.content, content) || shown.request.pointer !== request.pointer) {
        emit({ shown: { ...shown, request, content } });
      }
      return;
    }
    if (reading && reading.key === request.key) return;
    if (shown || Date.now() - closedAt < timings.warm) {
      present(request, "pointer");
      return;
    }
    stopShowing();
    pending = request;
    showTimer = setTimeout(() => {
      showTimer = null;
      const next = pending;
      pending = null;
      if (next) present(next, "pointer");
    }, timings.show);
  },

  /** The pointer left what *key* names, or everything when no key is given. */
  leave(key?: unknown): void {
    if (pending && (key === undefined || pending.key === key)) stopShowing();
    if (reading && (key === undefined || reading.key === key)) {
      generation += 1;
      reading = null;
    }
    const shown = state.shown;
    if (!shown || shown.via !== "pointer" || (key !== undefined && shown.request.key !== key)) return;
    if (hideTimer === null) {
      hideTimer = setTimeout(() => {
        hideTimer = null;
        conceal();
      }, timings.hide);
    }
  },

  /** The pointer is on the tooltip itself: it stays. */
  keep(): void {
    stopHiding();
  },

  /** Show *request* now: the keyboard's focus or a held touch asked for it. */
  show(request: TooltipRequest, via: TooltipVia): void {
    present(request, via);
  },

  /** Hide it now: a press, a wheel, a scroll, a drag, Escape, the window losing focus. */
  hide(): void {
    conceal();
  },

  /** The keyboard's focus left *target*: a tooltip its focus opened goes. */
  blurred(target: Element): void {
    const shown = state.shown;
    if (shown && shown.via === "focus" && shown.request.target === target) conceal();
  },

  /** Whether a tooltip is on screen. */
  isShown(): boolean {
    return state.shown !== null;
  },

  /** The content a target registered with useTooltipContent, by its id. */
  registered(id: string): React.ReactNode | undefined {
    return registered.get(id);
  },

  /** A target's content, registered or changed; the tooltip showing it follows. */
  register(id: string, node: React.ReactNode): void {
    registered.set(id, node);
    const shown = state.shown;
    if (shown && shown.request.target?.getAttribute("data-tooltip-content") === id && shown.content.kind === "preview") {
      if (shown.content.node !== node) emit({ shown: { ...shown, content: { kind: "preview", node } } });
    }
  },

  unregister(id: string): void {
    registered.delete(id);
  },
};

/** Hide the tooltip now: the canvas moved under it. */
export function hideTooltip(): void {
  tooltipStore.hide();
}
