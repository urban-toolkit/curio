import './builtinLifecycles';
import './iconRegistry';
import '../adapters/vegaLiteAdapter';

export {
  registerNode,
  getNodeDescriptor,
  tryGetNodeDescriptor,
  getAllNodeTypes,
  getPaletteNodeTypes,
  subscribeToRegistry,
} from './nodeRegistry';

export type { NodeKindId, NodeSource, NodePackageMeta } from './types';

export {
  registerGrammarAdapter,
  getGrammarAdapter,
  getAllGrammarAdapters,
} from './grammarAdapter';

export {
  registerLifecycle,
  getLifecycle,
  getAllLifecycleNames,
} from './lifecycleRegistry';

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
