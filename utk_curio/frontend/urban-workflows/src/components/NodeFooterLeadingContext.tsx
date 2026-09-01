import React, { createContext, useContext } from "react";

const NodeFooterLeadingContext = createContext<React.ReactNode>(null);

export function NodeFooterLeadingProvider({
  value,
  children,
}: {
  value: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <NodeFooterLeadingContext.Provider value={value}>
      {children}
    </NodeFooterLeadingContext.Provider>
  );
}

export function useNodeFooterLeading(): React.ReactNode {
  return useContext(NodeFooterLeadingContext);
}
