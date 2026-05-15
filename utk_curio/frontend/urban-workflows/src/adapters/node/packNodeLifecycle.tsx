/**
 * Lifecycle hook for pack-registered code nodes.
 *
 * Built-in code nodes use the no-op `useCodeNodeLifecycle`: the user is
 * expected to pick a preset from the Templates dropdown before running.
 *
 * Pack nodes ship a `defaultTemplate` field in the manifest (see
 * ``docs/nodesfactory@docs/manifest_spec.md`` (editor / template fields) and
 * ``docs/nodesfactory@docs/backend.md``. Reference fixture:
 * ``utk_curio/backend/fixtures/packs/ai.urbanlab.uhvi@1/manifest.json``).
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
import { useTemplateContext } from '../../providers/TemplateProvider';
import { tryGetNodeDescriptor } from '../../registry/nodeRegistry';
import type { NodeLifecycleHook } from '../../registry/types';

function defaultTemplateName(defaultTemplatePath: string | undefined): string | undefined {
  if (!defaultTemplatePath) return undefined;
  const basename = defaultTemplatePath.split('/').pop() ?? '';
  if (!basename) return undefined;
  const stem = basename.replace(/\.py$/i, '').replace(/\.js$/i, '');
  // The backend template loader maps `<Name_With_Underscores>.py` → name
  // `"Name With Underscores"` (see `_template_object` in
  // `utk_curio/backend/app/packs/templates.py`). Mirror that here.
  return stem.replace(/_/g, ' ');
}

export const usePackNodeLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const { getTemplates } = useTemplateContext();
  const descriptor = tryGetNodeDescriptor(data.nodeType);

  // `data.code` is a runtime mutation that `useNodeState` performs (see
  // `hook/useNodeState.ts` → `useEffect(() => { data.code = code; ... })`).
  // It is not part of the typed `NodeLifecycleData` surface, so we read it
  // through a narrow cast — we only care whether it was *defined* at mount.
  const initialCodeRef = useRef<unknown>((data as { code?: unknown }).code);
  const hasInjectedRef = useRef(false);
  const [override, setOverride] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (hasInjectedRef.current) return;

    // Reload / remount / copy-paste — never inject after instantiation.
    if (initialCodeRef.current !== undefined) {
      hasInjectedRef.current = true;
      return;
    }

    // Built-ins and pack-less descriptors are out of scope for this hook.
    if (!descriptor || descriptor.source !== 'pack') {
      hasInjectedRef.current = true;
      return;
    }

    const wantedName = defaultTemplateName(descriptor.pack?.defaultTemplate);
    if (!wantedName) {
      hasInjectedRef.current = true;
      return;
    }

    // If the user typed something before templates loaded, respect it.
    if (nodeState.code && nodeState.code.length > 0) {
      hasInjectedRef.current = true;
      return;
    }

    const templates = getTemplates(data.nodeType, false);
    const hit = templates.find((t) => t.name === wantedName);
    if (hit?.code) {
      hasInjectedRef.current = true;
      setOverride(hit.code);
    }
    // else: templates not loaded yet — wait for the next effect run.
  }, [descriptor, data.nodeType, getTemplates, nodeState.code]);

  // After CodeEditor consumes the override (its `defaultValueBypass`
  // effect copies the value into the Monaco buffer + nodeState), drop
  // the override so the user can clear the editor or switch templates
  // without it snapping back.
  useEffect(() => {
    if (override !== undefined) setOverride(undefined);
  }, [override]);

  return override !== undefined ? { defaultValueOverride: override } : {};
};
