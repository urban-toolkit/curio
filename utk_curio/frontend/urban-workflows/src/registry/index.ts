import './descriptors';
import '../adapters/vegaLiteAdapter';

export {
  registerNode,
  getNodeDescriptor,
  tryGetNodeDescriptor,
  getAllNodeTypes,
  getPaletteNodeTypes,
  subscribeToRegistry,
} from './nodeRegistry';

export type { NodeKindId, NodeSource, NodePackMeta } from './types';

export {
  registerGrammarAdapter,
  getGrammarAdapter,
  getAllGrammarAdapters,
} from './grammarAdapter';

export type {
  NodeDescriptor,
  PortDef,
  EditorType,
  NodeCategory,
  HandleDef,
  EditorConfig,
  ContainerConfig,
  NodeAdapter,
  NodeLifecycleHook,
  NodeLifecycleData,
  LifecycleResult,
  UseNodeStateReturn,
} from './types';

export type {
  GrammarAdapter,
} from './grammarAdapter';
