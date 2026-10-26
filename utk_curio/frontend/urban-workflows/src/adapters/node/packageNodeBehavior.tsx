/**
 * Behavior hook for package-registered code nodes.
 *
 * Built-in code nodes use the no-op `useCodeNodeBehavior`: the user is
 * expected to pick a preset from the Templates dropdown before running.
 *
 * Package nodes optionally ship a `source` field in the manifest. Reference package:
 * ``<repo_root>/packages/ai.utk.uhvi@1/manifest.json``. A model package's
 * template without one opens with the default cell the backend writes for its
 * model's type (``packages/model.curio.ddrnet23-slim@1``).
 *
 * Semantic — "inject once, at instantiation only":
 *
 *   - When a node is **freshly dropped** onto the canvas (no `code` field
 *     on `data` yet), populate the editor with the manifest's default
 *     template code as soon as the templates feed has it.
 *   - After that, the user owns the editor. Clearing the buffer, picking
 *     a different template, or doing anything else must **not** snap the
 *     default back in place.
 *   - Saved nodes (`data.code` is already defined when the hook first
 *     runs — even if it's an empty string) are left untouched. The user
 *     intentionally saved whatever they saved.
 *   - Except a node saved with no code and none of the widgets its template
 *     declares: it was saved before its template had a starter (a Data
 *     Export from before its code), since a node opened with the starter
 *     holds the template's widgets from then on. It opens with the starter
 *     and the widgets, as a fresh drop does.
 *
 * Implementation:
 *
 *   1. `initialCodeRef` captures `data.code` on the first render of this
 *      mount. `undefined` ⇒ fresh drop; anything else ⇒ restored.
 *   2. `hasInjectedRef` is a one-shot lock so the injection effect runs
 *      at most once per mount, regardless of how many times `nodeState.code`
 *      or the templates feed change afterwards.
 *   3. `override` is stored in component state. Once `CodeEditor`'s
 *      `defaultValueBypass` effect has consumed the value (via the
 *      `defaultValue` prop chain through `UniversalNode` → `NodeEditor`),
 *      we clear the override so subsequent template selections or
 *      clearing actions are not overridden by a stale default.
 */

import { useEffect, useRef, useState } from 'react';
import { useStarterContext, type Starter } from '../../providers/StarterProvider';
import { tryGetNodeDescriptor } from '../../registry/nodeRegistry';
import { packageStarterName } from '../../registry/packageStarter';
import type { NodeBehaviorHook, NodeDescriptor } from '../../registry/types';

/**
 * The code a freshly dropped node of *descriptor* opens with: its manifest's
 * `source` starter, or a model package's default cell, from the starters
 * feed. `undefined` for a template with neither, and until the feed has it.
 */
export function packageStarterCode(
  descriptor: NodeDescriptor | undefined,
  getStarters: (type: string, custom: boolean) => Starter[],
): string | undefined {
  if (!descriptor || descriptor.source !== 'package') return undefined;
  const wantedName = packageStarterName(descriptor);
  if (!wantedName) return undefined;
  const hit = getStarters(descriptor.id, false).find((t) => t.name === wantedName);
  return hit?.code || undefined;
}

/**
 * Whether a node restored with *code* and *widgets* was saved before its
 * template had a starter: no code, and none of the widgets the template
 * declares, which a node opened with the starter holds from then on.
 */
export function savedBeforeItsStarter(
  code: unknown,
  widgets: unknown,
  descriptor: NodeDescriptor | undefined,
): boolean {
  return typeof code === 'string' && code.trim() === '' && widgets === undefined
    && (descriptor?.widgets?.length ?? 0) > 0;
}

