import React, { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { useReactFlow, useStore, type Node as FlowNode } from "reactflow";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faListUl } from "@fortawesome/free-solid-svg-icons";

import { useCollab, type ActivityEntry, type CollabUser } from "../../../providers/CollaborationProvider";
import { useNotebookViewContext } from "../../../providers/flow/notebookViewContext";
import { agentHolding, agentWithAsker, canEditRole } from "../../../providers/collab/participants";
import type { Person } from "../../../providers/collab/people";
import { numberedName, type CanvasPointer } from "../../../providers/collab/presence";
import { resolveNodeDisplayLabel } from "../../../utils/palettePackageFactoryDraft";
import { AgentGlyph, agentTint } from "./AgentAvatarBadge";
import badgeStyles from "./AgentAvatarBadge.module.css";
import styles from "./AgentDock.module.css";

/**
 * Who else is here, in the canvas's dock beside its agents: a chip for each
 * other person, the agents' chip with their initials in their color, and one
 * for each agent at work, its badge's chip with its glyph in its category's
 * tint, then the Activity button at the row's end. A person's chip's tooltip
 * names them, their role and the node they are editing; a click moves the view
 * to where they point (their awareness `pointer`), when they point somewhere
 * on the canvas. An agent's names it, who asked it, the nodes it is writing
 * and the skills it is using; a click opens its chat for the owner and the
 * editors, who work with the dataflow's agents, and moves a watcher's view to
 * the node it is writing. A canvas agent at work keeps its own chip among the
 * canvas agents (`AgentDock`), shown at work. The Activity list is the room's
 * events: who joined, who left, whose role changed, and what each agent did.
 */

/** How long the move to where someone points takes, as an agent's new node's. */
const GO_TO_MS = 400;
/** How many of the room's events the list shows, the newest first. */
const ACTIVITY_SHOWN = 20;
const ACTIVITY_LIST_ID = "curio-room-activity";

/** *items* as a sentence lists them: "a", "a and b", "a, b and c". */
function inWords(items: ReadonlyArray<string>): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** What a chip says on hover: who, their role, and the node they are
 *  editing; an agent at work, who asked it, the nodes it is writing and the
 *  skills it is using: "Node Builder (asked by Ana), editing Map Editor,
 *  using map-edits". */
export function personText(
  person: Pick<Person, "name" | "role"> & Partial<Pick<Person, "agent">>,
  editingLabel: string | null,
): string {
  const agent = person.agent ?? null;
  const who = agent
    ? agentWithAsker({ name: person.name, askedBy: agent.askedBy })
    : person.role ? `${person.name} (${person.role})` : person.name;
  const parts = [who];
  if (editingLabel) parts.push(`editing ${editingLabel}`);
  if (agent && agent.skills.length > 0) parts.push(`using ${inWords(agent.skills)}`);
  return parts.join(", ");
}

const ROLE_WORDS: Record<string, string> = { owner: "the owner", editor: "an editor", watcher: "a watcher" };

/** What an agent did, as its leave counts it, by verb and thing, in the
 *  order first done (`agent_peers.Peer.did`), in plain words: "added 3 nodes
 *  and 2 connections", "added 1 node, and changed 2 nodes". Nothing for an
 *  agent that did nothing. */
function didText(did: unknown): string {
  if (!did || typeof did !== "object") return "";
  const clauses: string[] = [];
  for (const [verb, things] of Object.entries(did as Record<string, unknown>)) {
    if (!things || typeof things !== "object") continue;
    const counted = Object.entries(things as Record<string, unknown>)
      .filter((entry): entry is [string, number] => Number.isInteger(entry[1]) && (entry[1] as number) > 0)
      .map(([thing, count]) => `${count} ${thing}${count === 1 ? "" : "s"}`);
    if (counted.length > 0) clauses.push(`${verb} ${inWords(counted)}`);
  }
  if (clauses.length <= 1) return clauses[0] ?? "";
  return `${clauses.slice(0, -1).join(", ")}, and ${clauses[clauses.length - 1]}`;
}

/** One of the room's events, as the Activity list says it: a tab of the
 *  shared guest account by the number its event names, and an agent at work
 *  by who asked it and, as it leaves, what it did. */
