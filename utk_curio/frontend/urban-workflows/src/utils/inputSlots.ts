/**
 * A node's input circles (#662): which circle an edge feeds, what each circle
 * holds, and the one value the node's code reads.
 *
 * A template with one input port that takes more than one edge grows its
 * circles: each edge lands on the free circle at the bottom, and a new free
 * circle appears below it, up to the port's maximum. Circle 0 is the handle
 * `in`, circle k is `in_k`. Deleting an edge closes the gap: the circles below
 * move up one.
 *
 * Duck-typed edges, so this module needs no `reactflow` import.
 */

type SlotEdge = {
    id?: string | null;
    source?: string | null;
    target?: string | null;
    sourceHandle?: string | null;
    targetHandle?: string | null;
};

const SLOT_ARRAY_MIN_SIZE = 6;

/**
 * Initialize and pad input/source slot arrays to a minimum size.
 * Returns new arrays (does not mutate originals).
 */
export function ensureSlotArrays(
    input: any,
    source: any
): { inputList: any[]; sourceList: any[] } {
    const inputList = Array.isArray(input) ? [...input] : [undefined, undefined];
    const sourceList = Array.isArray(source) ? [...source] : [undefined, undefined];

    while (inputList.length < SLOT_ARRAY_MIN_SIZE) inputList.push(undefined);
    while (sourceList.length < SLOT_ARRAY_MIN_SIZE) sourceList.push(undefined);

    return { inputList, sourceList };
}

/**
 * The circle a target handle names: `in` (or none) is circle 0, `in_N` is
 * circle N. Any other handle (`in_points`, `in/out`) is -1.
 */
export function inputSlotOf(handle: string | null | undefined): number {
    if (handle == null || handle === "in") return 0;
    const match = handle.match(/^in_(\d+)$/);
    return match ? parseInt(match[1], 10) : -1;
}

/** The handle id of circle *slot*. */
export function slotHandleId(slot: number): string {
    return slot === 0 ? "in" : `in_${slot}`;
}

/** Whether an edge carries data rather than an interaction. */
export function isDataEdge(edge: SlotEdge): boolean {
    return !(edge.sourceHandle === "in/out" && edge.targetHandle === "in/out");
}

/** True when a slot holds a propagated upstream artifact. */
export function isFilledSlot(value: unknown): boolean {
    return value !== undefined && value !== null && value !== '';
}

/**
 * The circles of *nodeId* that have an edge, sorted ascending.
 */
export function wiredInputSlots(edges: SlotEdge[], nodeId: string): number[] {
    const slots = new Set<number>();
    for (const e of edges) {
        if (e.target !== nodeId || !isDataEdge(e)) continue;
        const i = inputSlotOf(e.targetHandle);
        if (i >= 0) slots.add(i);
    }
    return Array.from(slots).sort((a, b) => a - b);
}

/**
 * Every slot of *nodeId* that *sourceNodeId* feeds, by prior assignment
 * (`sourceList`) and by current wiring (edge target handles). A single source
 * can feed more than one slot of the same node.
 */
export function slotsFedBy(
    edges: SlotEdge[],
    nodeId: string,
    sourceNodeId: string,
    sourceList: unknown[],
): number[] {
    const slots = new Set<number>();
    sourceList.forEach((s, i) => {
        if (s === sourceNodeId) slots.add(i);
    });
    for (const edge of edges) {
        if (edge.target !== nodeId || edge.source !== sourceNodeId || !isDataEdge(edge)) continue;
        const i = inputSlotOf(edge.targetHandle);
        if (i >= 0) slots.add(i);
    }
    return Array.from(slots).sort((a, b) => a - b);
}

/**
 * Ensure arrays are large enough for `index`, then set output and source at that slot.
 * Mutates the arrays in place (they should be fresh copies from ensureSlotArrays).
 */
export function setSlot(
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
 * How many edges a template's input side takes: one port's declared upper
 * bound (`Infinity` for `n`), or one per port when there are several. The
 * twin of `input_capacity` in `packages/application/templates.py`.
 */
export function inputCapacity(ports: ReadonlyArray<{ cardinality?: string }> | undefined): number {
    if (!ports || ports.length !== 1) return ports?.length ?? 0;
    const text = (ports[0].cardinality ?? "1").trim();
    if (text === "n") return Infinity;
    if (/^\d+$/.test(text)) return parseInt(text, 10);
    const range = text.match(/^\[\s*\d+\s*,\s*(\d+|n)\s*\]$/);
    if (range) return range[1] === "n" ? Infinity : parseInt(range[1], 10);
    return Infinity;
}

/** Whether a template with these input ports grows a circle per edge. */
export function growsInputCircles(ports: ReadonlyArray<{ cardinality?: string }> | undefined): boolean {
    return ports?.length === 1 && inputCapacity(ports) > 1;
}

/**
 * How many circles a growing node shows: one past its last wired circle, so
 * there is always a free one, up to *max*.
 */
export function inputCircleCount(wired: number[], max: number): number {
    const next = wired.length > 0 ? wired[wired.length - 1] + 2 : 1;
    return Math.max(1, Math.min(next, max));
}

/**
 * The one value a growing node's code reads, from its slots: a single wired
 * input's value; several as an `outputs` bundle in circle order, the shape the
 * sandbox and the runner already take. Empty until every wired circle holds a
 * value, so a node never runs on part of its inputs.
 */
export function nodeInputFromSlots(inputSlots: unknown, wired: number[]): unknown {
    if (wired.length === 0) return "";
    const list = Array.isArray(inputSlots) ? inputSlots : [];
    const values = wired.map((s) => list[s]);
    if (!values.every(isFilledSlot)) return "";
    if (values.length === 1) return values[0];
    return { dataType: "outputs", data: values };
}

/** The wired circles that hold no value yet. */
export function emptyWiredSlots(inputSlots: unknown, wired: number[]): number[] {
    const list = Array.isArray(inputSlots) ? inputSlots : [];
    return wired.filter((s) => !isFilledSlot(list[s]));
}

/**
 * The new target handle of every edge into *nodeId* below circle
 * *removedSlot*, which lost its edge: each moves up one circle. Keyed by edge
 * id; edges that do not move are left out.
 */
export function compactedHandles(edges: SlotEdge[], nodeId: string, removedSlot: number): Map<string, string> {
    const moved = new Map<string, string>();
    for (const e of edges) {
        if (e.target !== nodeId || !isDataEdge(e) || e.id == null) continue;
        const slot = inputSlotOf(e.targetHandle);
        if (slot > removedSlot) moved.set(e.id, slotHandleId(slot - 1));
    }
    return moved;
}

/** *list* with entry *removedSlot* taken out, the later ones moved up one. */
export function withoutSlot<T>(list: unknown, removedSlot: number): T[] {
    const copy = Array.isArray(list) ? [...list] : [];
    if (removedSlot < copy.length) copy.splice(removedSlot, 1);
    return copy;
}