export const usePackageNodeBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { getStarters } = useStarterContext();
  const descriptor = tryGetNodeDescriptor(data.nodeType);

  // `data.code` is a runtime mutation that `useNodeState` performs (see
  // `hook/useNodeState.ts` → `useEffect(() => { data.code = code; ... })`).
  // It is not part of the typed `NodeBehaviorData` surface, so we read it
  // through a narrow cast — we only care whether it was *defined* at mount.
  const initialCodeRef = useRef<unknown>((data as { code?: unknown }).code);
  // And whether the node held widgets then: a node saved with no code and
  // none of its template's widgets predates the starter.
  const initialWidgetsRef = useRef<unknown>((data as { widgets?: unknown }).widgets);
  const hasInjectedRef = useRef(false);
  const [override, setOverride] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (hasInjectedRef.current) return;

    // Reload / remount / copy-paste — never inject after instantiation, but
    // into a node saved before its template had a starter.
    if (
      initialCodeRef.current !== undefined
      && !savedBeforeItsStarter(initialCodeRef.current, initialWidgetsRef.current, descriptor)
    ) {
      hasInjectedRef.current = true;
      return;
    }

    // Built-ins and package-less descriptors are out of scope for this hook.
    if (!descriptor || descriptor.source !== 'package') {
      hasInjectedRef.current = true;
      return;
    }

    const wantedName = packageStarterName(descriptor);
    if (!wantedName) {
      hasInjectedRef.current = true;
      return;
    }

    // If the user typed something before templates loaded, respect it.
    if (nodeState.code && nodeState.code.length > 0) {
      hasInjectedRef.current = true;
      return;
    }

    const templates = getStarters(data.nodeType, false);
    const hit = templates.find((t) => t.name === wantedName);
    if (hit?.code) {
      hasInjectedRef.current = true;
      // #662: the starter's [!! name !!] references need the widgets the
      // template declares. Seeded beside the code, once, like the code.
      const node = data as { widgets?: unknown; defaultCode?: unknown };
      if (node.widgets === undefined && descriptor.widgets && descriptor.widgets.length > 0) {
        node.widgets = descriptor.widgets.map((w) => ({ ...w }));
      }
      // A restored node's editor goes back to the code it was loaded with
      // once the override is consumed (UniversalNode's defaultValue): the
      // starter, from now on, not the empty code it was saved with.
      if (initialCodeRef.current !== undefined) node.defaultCode = hit.code;
      setOverride(hit.code);
    }
    // else: templates not loaded yet — wait for the next effect run.
  }, [descriptor, data.nodeType, getStarters, nodeState.code]);

  // After CodeEditor consumes the override (its `defaultValueBypass`
  // effect copies the value into the Monaco buffer + nodeState), drop
  // the override so the user can clear the editor or switch templates
  // without it snapping back.
  useEffect(() => {
    if (override !== undefined) setOverride(undefined);
  }, [override]);

  return override !== undefined ? { defaultValueOverride: override } : {};
};

/** The hook {@link withPackageStarter} composed for each inner hook. */
const packageStarterHooks = new WeakMap<NodeBehaviorHook, NodeBehaviorHook>();

/**
 * Wrap *inner* so a package template that ships a `source` starter still gets
 * its code injected on a fresh drop.
 *
 * A manifest names its behavior by string key (`"code"`, `"vega"`, a
 * package-shipped key, …). Resolving `"code"` yields the built-in no-op
 * `useCodeNodeBehavior`, which knows nothing about package starters — so
 * every package template declaring `behavior: "code"` alongside a `source`
 * (curio.weather, ai.utk.uhvi, and everything the node factory
 * scaffolds) used to open with an empty editor.
 *
 * The composed hook runs both: *inner* owns the whole behavior surface, and
 * the starter injection only fills in `defaultValueOverride` when *inner*
 * does not provide one of its own. Both hooks are called unconditionally and
 * in a fixed order, so the rules of hooks hold.
 *
 * One *inner* gets one composed hook, the same function on every call. Every
 * registry refresh builds every descriptor again and calls this again, and
 * `UniversalNode` remounts a node's body when its hook changes, so a new
 * function on each call would remount every node of such a template, and lose
 * what it holds, on every refresh.
 */
export function withPackageStarter(inner: NodeBehaviorHook): NodeBehaviorHook {
  const known = packageStarterHooks.get(inner);
  if (known) return known;
  const composed: NodeBehaviorHook = (data, nodeState) => {
    const starter = usePackageNodeBehavior(data, nodeState);
    const base = inner(data, nodeState);
    if (base.defaultValueOverride !== undefined) return base;
    return starter.defaultValueOverride !== undefined
      ? { ...base, defaultValueOverride: starter.defaultValueOverride }
      : base;
  };
  packageStarterHooks.set(inner, composed);
  return composed;
}
