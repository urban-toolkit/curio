import React from 'react';
import { BoxLifecycleHook } from '../../registry/types';
import OutputContent from '../../components/editing/OutputContent';

export const useCodeBoxLifecycle: BoxLifecycleHook = (_data, boxState) => {
  const contentComponent = React.useMemo(
    () => <OutputContent output={boxState.output} />,
    [boxState.output],
  );

  return { contentComponent };
};
