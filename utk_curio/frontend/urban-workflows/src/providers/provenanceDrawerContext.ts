import { createContext, useContext } from "react";

/**
 * The provenance drawer's controls, apart from the provider that renders it,
 * so a menu can open the drawer without importing what the drawer draws with.
 */
export type ProvenanceDrawerContextValue = {
  /** The dataflow's versions: View > Provenance. */
  openDataflowProvenance: () => void;
  closeProvenance: () => void;
  isProvenanceOpen: boolean;
};

export const ProvenanceDrawerContext = createContext<ProvenanceDrawerContextValue | null>(null);

/** The drawer's controls, or null outside a dataflow (a test that renders a
 *  menu alone). */
export function useProvenanceDrawerOptional(): ProvenanceDrawerContextValue | null {
  return useContext(ProvenanceDrawerContext);
}
