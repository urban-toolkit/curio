/**
 * Where two texts differ, so a change rewrites only that stretch: a node's
 * code in the dataflow's doc (`providers/collab/docMapping.ts`), and in its
 * editor (`hook/useMonacoExternalValue.ts`), keep typing made elsewhere in it.
 */

function isHighSurrogate(code: number): boolean {
    return code >= 0xd800 && code <= 0xdbff;
}

function isLowSurrogate(code: number): boolean {
    return code >= 0xdc00 && code <= 0xdfff;
}

/** Where *old* and *next* differ: past what they share at their start
 *  (`start`) and before what they share at their end (`endOld` in *old*,
 *  `endNew` in *next*), in UTF-16 places, never inside a surrogate pair. */
export function changedStretch(old: string, next: string): { start: number; endOld: number; endNew: number } {
    const limit = Math.min(old.length, next.length);
    let start = 0;
    while (start < limit && old.charCodeAt(start) === next.charCodeAt(start)) start += 1;
    if (start > 0 && isHighSurrogate(old.charCodeAt(start - 1))) start -= 1;
    let endOld = old.length;
    let endNew = next.length;
    while (endOld > start && endNew > start && old.charCodeAt(endOld - 1) === next.charCodeAt(endNew - 1)) {
        endOld -= 1;
        endNew -= 1;
    }
    // The shared end starts on the second half of a pair whose first half
    // changed: the pair goes whole, out and back in.
    if (endOld < old.length && isLowSurrogate(old.charCodeAt(endOld))) {
        endOld += 1;
        endNew += 1;
    }
    return { start, endOld, endNew };
}
