/**
 * The starter a freshly dropped node of a package template opens with: its
 * manifest's `source` file, or, for a model package's template without one,
 * the default cell the backend writes for its model's type
 * (`utk_curio/backend/app/packages/application/starters.py`).
 *
 * `adapters/node/packageNodeBehavior` injects it, and a grammar node's own
 * starter ladder (`hook/useStarterSpec`) never fills a node that opens with
 * one, so a template wired before its starter arrives still opens with it.
 * Pure, with no React and no provider.
 */
import { tryGetNodeDescriptor } from './nodeRegistry';
import type { NodeDescriptor } from './types';

/**
 * The name the starters feed lists a `source` file under: its file name
 * without the final extension, `_` read as a space (`Path.stem` in the
 * backend's walker).
 */
function sourceDisplayName(sourcePath: string | undefined): string | undefined {
  if (!sourcePath) return undefined;
  const basename = sourcePath.split('/').pop() ?? '';
  if (!basename) return undefined;
  const stem = basename.replace(/\.[^.]+$/u, '');
  return stem.replace(/_/g, ' ');
}

/**
 * The name of the starter a freshly dropped node of *descriptor* opens with:
 * its manifest's `source` file's, or, for a model package's template without
 * one, the default cell's, named for its template id.
 */
export function packageStarterName(descriptor: NodeDescriptor): string | undefined {
  return sourceDisplayName(descriptor.package?.source) ?? descriptor.package?.defaultCellStarter;
}

/** Whether a freshly dropped node of *nodeType* opens with a starter its package ships. */
export function opensWithPackageStarter(nodeType: string | undefined): boolean {
  const descriptor = nodeType ? tryGetNodeDescriptor(nodeType) : undefined;
  return descriptor?.source === 'package' && packageStarterName(descriptor) !== undefined;
}
