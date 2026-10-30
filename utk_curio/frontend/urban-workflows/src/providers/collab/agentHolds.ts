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

/** What the doc's awareness says agents are writing: *awareness*'s states,
 *  or none without it. */
export function holdAgentsOf(awareness: { getStates(): Map<number, unknown> } | null | undefined): void {
    const next = new Map<string, AgentHold>();
    awareness?.getStates().forEach((state) => {
        const writing = agentWriting(state);
        if (writing) for (const nodeId of writing.nodeIds) next.set(nodeId, writing.hold);
    });
    publish(settle(next));
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
        const read = () => holdAgentsOf(awareness);
        read();
        awareness.on("change", read);
        return () => {
            awareness.off("change", read);
            holdAgentsOf(null);
        };
    }, [awareness]);
}
