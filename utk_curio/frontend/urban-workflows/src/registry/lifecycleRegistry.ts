/**
 * LifecycleRegistry: pluggable interface for node lifecycle hooks.
 *
 * Manifests can't carry JS code, so each kind references a lifecycle by
 * string key (e.g. `"code"`, `"vega"`). Built-in lifecycles are
 * registered at app startup via `builtinLifecycles.ts`; third-party packs
 * pick from the same set when authoring their manifest's `lifecycle` field.
 */

import type { NodeLifecycleHook } from './types';

const lifecycleRegistry = new Map<string, NodeLifecycleHook>();

export function registerLifecycle(name: string, hook: NodeLifecycleHook): void {
  if (lifecycleRegistry.has(name)) {
    console.warn(`Lifecycle "${name}" already registered; overwriting.`);
  }
  lifecycleRegistry.set(name, hook);
}

export function getLifecycle(name: string): NodeLifecycleHook | undefined {
  return lifecycleRegistry.get(name);
}

export function getAllLifecycleNames(): string[] {
  return Array.from(lifecycleRegistry.keys());
}
