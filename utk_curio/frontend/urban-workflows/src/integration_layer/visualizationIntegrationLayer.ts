import { getAllGrammarAdapters, getGrammarAdapter } from '../registry/grammarAdapter';
import { VisualizationIR, VisualizationRenderResult } from './ir';
console.log(
  'Registered adapters:',
  getAllGrammarAdapters().map(a => a.grammarId)
);

function resolveContainer(
  container: HTMLElement | string | null | undefined,
  retries = 10,
  interval = 50
): Promise<HTMLElement> {
  console.log('resolveContainer called', { container, retries, interval });
  return new Promise((resolve, reject) => {
    if (container instanceof HTMLElement) return resolve(container);
    if (!container) return reject(new Error('Missing visualization container'));

    let attempts = 0;
    const poll = () => {
      const el = document.getElementById(container as string);
      if (el) return resolve(el);
      if (++attempts >= retries) return reject(new Error(`Container not found: ${container}`));
      setTimeout(poll, interval);
    };
    poll();
  });
}

export async function executeVisualization(
  ir: VisualizationIR
): Promise<VisualizationRenderResult> {
  try {
    console.log('executeVisualization called', { 
    grammarId: ir.grammarId, 
    containerId: ir.containerId,
    nodeId: ir.nodeId,
  });
    if (!ir.grammarId) {
      throw new Error('Visualization request is missing grammarId');
    } 

    const resolvedInput = ir.container ?? ir.containerId;

    console.log('container input:', resolvedInput);

    const adapter = getGrammarAdapter(ir.grammarId);
    console.log('Adapter found for grammarId:', ir.grammarId, adapter);
    const container = await resolveContainer(ir.container ?? ir.containerId);

    if (!ir.options?.skipValidation && adapter.validate) {
      if (!adapter.validate(ir.spec)) {
        throw new Error(`Invalid visualization spec for grammarId: ${ir.grammarId}`);
      }
    }

    await adapter.render(
      container,
      ir.spec,
      ir.data,
      {
        ...ir.options,
        nodeId: ir.nodeId, // always forward nodeId into options
      }
    );

    return {
      success: true,
      grammarId: ir.grammarId,
      output: undefined,
    };
  } catch (error: any) {
    return {
      success: false,
      grammarId: ir.grammarId,
      error: error?.message || 'Visualization execution failed',
    };
  }
}