import { useEffect, useState } from "react";
import { formatElapsed, LABEL_ROTATE_SECONDS, PROCESSING_LABELS } from "./agentRunStatus";

/**
 * One 1 s ticker driving the live run indicator (memo dev/80): the elapsed
 * readout from `startedAt` plus the rotating processing label. The label
 * index derives from elapsed seconds — deterministic, never random — so a
 * chat reopened mid-run resumes the correct elapsed AND label. Under
 * prefers-reduced-motion the label pins to the first entry (the dot's CSS
 * animation is disabled separately via the component's media query). A null
 * `startedAt` runs no interval.
 */
export function useRunTicker(startedAt: number | null): {
  elapsedLabel: string;
  processingLabel: string;
} {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  if (startedAt === null) {
    return { elapsedLabel: "", processingLabel: PROCESSING_LABELS[0] };
  }
  const elapsedMs = Math.max(0, now - startedAt);
  const reduceMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const index = reduceMotion
    ? 0
    : Math.floor(elapsedMs / 1000 / LABEL_ROTATE_SECONDS) % PROCESSING_LABELS.length;
  return { elapsedLabel: formatElapsed(elapsedMs), processingLabel: PROCESSING_LABELS[index] };
}
