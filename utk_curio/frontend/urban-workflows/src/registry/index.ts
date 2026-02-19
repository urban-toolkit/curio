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
  BoxDescriptor,
  PortDef,
  EditorType,
  BoxCategory,
  HandleDef,
  EditorConfig,
  ContainerConfig,
  BoxAdapter,
  BoxLifecycleHook,
  BoxLifecycleData,
  LifecycleResult,
  UseBoxStateReturn,
} from './types';

export type {
  GrammarAdapter,
} from './grammarAdapter';
