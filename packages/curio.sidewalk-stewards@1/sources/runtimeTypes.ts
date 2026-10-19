import type React from 'react';

/** Structural subset of Curio's package behavior API; no runtime import. */
export interface SidewalkBehaviorData {
  nodeId: string;
  input: unknown;
  interactions?: unknown;
  outputCallback: (nodeId: string, output: unknown) => void;
  interactionsCallback: (interactions: unknown, nodeId: string) => void;
}

export interface SidewalkNodeState {
  code: string;
  setCode: (code: string) => void;
  setOutput: (status: { code: string; content: string }) => void;
}

export interface SidewalkBehaviorResult { contentComponent?: React.ReactNode; disablePlay?: boolean; sendCodeOverride?: (code: string) => Promise<void>; }
