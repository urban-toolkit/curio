import { useFlowContext } from '../../../utk_curio/frontend/urban-workflows/src/providers/FlowProvider';
import { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';


//todo: create a behavior hook for soft artifact behavior
export const useSoftArtifactBehavior: NodeBehaviorHook = (data, nodeState) => {
  
  const contentComponent = (
    <div>
      <p>aaaa</p>
    </div>
  )
  return {
    contentComponent
  };
}