/**
 * The nodes agents are writing now, by node id, for whatever shows a node to
 * read: the tab its editor shows while an agent writes it (`NodeEditor`), and
 * the lines its code editor marks as the agent's change lands
 * (`useYMonacoBinding`).
 *
 * An agent at work is a peer of the dataflow's doc, with an awareness state of
 * its own: its `user` names it (`agent`, as its lock does), `editing` is the
 * node it is writing, from just before the write to a second after, or the
 * nodes one action writes at once, and `writes` what it writes there (`code`,
 * `spec`, `widgets` or `settings`), in each of them. That holds whether the
 * agent holds the node's lock or writes under its asker's, whose lock a node
 * keeps while they hold it.
 *
 * `CollaborationProvider` keeps it in step with the doc's awareness
 * (`useAgentsWriting`): read again at each change of a state, in the same
 * task, so a change the agent writes right after its state finds its node
 * held when it lands.
 *
 * A canvas no doc binds (a hosted guest's example) has no awareness to read:
 * there, each `change` event of a run says what the agent's state said as it
 * wrote (`writing`), and the node is held from just before the change lands
 * until `AGENT_CHANGE_HOLD_MS` after (`holdAgentsOfChange`), as the room's
 * tabs see it. While a doc's awareness feeds the store, it alone says what
 * agents write.
 */
import { useEffect, useSyncExternalStore } from "react";

import { agentHolding, type AgentHold } from "./participants";
import { editingOf } from "./presence";

let held: ReadonlyMap<string, AgentHold> = new Map();
const listeners = new Set<() => void>();

function sameHold(a: AgentHold, b: AgentHold): boolean {
    return a.participantId === b.participantId && a.attachmentId === b.attachmentId && a.name === b.name
        && a.category === b.category && a.askedBy === b.askedBy && a.writes === b.writes;
}

/** *next*, keeping each hold that did not change as it was, so a node whose
 *  hold stays reads the same one and draws nothing again. */
function settle(next: Map<string, AgentHold>): ReadonlyMap<string, AgentHold> {
    next.forEach((hold, nodeId) => {
        const was = held.get(nodeId);
        if (was && sameHold(was, hold)) next.set(nodeId, was);
    });
    return next;
}

function publish(next: ReadonlyMap<string, AgentHold>): void {
    const changed = next.size !== held.size || Array.from(next).some(([nodeId, hold]) => held.get(nodeId) !== hold);
    if (!changed) return;
    held = next;
    listeners.forEach((listener) => listener());
}

/** The agent writing *nodeId* now, or null. */
export function agentHoldOf(nodeId: string | null | undefined): AgentHold | null {
    return (nodeId ? held.get(nodeId) : undefined) ?? null;
}

export function subscribeAgentHolds(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** The agent writing *nodeId*, read again whenever that changes. */
export function useAgentHold(nodeId: string | null | undefined): AgentHold | null {
    return useSyncExternalStore(subscribeAgentHolds, () => agentHoldOf(nodeId), () => null);
}

/** The nodes an agent peer's awareness *state* says it is writing, one id or
 *  a list of them, and the agent; null for anyone else's state, or an agent
 *  writing nothing. */
export function agentWriting(state: unknown): { nodeIds: string[]; hold: AgentHold } | null {
    if (!state || typeof state !== "object") return null;
    const { user, writes } = state as { user?: unknown; writes?: unknown };
    const nodeIds = editingOf(state);
    if (nodeIds.length === 0 || !user || typeof user !== "object") return null;
    const hold = agentHolding({ ...(user as Record<string, unknown>), writes });
    return hold ? { nodeIds, hold } : null;
}

/** How long a run's `change` event holds the node it names, after it lands:
 *  the second the server keeps a node after an agent's write
 *  (`agent_peers.KEEP_AFTER_WRITE_S`). */
export const AGENT_CHANGE_HOLD_MS = 1000;

/** What the doc's awareness says agents are writing. */
let fromAwareness: ReadonlyMap<string, AgentHold> = new Map();
/** What runs' `change` events say agents just wrote, each until its moment
 *  ends, on a canvas no doc binds. */
const fromChanges = new Map<string, { hold: AgentHold; timer: ReturnType<typeof setTimeout> }>();
/** How many docs' awarenesses feed the store now. */
let awarenessFeeds = 0;

function republish(): void {
    const next = new Map(fromAwareness);
    fromChanges.forEach(({ hold }, nodeId) => {
        if (!next.has(nodeId)) next.set(nodeId, hold);
    });
    publish(settle(next));
}

/** What the doc's awareness says agents are writing: *awareness*'s states,
 *  or none without it. */
export function holdAgentsOf(awareness: { getStates(): Map<number, unknown> } | null | undefined): void {
    const next = new Map<string, AgentHold>();
    awareness?.getStates().forEach((state) => {
        const writing = agentWriting(state);
        if (writing) for (const nodeId of writing.nodeIds) next.set(nodeId, writing.hold);
    });
    fromAwareness = next;
    republish();
}

/**
 * What a run's `change` event says the agent wrote (*writing*: its `user`,
 * `editing` and `writes`, as its state in the room said them while it
 * wrote), on a canvas no doc binds: each node it names is held now, before
 * the change lands, until *ms* after. A canvas a doc's awareness feeds takes
 * nothing from it, since the awareness said it already, while the agent
 * wrote. Whether it held anything.
 */
export function holdAgentsOfChange(writing: unknown, ms: number = AGENT_CHANGE_HOLD_MS): boolean {
    if (awarenessFeeds > 0) return false;
    const found = agentWriting(writing);
    if (!found) return false;
    for (const nodeId of found.nodeIds) {
        const was = fromChanges.get(nodeId);
        if (was) clearTimeout(was.timer);
        const timer = setTimeout(() => {
            if (fromChanges.get(nodeId)?.timer !== timer) return;
            fromChanges.delete(nodeId);
            republish();
        }, ms);
        fromChanges.set(nodeId, { hold: found.hold, timer });
    }
    republish();
    return true;
}

/** Keep what agents are writing in step with *awareness*: at once, and at
 *  each change of a state; nothing once it goes. */
export function useAgentsWriting(awareness: {
    getStates(): Map<number, unknown>;
    on(event: "change", listener: () => void): void;
    off(event: "change", listener: () => void): void;
} | null | undefined): void {
    useEffect(() => {
        if (!awareness) return undefined;
        awarenessFeeds += 1;
        const read = () => holdAgentsOf(awareness);
        read();
        awareness.on("change", read);
        return () => {
            awarenessFeeds -= 1;
            awareness.off("change", read);
            holdAgentsOf(null);
        };
    }, [awareness]);
}
