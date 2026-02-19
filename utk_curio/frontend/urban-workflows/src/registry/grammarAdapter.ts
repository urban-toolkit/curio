/**
 * GrammarAdapter: pluggable interface for grammar-based visualizations.
 *
 * Each grammar toolkit (Vega-Lite, UTK, future D3/Scout) implements this
 * interface and registers itself via registerGrammarAdapter().
 *
 * GrammarVisBox (or individual grammar boxes) call getGrammarAdapter(grammarId)
 * to obtain the correct adapter at runtime.
 */

export interface GrammarAdapter {
  grammarId: string;

  /** Validate a grammar specification before rendering. */
  validate(spec: unknown): boolean;

  /** Compile and render a grammar spec into the given container. */
  render(
    container: HTMLElement,
    spec: unknown,
    data?: unknown,
    options?: { interactions?: unknown; resolutionMode?: string }
  ): void | Promise<void>;

  /** Return a minimal default spec for this grammar. */
  getDefaultSpec?(): unknown;

  /** Cleanup resources (e.g. dispose Vega views, remove event listeners). */
  cleanup?(): void;
}

const grammarRegistry = new Map<string, GrammarAdapter>();

export function registerGrammarAdapter(adapter: GrammarAdapter): void {
  grammarRegistry.set(adapter.grammarId, adapter);
}

export function getGrammarAdapter(grammarId: string): GrammarAdapter {
  const adapter = grammarRegistry.get(grammarId);
  if (!adapter) throw new Error(`No grammar adapter registered for: ${grammarId}`);
  return adapter;
}

export function getAllGrammarAdapters(): GrammarAdapter[] {
  return Array.from(grammarRegistry.values());
}