export function activityText(entry: ActivityEntry, users: ReadonlyArray<CollabUser>): string {
  const payload = (entry.payload ?? {}) as Record<string, unknown>;
  const listed = typeof payload.user_id === "number" ? users.find((user) => user.user_id === payload.user_id) : undefined;
  const who = numberedName(String(payload.name || listed?.name || payload.username || listed?.username || "Someone"), payload);
  const role = typeof payload.role === "string" ? payload.role : null;
  switch (entry.kind) {
    case "user_joined":
      return role ? `${who} joined (${role})` : `${who} joined`;
    case "user_left":
      return `${who} left`;
    case "role_changed":
      return role ? `${who} is now ${ROLE_WORDS[role] ?? role}` : `${who}'s role changed`;
    case "agent_joined": {
      // The agent's `user`, as the server names it (`agent_peers.py`).
      const agent = agentHolding(payload);
      const name = agent?.name ?? who;
      return agent?.askedBy ? `${name} joined, asked by ${agent.askedBy}` : `${name} joined`;
    }
    case "agent_left": {
      const name = agentHolding(payload)?.name ?? who;
      const did = didText(payload.did);
      return did ? `${name} left: ${did}` : `${name} left`;
    }
    default:
      return entry.kind.replace(/_/g, " ");
  }
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** The names of the nodes *editing* lists as their headers show them, read
 *  from the store by id so a rename shows at once and another node's change
 *  draws nothing; null when none of them is on the canvas. */
function useEditingLabel(editing: ReadonlyArray<string>): string | null {
  const ids = JSON.stringify(editing);
  return useStore(
    useCallback(
      (s: any) => {
        const labels = (JSON.parse(ids) as string[]).flatMap((nodeId) => {
          const node = s.nodeInternals.get(nodeId);
          if (!node?.data) return [];
          try {
            const label = resolveNodeDisplayLabel(node.data);
            return label ? [label] : [];
          } catch {
            return [];
          }
        });
        return labels.length > 0 ? inWords(labels) : null;
      },
      [ids],
    ),
  );
}

/** What an agent at work's chip says, its nodes' names kept as they change:
 *  its chip in the row's, and a canvas agent's own chip's (`AgentDock`). */
export function useAgentAtWorkText(person: Person): string {
  return personText(person, useEditingLabel(person.editing));
}

/** Where the middle of *node* is, in flow coordinates. */
function middleOf(node: FlowNode | undefined): { x: number; y: number } | null {
  const at = node?.positionAbsolute ?? node?.position;
  if (!node || !at) return null;
  return { x: at.x + (node.width ?? 0) / 2, y: at.y + (node.height ?? 0) / 2 };
}

/** An agent at work: its badge's chip, its glyph in its category's tint, with
 *  the running dot. */
function AgentChip({ person, onClick }: { person: Person; onClick: (person: Person) => void }) {
  const text = useAgentAtWorkText(person);
  const agent = person.agent!;
  return (
    <div className={badgeStyles.badge} data-tooltip={text}>
      <button
        type="button"
        className={clsx(badgeStyles.avatar, agentTint(agent.category))}
        aria-label={text}
        data-collab-participant={person.key}
        data-collab-agent={agent.attachmentId ?? ""}
        onClick={(event) => {
          event.stopPropagation();
          onClick(person);
        }}
      >
        <AgentGlyph category={agent.category} working={text} />
      </button>
    </div>
  );
}

function PersonChip({ person, onGoTo }: { person: Person; onGoTo: (person: Person) => void }) {
  const editingLabel = useEditingLabel(person.editing);
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
  onOpenAgent,
}: {
  people: Person[];
  pointerOf: (person: Person) => CanvasPointer | null;
  /** Opens the chat of the agent attached as *attachmentId*: the dock's. */
  onOpenAgent: (attachmentId: string) => void;
}) {
  const { setCenter, getZoom, getNode } = useReactFlow();
  const notebook = useNotebookViewContext();
  // Whether this tab works with the dataflow's agents: the owner's and an
  // editor's do, a watcher's has none (`canvasRole`'s rule, on the room's
  // role, which every tab an agent is here for has).
  const { role } = useCollab();
  const drivesAgents = canEditRole(role);
  const moveTo = useCallback(
    (at: { x: number; y: number } | null) => {
      // The notebook view has no canvas to move over.
      if (notebook.on || !at) return;
      setCenter(at.x, at.y, { zoom: getZoom(), duration: prefersReducedMotion() ? 0 : GO_TO_MS });
    },
    [getZoom, notebook.on, setCenter],
  );
  const goTo = useCallback((person: Person) => moveTo(pointerOf(person)), [moveTo, pointerOf]);
  // An agent's chip opens its chat for whoever works with the agents, and
  // moves a watcher's view to the node it is writing, else to where it drags.
  const goToAgent = useCallback(
    (person: Person) => {
      const attachmentId = person.agent?.attachmentId;
      if (drivesAgents) {
        if (attachmentId) onOpenAgent(attachmentId);
        return;
      }
      const held = person.editing.length > 0 ? middleOf(getNode(person.editing[0])) : null;
      moveTo(held ?? pointerOf(person));
    },
    [drivesAgents, getNode, moveTo, onOpenAgent, pointerOf],
  );
  return (
    <div className={styles.people} role="group" aria-label="People here">
      {people.map((person) =>
        person.agent ? (
          <AgentChip key={person.key} person={person} onClick={goToAgent} />
        ) : (
          <PersonChip key={person.key} person={person} onGoTo={goTo} />
        ),
      )}
      <RoomActivity />
    </div>
  );
}
