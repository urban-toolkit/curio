/**
 * Send browser runtime errors to the monitor's error log.
 *
 * The server sees nothing of what happens after the bundle loads, so a render
 * crash or a rejected promise leaves no trace anywhere. This closes that half.
 *
 * Every guard below exists because a crash reporter is the one piece of code
 * that runs while things are already going wrong:
 *
 * - **It never throws.** An exception raised from a window error handler
 *   re-enters the handler.
 * - **It never awaits and never retries.** `postClientError` ignores the
 *   response entirely; the server answers 204 to everything for the same
 *   reason.
 * - **It stops after MAX_REPORTS_PER_LOAD.** A component throwing on every
 *   frame would otherwise post thousands of times. The server rate-limits too,
 *   but the cheapest request is the one never sent.
 * - **It is installed once.** A second install would double every report.
 * - **It leaves out the browser's ResizeObserver loop notice**, which is no
 *   error: see `isResizeObserverLoopNotice`.
 */
import { postClientError } from "../api/monitorApi";

export const MAX_REPORTS_PER_LOAD = 5;

/**
 * What the browser says, as a window `error` event with no error object, when
 * a ResizeObserver callback changes a size it observes, so that the new size
 * reaches its observer a frame later. Nothing threw, so it is not reported.
 * webpack.config.js keeps it off the dev server's overlay too.
 */
export const RESIZE_OBSERVER_LOOP_NOTICE =
  "ResizeObserver loop completed with undelivered notifications.";

/** Whether *event* is that notice: its exact words, with no error object.
 *  An `Error` thrown with the same words is still an error. */
export function isResizeObserverLoopNotice(event: Pick<ErrorEvent, "message" | "error">): boolean {
  return event.error == null && event.message === RESIZE_OBSERVER_LOOP_NOTICE;
}

let installed = false;
let sent = 0;
let reporting = false;

function report(message: string, stack: string): void {
  // `reporting` guards against a failure inside this function re-entering it
  // through the very handler that called it.
  if (reporting || sent >= MAX_REPORTS_PER_LOAD) return;
  reporting = true;
  try {
    sent += 1;
    postClientError({
      message: String(message || "Unknown browser error").slice(0, 2000),
      stack: String(stack || "").slice(0, 8000),
      url: typeof location !== "undefined" ? location.href : "",
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "",
    });
  } catch {
    /* a reporter that fails must stay silent */
  } finally {
    reporting = false;
  }
}

export function installClientErrorReporter(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;

  window.addEventListener("error", (event: ErrorEvent) => {
    // Before the count: a page whose layout loops every frame would spend
    // every report it may send on the notice, and its real errors go unsent.
    if (isResizeObserverLoopNotice(event)) return;
    const error = event.error;
    report(
      event.message || error?.message || "Unhandled error",
      error?.stack || `${event.filename ?? ""}:${event.lineno ?? ""}`
    );
  });

  window.addEventListener(
    "unhandledrejection",
    (event: PromiseRejectionEvent) => {
      const reason: any = event.reason;
      report(
        reason?.message || String(reason) || "Unhandled promise rejection",
        reason?.stack || ""
      );
    }
  );
}
