/**
 * Who else is in the dataflow's room now (`people.ts`), for the canvas's dock:
 * the list changes only when what the dock draws of someone does, so a pointer
 * that moves draws nothing again. Where someone points is read when it is
 * asked for. Empty while the canvas is bound to no doc.
 *
 * The list is read from the doc's awareness as a store, at each change of a
 * state, and drawn in the task of that change, as the nodes agents write are
 * (`agentHolds`). Left to React's next render, an agent's state naming the
 * node it writes and its state naming none a second later could both be
 * handled before React rendered again on a busy page, and the dock never said
 * what the agent was editing.
 */
import { useCallback, useMemo, useRef, useSyncExternalStore } from "react";

import { useCollab } from "../CollaborationProvider";
import { useDocBinding } from "./docContext";
import { peopleOf, pointerOfPerson, samePeople, type OwnParticipant, type Person } from "./people";
import type { CanvasPointer } from "./presence";

const NONE: Person[] = [];

export interface PeopleHere {
    people: Person[];
    /** Where *person* points on the canvas now, or null. */
    pointerOf: (person: Person) => CanvasPointer | null;
}

export function usePeopleHere(): PeopleHere {
    const binding = useDocBinding();
    const awareness = binding?.provider.awareness ?? null;
    const { participantId, users } = useCollab();
    const userId = useMemo(
        () => users.find((user) => user.participant_id === participantId)?.user_id ?? null,
        [users, participantId],
    );
    const roles = useMemo(
        () => new Map(users.filter((user) => user.participant_id).map((user) => [user.participant_id!, user.role])),
        [users],
    );
    const own: OwnParticipant = useMemo(() => ({ participantId, userId }), [participantId, userId]);
    // The list last read, kept while what the dock draws of everyone is the same.
    const shown = useRef<Person[]>(NONE);
    const subscribe = useCallback(
        (changed: () => void) => {
            if (!awareness) return () => undefined;
            awareness.on("change", changed);
            return () => awareness.off("change", changed);
        },
        [awareness],
    );
    const read = useCallback(() => {
        const next = awareness ? peopleOf(awareness, own, roles) : NONE;
        if (!samePeople(shown.current, next)) shown.current = next.length ? next : NONE;
        return shown.current;
    }, [awareness, own, roles]);
    const people = useSyncExternalStore(subscribe, read, read);

    const pointerOf = useCallback((person: Person) => pointerOfPerson(awareness, own, person), [awareness, own]);
    return { people, pointerOf };
}
