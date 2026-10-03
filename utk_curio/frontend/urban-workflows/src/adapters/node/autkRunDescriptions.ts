// What an Autark run says about itself: feature counts, the one line a data
// or compute node shows after a run, and the words of its pre-run notice.
// Used by the node behavior (autkGrammarBehavior.tsx).

import type { NodeEmptyReason } from '../../utils/nodeEmptyState';
import type { AutkSpecKind } from '../../utils/autkSpecKind';

/**
 * Features in a collection, or `undefined` when it is not one: an uncountable
 * collection is unknown, never a guessed 0 (memo dev/136).
 */
export function featureCount(fc: any): number | undefined {
    return Array.isArray(fc?.features) ? fc.features.length : undefined;
}

/** Whether a collection is known to hold at least one feature. */
export function hasFeatures(fc: any): boolean {
    const count = featureCount(fc);
    return typeof count === 'number' && count > 0;
}

/** The sum of the counts, or `undefined` when any of them is unknown. */
export function totalCount(counts: Array<number | undefined>): number | undefined {
    let total = 0;
    for (const count of counts) {
        if (typeof count !== 'number') return undefined;
        total += count;
    }
    return total;
}

/** ``name (N unit)`` when the count is known, else the bare name. */
export function countedItem(name: string, count: number | undefined, unit: string): string {
    return typeof count === 'number' ? `${name} [${count} ${unit}]` : name;
}

/**
 * The words for a pre-run notice. A data or compute step is "not run", not
 * "not drawn", and says what running it does; an input problem says what it
 * is. Everything else is the shared copy.
 */
export function emptyStateWords(
    reason: NodeEmptyReason | null,
    kind: AutkSpecKind,
    detail?: string,
): { title?: string; hint?: string } {
    if (reason === 'not-run' && kind === 'data') {
        return { title: 'Not run yet', hint: 'This step loads data; run it to pass tables downstream.' };
    }
    if (reason === 'not-run' && kind === 'compute') {
        return { title: 'Not run yet', hint: 'This step computes on upstream layers; run it to pass results downstream.' };
    }
    if (detail && (reason === 'input-type-rejected' || reason === 'geometry-unresolved' || reason === 'geometry-ambiguous')) {
        return { hint: detail };
    }
    return {};
}

/** ``Loaded 3 tables: a, b, c`` - the one line a data/compute node shows after a run. */
export function describeAutkRun(verb: string, noun: string, items: string[]): string {
    if (items.length === 0) return `${verb} nothing - the spec names no ${noun}s.`;
    const plural = noun;
    return `${verb} ${items.length} ${plural}: ${items.join(', ')}`;
}
