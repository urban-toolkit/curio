import React from 'react';
import { NodeLifecycleHook } from '../../registry/types';
import OutputContent from '../../components/editing/OutputContent';

export const useCodeNodeLifecycle: NodeLifecycleHook = (_data, nodeState) => {
  const contentComponent = React.useMemo(
    () => <OutputContent output={nodeState.output} />,
    [nodeState.output],
  );

  return { contentComponent };
};
