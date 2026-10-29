import React, { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useReactFlow, useStore } from "reactflow";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faListUl } from "@fortawesome/free-solid-svg-icons";

import { useCollab, type ActivityEntry, type CollabUser } from "../../../providers/CollaborationProvider";
import { useNotebookViewContext } from "../../../providers/flow/notebookViewContext";
import type { Person } from "../../../providers/collab/people";
import type { CanvasPointer } from "../../../providers/collab/presence";
import { resolveNodeDisplayLabel } from "../../../utils/palettePackageFactoryDraft";
import badgeStyles from "./AgentAvatarBadge.module.css";
import styles from "./AgentDock.module.css";

/**
 * Who else is here, in the canvas's dock beside its agents: a chip for each
 * other person, the agents' chip with their initials in their color, then the
 * Activity button at the row's end. A chip's tooltip names the person, their
 * role and the node they are editing; a click moves the view to where they
 * point (their awareness `pointer`), when they point somewhere on the canvas.
 * The Activity list is the room's events: who joined, who left, whose role
 * changed.
 */

/** How long the move to where someone points takes, as an agent's new node's. */
const GO_TO_MS = 400;
/** How many of the room's events the list shows, the newest first. */
const ACTIVITY_SHOWN = 20;
const ACTIVITY_LIST_ID = "curio-room-activity";

/** What a person's chip says on hover: who, their role, and the node they
 *  are editing. */
export function personText(person: Pick<Person, "name" | "role">, editingLabel: string | null): string {
  const who = person.role ? `${person.name} (${person.role})` : person.name;
  return editingLabel ? `${who}, editing ${editingLabel}` : who;
}

const ROLE_WORDS: Record<string, string> = { owner: "the owner", editor: "an editor", watcher: "a watcher" };

/** One of the room's events, as the Activity list says it. */
export function activityText(entry: ActivityEntry, users: ReadonlyArray<CollabUser>): string {
  const payload = (entry.payload ?? {}) as Record<string, unknown>;
  const listed = typeof payload.user_id === "number" ? users.find((user) => user.user_id === payload.user_id) : undefined;
  const who = String(payload.name || listed?.name || payload.username || listed?.username || "Someone");
  const role = typeof payload.role === "string" ? payload.role : null;
  switch (entry.kind) {
    case "user_joined":
      return role ? `${who} joined (${role})` : `${who} joined`;
    case "user_left":
      return `${who} left`;
    case "role_changed":
      return role ? `${who} is now ${ROLE_WORDS[role] ?? role}` : `${who}'s role changed`;
    default:
      return entry.kind.replace(/_/g, " ");
  }
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function PersonChip({ person, onGoTo }: { person: Person; onGoTo: (person: Person) => void }) {
  // The node's name as its header shows it, read from the store by id so a
  // rename shows at once and another node's change draws nothing.
  const editingLabel = useStore(
    useCallback(
      (s: any) => {
        if (!person.editing) return null;
        const node = s.nodeInternals.get(person.editing);
        if (!node?.data) return null;
        try {
          return resolveNodeDisplayLabel(node.data);
        } catch {
          return null;
        }
      },
      [person.editing],
    ),
  );
  const text = personText(person, editingLabel);
  return (
    <div className={badgeStyles.badge} data-tooltip={text}>
      <button
        type="button"
        className={badgeStyles.avatar}
        style={{ color: person.color }}
        aria-label={text}
        data-collab-role={person.role ?? undefined}
        data-collab-participant={person.key}
        onClick={(event) => {
          event.stopPropagation();
          onGoTo(person);
        }}
      >
        <span className={styles.initials} aria-hidden="true">{person.initials}</span>
      </button>
    </div>
  );
}

function RoomActivity() {
  const { activity, users } = useCollab();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Closed by a press anywhere else or by Escape, as the bar's menus are.
  useEffect(() => {
    if (!open) return;
    const onPress = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPress, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPress, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const lines = activity.slice(-ACTIVITY_SHOWN).reverse();
  return (
    // Open, it is lit as a selected agent's chip is.
    <div className={clsx(badgeStyles.badge, open && badgeStyles.badgeActive)} ref={ref}>
      <button
        type="button"
        className={badgeStyles.avatar}
        aria-label="Activity"
        aria-expanded={open}
        aria-controls={open ? ACTIVITY_LIST_ID : undefined}
        data-tooltip="Activity"
        onClick={(event) => {
          event.stopPropagation();
          setOpen((was) => !was);
        }}
      >
        <FontAwesomeIcon icon={faListUl} className={badgeStyles.icon} />
      </button>
      {open && (
        <div id={ACTIVITY_LIST_ID} className={styles.activityList} role="region" aria-label="Activity">
          <div className={styles.activityTitle}>Activity</div>
          {lines.length === 0 ? (
            <p className={styles.activityEmpty}>No activity yet.</p>
          ) : (
            <ul className={styles.activityItems}>
              {lines.map((entry, i) => (
                <li key={`${entry.ts}-${i}`}>{activityText(entry, users)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function PeopleHere({
  people,
  pointerOf,
}: {
  people: Person[];
  pointerOf: (person: Person) => CanvasPointer | null;
}) {
  const { setCenter, getZoom } = useReactFlow();
  const notebook = useNotebookViewContext();
  const goTo = useCallback(
    (person: Person) => {
      // The notebook view has no canvas to move over.
      if (notebook.on) return;
      const at = pointerOf(person);
      if (!at) return;
      setCenter(at.x, at.y, { zoom: getZoom(), duration: prefersReducedMotion() ? 0 : GO_TO_MS });
    },
    [pointerOf, getZoom, notebook.on, setCenter],
  );
  return (
    <div className={styles.people} role="group" aria-label="People here">
      {people.map((person) => (
        <PersonChip key={person.key} person={person} onGoTo={goTo} />
      ))}
      <RoomActivity />
    </div>
  );
}
