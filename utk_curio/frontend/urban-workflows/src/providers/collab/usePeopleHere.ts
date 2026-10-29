/**
 * Who else is in the dataflow's room now (`people.ts`), for the canvas's dock:
 * the list changes only when what the dock draws of someone does, so a pointer
 * that moves draws nothing again. Where someone points is read when it is
 * asked for. Empty while the canvas is bound to no doc.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { useCollab } from "../CollaborationProvider";
import { useDocBinding } from "./docContext";
import { peopleOf, pointerOfPerson, samePeople, type CanvasPoint, type OwnParticipant, type Person } from "./people";

const NONE: Person[] = [];

export interface PeopleHere {
    people: Person[];
    /** Where *person* points on the canvas now, or null. */
    pointerOf: (person: Person) => CanvasPoint | null;
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
    const [people, setPeople] = useState<Person[]>(NONE);

    useEffect(() => {
        if (!awareness) {
            setPeople(NONE);
            return;
        }
        const read = () => {
            const next = peopleOf(awareness, own, roles);
            setPeople((prev) => (samePeople(prev, next) ? prev : next.length ? next : NONE));
        };
        read();
        awareness.on("change", read);
        return () => awareness.off("change", read);
    }, [awareness, own, roles]);

    const pointerOf = useCallback((person: Person) => pointerOfPerson(awareness, own, person), [awareness, own]);
    return { people, pointerOf };
}
