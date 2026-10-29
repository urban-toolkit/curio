/**
 * Who else is in the dataflow's room, read from the doc's awareness
 * (`presence.ts`): one entry for each other participant the server named, the
 * people the canvas's dock shows. Any peer with a state the server named is
 * one, whatever joined as it.
 *
 * You are not among them, in this tab or another of your account's. A
 * participant whose doc started again leaves an older state behind for a
 * while, so each participant is its freshest state.
 *
 * Each state's `user` is the server's (`dataflow_docs._user`). `editing` is the
 * node whose code the participant edits, and `pointer` where they point on the
 * canvas, as `cursors.ts` sends and reads it: a field the server keeps in a
 * watcher's state too (`PRESENCE_FIELDS`).
 */
import type { Awareness } from "y-protocols/awareness";

import { pointerOf } from "./cursors";
import { nameOf, personColor, type CanvasPointer, type PresenceState } from "./presence";

export interface Person {
    /** One per participant: its id, else its awareness client's. */
    key: string;
    clientId: number;
    participantId: string | null;
    userId: number | null;
    name: string;
    initials: string;
    /** Their color, from their account: their cursor's on the canvas and in
     *  the code editors. */
    color: string;
    /** Owner, editor or watcher; the room's list is newer than a state's. */
    role: string | null;
    /** The node whose code they edit. */
    editing: string | null;
}

/** Who this tab is in the room. */
export interface OwnParticipant {
    participantId: string | null;
    userId: number | null;
}

/** The first letters of a name's first and last words, or of its one word. */
export function initialsOf(name: string): string {
    const words = name.trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) return "?";
    const first = Array.from(words[0])[0] ?? "";
    const last = words.length > 1 ? Array.from(words[words.length - 1])[0] ?? "" : "";
    return (first + last).toUpperCase();
}

type Named = { clientId: number; state: PresenceState; key: string; at: number };

/** Each other participant's freshest state, by participant. */
function freshest(awareness: Awareness, own: OwnParticipant): Map<string, Named> {
    const out = new Map<string, Named>();
    awareness.getStates().forEach((raw, clientId) => {
        const state = raw as PresenceState | undefined;
        const user = state?.user;
        if (clientId === awareness.clientID || !user || typeof user !== "object") return;
        const participantId = typeof user.participant_id === "string" ? user.participant_id : null;
        if (participantId && participantId === own.participantId) return;
        if (own.userId != null && user.user_id === own.userId) return;
        const key = participantId ?? `client:${clientId}`;
        const at = awareness.meta.get(clientId)?.lastUpdated ?? 0;
        const prior = out.get(key);
        if (!prior || at >= prior.at) out.set(key, { clientId, state: state!, key, at });
    });
    return out;
}

/** Everyone else in the room, by name. *roles* is the room's list, by
 *  participant id, which a change to the editors reaches first. */
export function peopleOf(
    awareness: Awareness | null | undefined,
    own: OwnParticipant,
    roles?: ReadonlyMap<string, string | null | undefined>,
): Person[] {
    if (!awareness) return [];
    const people: Person[] = [];
    freshest(awareness, own).forEach(({ clientId, state, key }) => {
        const user = state.user!;
        const participantId = typeof user.participant_id === "string" ? user.participant_id : null;
        const name = nameOf(state);
        people.push({
            key,
            clientId,
            participantId,
            userId: typeof user.user_id === "number" ? user.user_id : null,
            name,
            initials: initialsOf(name),
            color: personColor(user, String(clientId)),
            role: (participantId ? roles?.get(participantId) : null) ?? user.role ?? null,
            editing: typeof state.editing === "string" ? state.editing : null,
        });
    });
    return people.sort((a, b) => a.name.localeCompare(b.name) || a.key.localeCompare(b.key));
}

/** Where *person* points on the canvas now, from their freshest state, or
 *  null when they point nowhere on it. */
export function pointerOfPerson(
    awareness: Awareness | null | undefined,
    own: OwnParticipant,
    person: Pick<Person, "key">,
): CanvasPointer | null {
    if (!awareness) return null;
    const named = freshest(awareness, own).get(person.key);
    return named ? pointerOf(named.state) : null;
}

/** Whether two lists show the same: what the dock draws of each person. */
export function samePeople(a: ReadonlyArray<Person>, b: ReadonlyArray<Person>): boolean {
    if (a.length !== b.length) return false;
    return a.every((person, i) => {
        const other = b[i];
        return person.key === other.key && person.clientId === other.clientId && person.name === other.name
            && person.color === other.color && person.role === other.role && person.editing === other.editing;
    });
}
