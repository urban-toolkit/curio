import './descriptors';
import '../adapters/vegaLiteAdapter';
import '../adapters/utkAdapter';

export {
  registerNode,
  getNodeDescriptor,
  getAllNodeTypes,
  getPaletteNodeTypes,
} from './nodeRegistry';

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
