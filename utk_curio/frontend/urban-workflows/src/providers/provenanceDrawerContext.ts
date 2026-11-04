import { createContext, useContext } from "react";

/** A node's runs, as its Provenance pill opens them. */
export interface NodeProvenanceTarget {
  nodeId: string;
  /** The node's name, as its header shows it. */
  title: string;
  /** Puts a run's code back in the node's editor. */
  restore: (code: string) => void;
  /** Shows the node's code, which the server put back (a canvas bound to the
   *  dataflow's doc). */
  showCode?: () => void;
}

/**
 * The provenance drawer's controls, apart from the provider that renders it,
 * so a menu or a node can open the drawer without importing what the drawer
 * draws with.
 */
export type ProvenanceDrawerContextValue = {
  /** The dataflow's versions: View > Provenance. */
  openDataflowProvenance: () => void;
  /** A node's runs: its Provenance pill. */
  openNodeProvenance: (target: NodeProvenanceTarget) => void;
  closeProvenance: () => void;
  isProvenanceOpen: boolean;
};

export const ProvenanceDrawerContext = createContext<ProvenanceDrawerContextValue | null>(null);

/** The drawer's controls, or null outside a dataflow (a test that renders a
 *  menu or a node alone). */
export function useProvenanceDrawerOptional(): ProvenanceDrawerContextValue | null {
  return useContext(ProvenanceDrawerContext);
}
