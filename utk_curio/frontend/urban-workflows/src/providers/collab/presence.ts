/**
 * What each tab tells the others through the doc's awareness, which writes
 * nothing into the doc and is gone when the tab leaves:
 *
 * - `editing`: the node whose editor has the focus, which asks before anyone
 *   removes it;
 * - `selection`: the cursor in that editor (y-monaco's), drawn in the others'
 *   editors in this tab's color;
 * - `drag`: the places of the nodes this tab is dragging, which the others
 *   show live; the place itself is written into the doc at the drop;
 * - `removed`: the nodes this tab just removed, so a tab that was editing one
 *   says who removed it;
 * - `pointer`: where this tab's pointer is on the canvas, in flow coordinates,
 *   or null while it is off the canvas (`cursors.ts`); the others draw it as a
 *   cursor in this tab's color with its name.
 *
 * The server writes each state's `user`: the participant the room knows. A
 * watcher's state keeps only `pointer` and `selection`.
 */
import type { Awareness } from "y-protocols/awareness";

export interface PresenceUser {
    participant_id?: string | null;
    user_id?: number | null;
    username?: string | null;
    name?: string | null;
    role?: string | null;
}

export interface DragState {
    nodes: Record<string, { x: number; y: number }>;
}

/** A pointer on the canvas: the point of the dataflow it is on, in React
 *  Flow's flow coordinates (the same in every tab, whatever each has panned
 *  or zoomed to), and when it was sent, in milliseconds since the epoch. */
export interface CanvasPointer {
    x: number;
    y: number;
    t: number;
}

export interface PresenceState {
    user?: PresenceUser;
    editing?: string | null;
    drag?: DragState | null;
    removed?: { nodes: string[]; at: number } | null;
    selection?: unknown;
    pointer?: CanvasPointer | null;
}

/** How long a removal note stays in this tab's state. */
export const REMOVAL_NOTE_MS = 5000;

/** The states of everyone else, by their client id. */
export function othersOf(awareness: Awareness | null | undefined): Array<[number, PresenceState]> {
    if (!awareness) return [];
    const own = awareness.clientID;
    const out: Array<[number, PresenceState]> = [];
    awareness.getStates().forEach((state, clientId) => {
        if (clientId !== own && state) out.push([clientId, state as PresenceState]);
    });
    return out;
}

/** The name a state's participant goes by. */
export function nameOf(state: PresenceState | null | undefined): string {
    const user = state?.user;
    return (user?.name || user?.username || "Someone").toString();
}

/** The names of everyone else editing *nodeId*'s code. */
export function editorsOf(awareness: Awareness | null | undefined, nodeId: string): string[] {
    return othersOf(awareness)
        .filter(([, state]) => state.editing === nodeId)
        .map(([, state]) => nameOf(state));
}

export function setEditing(awareness: Awareness | null | undefined, nodeId: string | null): void {
    if (!awareness) return;
    const current = (awareness.getLocalState() as PresenceState | null)?.editing ?? null;
    if (current === nodeId) return;
    awareness.setLocalStateField("editing", nodeId);
}

export function setDrag(awareness: Awareness | null | undefined, drag: DragState | null): void {
    if (!awareness) return;
    awareness.setLocalStateField("drag", drag);
}

/** Where everyone else is dragging nodes now, by node id. */
export function remoteDrags(awareness: Awareness | null | undefined): Map<string, { x: number; y: number }> {
    const out = new Map<string, { x: number; y: number }>();
    for (const [, state] of othersOf(awareness)) {
        const nodes = state.drag?.nodes;
        if (!nodes || typeof nodes !== "object") continue;
        for (const [id, place] of Object.entries(nodes)) {
            if (place && typeof place.x === "number" && typeof place.y === "number") out.set(id, place);
        }
    }
    return out;
}

const removalTimers = new WeakMap<Awareness, ReturnType<typeof setTimeout>>();

/** Tell the others this tab removes *nodeIds* now. */
export function noteRemoval(awareness: Awareness | null | undefined, nodeIds: string[]): void {
    if (!awareness || nodeIds.length === 0) return;
    awareness.setLocalStateField("removed", { nodes: nodeIds, at: Date.now() });
    const prior = removalTimers.get(awareness);
    if (prior) clearTimeout(prior);
    removalTimers.set(awareness, setTimeout(() => {
        removalTimers.delete(awareness);
        if (awareness.getLocalState()) awareness.setLocalStateField("removed", null);
    }, REMOVAL_NOTE_MS));
}

/** The name of whoever else just removed *nodeId*, if a note says so. */
export function removerOf(awareness: Awareness | null | undefined, nodeId: string): string | null {
    for (const [, state] of othersOf(awareness)) {
        if (Array.isArray(state.removed?.nodes) && state.removed!.nodes.includes(nodeId)) return nameOf(state);
    }
    return null;
}

/** Colors a participant's cursor takes, each legible on white. */
export const PARTICIPANT_COLORS = [
    "#d6336c", "#2b8a3e", "#1c7ed6", "#e8590c", "#7048e8",
    "#0c8599", "#c2255c", "#5c940d", "#364fc7", "#a61e4d",
];

/** The color of the participant *id*: the same in every tab. */
export function participantColor(id: string | null | undefined): string {
    const key = id || "";
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
    return PARTICIPANT_COLORS[hash % PARTICIPANT_COLORS.length];
}

/** The color of whoever holds the awareness state *state*, client *clientId*:
 *  their cursor's in the code editors and on the canvas. */
export function colorOf(clientId: number, state: PresenceState | null | undefined): string {
    return participantColor(state?.user?.participant_id ?? String(clientId));
}

function cssString(text: string): string {
    return `"${text.replace(/[\\"]/g, (c) => `\\${c}`).replace(/[\n\r\f]/g, " ")}"`;
}

/**
 * The style that colors everyone else's cursor and selection in a code
 * editor, in their color, with their name over the cursor: y-monaco marks
 * them with `yRemoteSelection-<client id>` and `yRemoteSelectionHead-<client
 * id>`.
 */
export function remoteCursorStyle(awareness: Awareness | null | undefined): string {
    const rules: string[] = [];
    for (const [clientId, state] of othersOf(awareness)) {
        const color = colorOf(clientId, state);
        rules.push(
            `.yRemoteSelection-${clientId} { background-color: ${color}33; }`,
            `.yRemoteSelectionHead-${clientId} { position: absolute; border-left: 2px solid ${color}; `
            + "height: 100%; box-sizing: border-box; }",
            `.yRemoteSelectionHead-${clientId}::after { position: absolute; top: -1.3em; left: -2px; `
            + `padding: 0 4px; border-radius: 3px 3px 3px 0; background: ${color}; color: #fff; `
            + `font-size: 10px; line-height: 1.3em; white-space: nowrap; pointer-events: none; `
            + `content: ${cssString(nameOf(state))}; }`,
        );
    }
    return rules.join("\n");
}
