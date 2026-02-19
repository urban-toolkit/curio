/**
 * Utilities for MERGE_FLOW box input/source array management.
 *
 * MERGE_FLOW is the only box type that supports multiple 'in' connections.
 * It uses fixed-size arrays for positional input/source slots indexed by handle
 * (e.g. "in_0", "in_1", ...).
 */

const MERGE_FLOW_MIN_SIZE = 6;

/**
 * Initialize and pad merge flow input/source arrays to minimum size.
 * Returns new arrays (does not mutate originals).
 */
export function ensureMergeArrays(
    input: any,
    source: any
): { inputList: any[]; sourceList: any[] } {
    const inputList = Array.isArray(input) ? [...input] : [undefined, undefined];
    const sourceList = Array.isArray(source) ? [...source] : [undefined, undefined];

    while (inputList.length < MERGE_FLOW_MIN_SIZE) inputList.push(undefined);
    while (sourceList.length < MERGE_FLOW_MIN_SIZE) sourceList.push(undefined);

    return { inputList, sourceList };
}

/**
 * Parse a handle string like "in_0", "in_1", etc.
 * Returns the numeric index, or -1 if the handle doesn't match.
 */
export function parseHandleIndex(handle: string | null | undefined): number {
    const match = handle?.match(/^in_(\d)$/);
    return match ? parseInt(match[1], 10) : -1;
}

/**
 * Ensure arrays are large enough for `index`, then set output and source at that slot.
 * Mutates the arrays in place (they should be fresh copies from ensureMergeArrays).
 */
export function setMergeSlot(
    inputList: any[],
    sourceList: any[],
    index: number,
    output: any,
    source: any
): void {
    while (inputList.length <= index) inputList.push(undefined);
    while (sourceList.length <= index) sourceList.push(undefined);
    inputList[index] = output;
    sourceList[index] = source;
}

/**
 * Ensure arrays are large enough for `index`, then clear the slot.
 * Mutates the arrays in place (they should be fresh copies from ensureMergeArrays).
 */
export function clearMergeSlot(
    inputList: any[],
    sourceList: any[],
    index: number
): void {
    while (inputList.length <= index) inputList.push(undefined);
    while (sourceList.length <= index) sourceList.push(undefined);
    inputList[index] = undefined;
    sourceList[index] = undefined;
}
