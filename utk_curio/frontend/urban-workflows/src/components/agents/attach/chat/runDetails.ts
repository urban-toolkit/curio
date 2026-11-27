/**
 * Show run details: the viewer's own switch, in the chat's More menu, off
 * until they turn it on. On, each reply shows what its run used: the skills it
 * held, its time and tokens, the tools it called, and the agents it asked;
 * the plan line its pass, and a card of a run's trace. It is the viewer's
 * alone, kept in this browser, the same in every chat and every dataflow:
 * what one person reads changes nothing another sees. A browser that keeps
 * nothing (a private window, blocked site data) starts it off each time.
 */
import { useSyncExternalStore } from "react";

/** Where this browser keeps the switch. */
export const RUN_DETAILS_KEY = "curio.agentChat.showRunDetails";

const listeners = new Set<() => void>();
let shown: boolean | null = null;

function read(): boolean {
  if (shown === null) {
    try {
      shown = window.localStorage.getItem(RUN_DETAILS_KEY) === "on";
    } catch {
      shown = false;
    }
  }
  return shown;
}

/** Turns run details on or off, for every chat this viewer opens. */
export function setRunDetailsShown(on: boolean): void {
  shown = on;
  try {
    if (on) window.localStorage.setItem(RUN_DETAILS_KEY, "on");
    else window.localStorage.removeItem(RUN_DETAILS_KEY);
  } catch {
    // Kept for this page only.
  }
  listeners.forEach((listener) => listener());
}

/** Forgets the switch as read, so the next read takes it from the browser
 * again: tests start each case from what they put there. */
export function resetRunDetailsForTests(): void {
  shown = null;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Whether this viewer shows run details, and its setter. */
export function useRunDetails(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, read, () => false);
  return [on, setRunDetailsShown];
}
