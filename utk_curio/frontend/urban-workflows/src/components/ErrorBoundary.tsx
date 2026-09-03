import React from "react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  /** Rendered in place of the subtree that threw. Given the error so a caller
   *  can name it; defaults to a short inline notice. */
  fallback?: (error: Error) => React.ReactNode;
  /** Names the subtree in the console line, e.g. "node autk-1". */
  label?: string;
  onError?: (error: Error, info: React.ErrorInfo) => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Contains a render-time throw so one broken subtree cannot take the app (#201).
 *
 * There was no error boundary anywhere in the app, so a throw from a single
 * node's content unmounted the entire React root and left a blank page with
 * the canvas, the menus and every other node gone. The reported case was an
 * Autark node on a browser without WebGPU, but the blast radius is the point:
 * any node that throws while rendering does this.
 *
 * Deliberately does NOT catch async failures - `componentDidCatch` never sees
 * a rejected promise. Those are handled where they are raised (see
 * `applyGrammar`'s WebGPU guard) and by the `unhandledrejection` logger in
 * `index.tsx`.
 *
 * `onError` is also how a node reports a render throw into its own output
 * (UniversalNode), and `reset` / the default fallback's "Try again" let the
 * subtree remount once whatever broke it has changed (#271).
 */
export default class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  /** Drop the caught error and render the children again. */
  reset = (): void => {
    this.setState({ error: null });
  };

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    const where = this.props.label ? ` in ${this.props.label}` : "";
    console.error(`[ErrorBoundary] contained a render error${where}:`, error, info);
    this.props.onError?.(error, info);
  }

  render(): React.ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error);
    return (
      <div
        role="alert"
        style={{
          padding: "12px 14px",
          margin: 8,
          border: "1px solid var(--curio-danger, #c0392b)",
          borderRadius: "var(--curio-radius-md, 6px)",
          background: "var(--curio-danger-bg, rgba(192, 57, 43, 0.08))",
          color: "var(--curio-danger-strong, #922b21)",
          fontSize: "var(--curio-font-size-md, 13px)",
          lineHeight: 1.45,
        }}
      >
        <strong>Something went wrong here.</strong>
        <div style={{ marginTop: 4 }}>
          {error.message || "This part of the page could not be rendered."}
        </div>
        <div style={{ marginTop: 4, opacity: 0.8 }}>
          The rest of the dataflow is unaffected.
        </div>
        <button
          type="button"
          onClick={this.reset}
          style={{
            marginTop: 8,
            padding: "4px 10px",
            border: "1px solid currentColor",
            borderRadius: "var(--curio-radius-sm, 4px)",
            background: "transparent",
            color: "inherit",
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </div>
    );
  }
}
