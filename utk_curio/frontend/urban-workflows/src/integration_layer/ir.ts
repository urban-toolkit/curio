/**
 * IR (Intermediate Representation) for visualization execution.
 *
 * This is a lightweight, normalized rendering request shared by:
 * - generic grammar lifecycle
 * - integration layer
 * - backend adapters
 *
 * It is NOT a universal visualization grammar.
 * It simply captures the minimum backend-agnostic information needed
 * to dispatch and execute a visualization render request.
 */

export type GrammarId = 'vega-lite' | 'utk' | string;

export interface VisualizationRenderOptions {
  /**
   * Optional interaction payload used by backends that support
   * linked brushing, selection propagation, etc.
   */
  interactions?: unknown;

  /**
   * Optional strategy for resolving rendering / interaction conflicts.
   * Keep open-ended for future backends.
   */
  resolutionMode?: string;

  /**
   * If true, adapter/integration layer may skip strict validation.
   * Useful for incremental / partial rendering flows if needed later.
   */
  skipValidation?: boolean;
}

export interface VisualizationIR {
  /**
   * Backend grammar identifier.
   * Examples: 'vega-lite', 'utk'
   */
  grammarId: GrammarId;

  /**
   * Raw visualization specification.
   * This remains backend-specific:
   * - Vega-Lite JSON for Vega
   * - UTK grammar object/string for UTK
   */
  spec: unknown;

  /**
   * Input data passed into the visualization backend.
   * This may be:
   * - a resolved in-memory object
   * - a file-backed input descriptor
   * - a dataframe/geodataframe payload
   */
  data?: unknown;

  /**
   * Curio node identity, useful for provenance, debugging,
   * container lookup, and interaction wiring.
   */
  nodeId: string;

  /**
   * DOM container id to render into.
   * The integration layer can resolve this into an HTMLElement.
   * Example:
   * - 'vega' + nodeId
   * - 'utk' + nodeId + 'outer'
   */
  containerId: string;

  /**
   * Optional direct DOM container reference.
   * This lets the integration layer skip DOM lookup if the caller
   * already resolved the container.
   */
  container?: HTMLElement | null;

  /**
   * Optional Curio box type / node type for logging, fallback routing,
   * legacy hook support, or adapter debugging.
   */
  boxType?: string;

  /**
   * Optional execution settings shared across backends.
   */
  options?: VisualizationRenderOptions;
}

export interface VisualizationRenderResult {
  /**
   * Indicates whether rendering completed without throwing.
   */
  success: boolean;

  /**
   * Backend grammar actually used to render.
   */
  grammarId: GrammarId;

  /**
   * Optional backend-specific return value, such as:
   * - Vega View
   * - UTK interpreter / view state
   * - future renderer handles
   */
  output?: unknown;

  /**
   * Optional human-readable error if rendering failed.
   */
  error?: string;

  outputCallback?: (nodeId: string, output: any) => void;
  
  interactionsCallback?: (nodeId: string, interaction: any) => void;
}