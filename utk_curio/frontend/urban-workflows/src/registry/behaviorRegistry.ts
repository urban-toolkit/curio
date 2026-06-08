/**
 * BehaviorRegistry: pluggable interface for node behavior hooks.
 *
 * Manifests can't carry JS code, so each kind references a behavior by
 * string key (e.g. `"code"`, `"vega"`). Built-in behaviors are
 * registered at app startup via `builtinBehaviors.ts`; third-party packages
 * pick from the same set when authoring their manifest's `behavior` field.
 */

import type { NodeBehaviorHook } from './types';

const behaviorRegistry = new Map<string, NodeBehaviorHook>();

export function registerBehavior(name: string, hook: NodeBehaviorHook): void {
  if (behaviorRegistry.has(name)) {
    console.warn(`Behavior "${name}" already registered; overwriting.`);
  }
  behaviorRegistry.set(name, hook);
}

export function getBehavior(name: string): NodeBehaviorHook | undefined {
  return behaviorRegistry.get(name);
}

export function getAllBehaviorNames(): string[] {
  return Array.from(behaviorRegistry.keys());
}
