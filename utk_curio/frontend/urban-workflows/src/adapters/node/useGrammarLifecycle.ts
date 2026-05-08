
import { useRef } from 'react';
import { NodeLifecycleHook } from '../../registry/types';
import { getNodeDescriptor } from '../../registry/nodeRegistry';
import { VisualizationIR } from '../../integration_layer/ir';
import { executeVisualization } from '../../integration_layer/visualizationIntegrationLayer';
import { getAllGrammarAdapters, getGrammarAdapter } from '../../registry/grammarAdapter';
const metrics = {
  startTime: 0,
  inputSize: 0,
  success: 0,
  failure: 0,
};

export const useGrammarLifecycle: NodeLifecycleHook = (data, boxState) => {
  const stateRef = useRef<any>(null);

  const applyGrammar = async (spec: string) => {
    const start = performance.now(); 
    metrics.startTime = start;
    try {
      console.log('applyGrammar called', { spec, nodeType: data.nodeType });
      console.log(
  'Registered adapters:',
  getAllGrammarAdapters().map(a => a.grammarId)
);
      const descriptor = getNodeDescriptor(data.nodeType);

      if (!descriptor?.grammarId) {
        throw new Error(`No grammarId configured for node type: ${data.nodeType}`);
      }

      const outputId = descriptor.adapter?.editor?.outputId?.(data.nodeId);
      if (!outputId) {
        throw new Error(`No output container configured for node type: ${data.nodeType}`);
      }

      metrics.inputSize = JSON.stringify(data.input || {}).length;
      

      const ir: VisualizationIR = {
        grammarId: descriptor.grammarId,
        spec,
        data: data.input,
        nodeId: data.nodeId,
        containerId: outputId,
        boxType: data.nodeType,
        options: {
          outputCallback: data.outputCallback,
          interactionsCallback: data.interactionsCallback,
          stateRef,
        },
      };

      console.log('Constructed VisualizationIR', ir);

      boxState.setOutput({ code: 'exec', content: '', outputType: '' });

      const result = await executeVisualization(ir);

      const end = performance.now();

      const duration = end - start;

      console.log('📊 METRICS (SUCCESS)', {
      executionTimeMs: duration,
      inputSizeBytes: metrics.inputSize,
      grammarId: descriptor.grammarId,
      nodeType: data.nodeType,
    });

      if (!result.success) {
        throw new Error(result.error || 'Visualization execution failed');
      }

      boxState.setOutput({ code: 'success', content: '', outputType: '' });
      data.outputCallback(data.nodeId, data.input);

    } catch (error: any) {
      boxState.setOutput({
        code: 'error',
        content: error?.message || 'Visualization execution failed',
        outputType: '',
      });
    }
  };

  return { applyGrammar };
};