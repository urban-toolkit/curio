/**
 * What a node is, read off its registered descriptor: the behavior its
 * template declares (its manifest's `behavior`), and its category and input
 * ports. A package template that declares a built-in's behavior is that
 * built-in node to every rule that asks here, and a template only named like
 * a built-in is not. A type no descriptor is registered for, or whose template
 * declares no behavior (no category, for `loadsData`), is a built-in node by
 * its id, the fallback each rule names.
 *
 * The backend reads the same declarations off the package manifests
 * (`declares_behavior` in `projects/template_grammars.py`, `loads_data` in
 * `datasets/application/export.py`), and `declaredNodes.cases.json` beside
 * this module holds the cases both sides run.
 *
 * Pure, with no React and no provider.
 */
import { NodeType } from '../constants';
import { tryGetNodeDescriptor } from './nodeRegistry';

/** The name a dataflow saved before node packages gives the Data Loading node. */
const LEGACY_DATA_LOADING = 'DATA_LOADING';

/** A trailing `@<major>`, as the backend's `unversioned_node_type` strips it. */
const MAJOR_SUFFIX = /@(?:0|[1-9][0-9]{0,3})$/;

/** *nodeType* without its `@<major>`. */
function withoutMajor(nodeType: string): string {
  return nodeType.replace(MAJOR_SUFFIX, '');
}

/** The behavior the registered template of *nodeType* declares, or undefined. */
export function declaredBehavior(nodeType: string | null | undefined): string | undefined {
  if (!nodeType) return undefined;
  const behavior = tryGetNodeDescriptor(nodeType)?.behavior;
  return typeof behavior === 'string' && behavior ? behavior : undefined;
}

/**
 * Whether a node of *nodeType* behaves as one of *behaviors*: the behavior its
 * template declares decides. A type whose template declares none, or that no
 * descriptor is registered for, is one of the built-in nodes *builtinTypes*
 * names (unversioned ids) or none.
 */
export function declaresBehavior(
  nodeType: string | null | undefined,
  behaviors: ReadonlySet<string>,
  builtinTypes: ReadonlySet<string>,
): boolean {
  if (!nodeType) return false;
  const behavior = declaredBehavior(nodeType);
  if (behavior !== undefined) return behaviors.has(behavior);
  return builtinTypes.has(withoutMajor(nodeType));
}

/**
 * Whether a node of *nodeType* brings data into its dataflow, as the Data
 * Loading node does: its template declares the `data` category and no input
 * port. A type whose template declares no category, or that no descriptor is
 * registered for, loads data when it is the built-in Data Loading node, by
 * its id or its name before node packages.
 */
export function loadsData(nodeType: string | null | undefined): boolean {
  if (!nodeType) return false;
  if (nodeType === LEGACY_DATA_LOADING) return true;
  const descriptor = tryGetNodeDescriptor(nodeType);
  if (descriptor?.category) {
    return descriptor.category === 'data' && (descriptor.inputPorts ?? []).length === 0;
  }
  return withoutMajor(nodeType) === NodeType.DATA_LOADING;
}
