import './builtinLifecycles';
import './iconRegistry';
import '../adapters/vegaLiteAdapter';

// ── Dynamic-package globals ────────────────────────────────────────────
//
// Packages declaring `manifest.lifecycleScript` ship a pre-built
// `lifecycles.js` that gets loaded via <script> injection at boot
// (see `packageRegistryBootstrap.loadPackageLifecycleScripts`). That
// bundle externalises React, ReactFlow, and a `registerLifecycle`
// function — we expose them on `window` so the package bundle's
// `const React = window.React` (etc.) replaces resolve at runtime,
// distinct bundles share Curio's React instance (essential for
// rules-of-hooks), and the bundle's side-effect can register against
// the same lifecycle registry the built-ins use.
//
// Pending registrations: if a package's <script> loads before this
// module runs (race during first paint), it pushes a callback into
// `__curioPendingPackages__`. We drain those here so registration
// completes deterministically.
import * as ReactNS from 'react';
import * as ReactFlowNS from 'reactflow';
import { registerLifecycle } from './lifecycleRegistry';

if (typeof window !== 'undefined') {
  const w = window as any;
  w.React = ReactNS;
  w.ReactFlow = ReactFlowNS;
  // ``backendUrl`` is the runtime resolution of the host's ``BACKEND_URL``
  // env var. Packages should read this instead of inlining
  // ``process.env.BACKEND_URL`` at their own build time — that path bakes
  // the URL into the published catalog bundle and breaks for any
  // deployment that doesn't match the build host.
  w.curio = {
    ...(w.curio ?? {}),
    registerLifecycle,
    backendUrl: process.env.BACKEND_URL ?? '',
  };
  const pending: Array<(c: { registerLifecycle: typeof registerLifecycle }) => void> =
    Array.isArray(w.__curioPendingPackages__) ? w.__curioPendingPackages__ : [];
  for (const fn of pending) {
    try {
      fn(w.curio);
    } catch (e) {
      // One bad package shouldn't take the whole boot down.
      console.error('[curio] pending package registration failed:', e);
    }
  }
  w.__curioPendingPackages__ = [];
}

export {
  registerNode,
  getNodeDescriptor,
  tryGetNodeDescriptor,
  getAllNodeTypes,
  getPaletteNodeTypes,
  subscribeToRegistry,
} from './nodeRegistry';

export type { NodeTemplateId, NodeSource, NodePackageMeta } from './types';

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
