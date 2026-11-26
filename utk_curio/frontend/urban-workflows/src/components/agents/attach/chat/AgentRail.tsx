import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import clsx from "clsx";

import { attachmentDisplayName, type AgentAttachment } from "../../../../services/agents";
import { AgentGlyph, waitsForYou } from "../AgentAvatarBadge";
import { agentChipClass } from "./ChatHeader";
import { targetPhraseFor, type TargetPhrase } from "./chatPanelDerived";
import { useMenuPopup } from "./useMenuPopup";
import styles from "./AgentRail.module.css";

/** How many attachments make one agent a single entry of the rail. */
export const RAIL_GROUP_SIZE = 3;

/** One entry of the rail: one attachment, or every attachment of an agent
 *  attached RAIL_GROUP_SIZE times or more. */
export interface RailEntry {
  key: string;
  members: AgentAttachment[];
}

/** The rail's entries in the attachments' order. An agent attached three times
 *  or more is one entry, where its first attachment is. */
export function railEntriesOf(attachments: AgentAttachment[]): RailEntry[] {
  const byAgent = new Map<string, AgentAttachment[]>();
  for (const a of attachments) byAgent.set(a.coord, [...(byAgent.get(a.coord) ?? []), a]);
  const entries: RailEntry[] = [];
  const grouped = new Set<string>();
  for (const a of attachments) {
    const members = byAgent.get(a.coord) ?? [a];
    if (members.length < RAIL_GROUP_SIZE) {
      entries.push({ key: a.attachmentId, members: [a] });
    } else if (!grouped.has(a.coord)) {
      grouped.add(a.coord);
      entries.push({ key: `agent:${a.coord}`, members });
    }
  }
  return entries;
}

/** The room a group's list keeps above and below it, inside the panel. */
const LIST_GAP = 8;

/** Where a group's list starts in the panel: beside its entry, *entryTop*
 *  down, moved up as far as it takes to end inside the panel's *room*, never
 *  above its top. */
export function listTopWithin(entryTop: number, listHeight: number, room: number): number {
  return Math.max(LIST_GAP, Math.min(entryTop, room - listHeight - LIST_GAP));
}

/** "6 nodes", "3 connections", or "3 places" for a mix. */
function placesOf(members: AgentAttachment[]): string {
  const kinds = new Set(members.map((m) => m.target.kind));
  const noun = kinds.size === 1 && kinds.has("node") ? "node" : kinds.size === 1 && kinds.has("connection") ? "connection" : "place";
  return `${members.length} ${noun}${members.length === 1 ? "" : "s"}`;
}

/** How the rail names one attachment. */
interface RailName {
  /** Its conversation's name, as its dock badge says it ("Node Builder:
   *  Heat colors" once titled), and its number among the instances of the
   *  agent on one place that would read the same ("Dataset Finder (2)"):
   *  its entry's tooltip and accessible name. */
  name: string;
  /** Its entry's label: the agent's name, and that number ("Dataset Finder
   *  (2)"). */
  label: string;
  /** What it is attached to. */
  phrase: TargetPhrase;
  /** Its row in its group's list: the place, the title and the number. */
  row: string;
  /** The same after "open", as its group's entry names its open node: "on
   *  Load heat (2)", "from A to B". */
  rowHeader: string;
}

/** Each attachment's name on the rail, by attachment id. Two instances of one
 *  agent on one place are told apart by their conversations' titles, and by
 *  number, in the attachments' order, when those read the same too. */
function railNamesOf(
  attachments: AgentAttachment[],
  targetNameOf: (attachment: AgentAttachment) => string | null,
): Map<string, RailName> {
  const read = attachments.map((a) => {
    const phrase = targetPhraseFor(a, targetNameOf(a));
    return { a, phrase, label: `${attachmentDisplayName(a)} ${phrase.header}` };
  });
  const alike = new Map<string, number>();
  for (const { label } of read) alike.set(label, (alike.get(label) ?? 0) + 1);
  const seen = new Map<string, number>();
  const names = new Map<string, RailName>();
  for (const { a, phrase, label } of read) {
    const nth = (seen.get(label) ?? 0) + 1;
    seen.set(label, nth);
    const number = (alike.get(label) ?? 0) > 1 ? ` (${nth})` : "";
    const after = `${a.title ? `: ${a.title}` : ""}${number}`;
    names.set(a.attachmentId, {
      name: `${attachmentDisplayName(a)}${number}`,
      label: `${a.name}${number}`,
      phrase,
      row: `${phrase.short ?? phrase.object}${after}`,
      rowHeader: `${phrase.header}${after}`,
    });
  }
  return names;
}

/**
 * The agents on this dataflow, down the chat panel's left side, in the
 * attachments' order: each one's glyph in its category's tint, its agent's
 * name, and under it what it is attached to. Hovering an entry names its
 * conversation, as its dock badge does, with the conversation's title once it
 * has one, and what it is attached to; that is its accessible name too. Two
 * instances of one agent on one place that would read the same are numbered,
 * on the label as in the name. The open chat's entry is marked
 * (`aria-current`); an agent at work shows its running dot, from its job and
 * from the room, as its badge does, and an agent that waits for you to pick a
 * node's source its waiting dot (`waitsForYou`). An agent attached three times
 * or more (six Node Builders) is one entry, which opens the list of its
 * nodes; each row opens that node's chat. A group shows each dot when any of
 * its members has it, and its list says which.
 */
export const AgentRail: React.FC<{
  attachments: AgentAttachment[];
  /** The attachment whose chat is open. */
  selectedId: string;
  onOpen: (attachmentId: string) => void;
  /** What an attachment is attached to, as the overlay names it from the
   *  canvas: a node's name, "from A to B" for a connection; null for the
   *  canvas, or a target the canvas no longer holds. */
  targetNameOf: (attachment: AgentAttachment) => string | null;
  /** What an agent at work is doing, for its running dot; null while it is
   *  not at work. */
  workingOf: (attachment: AgentAttachment) => string | null;
}> = ({ attachments, selectedId, onOpen, targetNameOf, workingOf }) => {
  const entries = railEntriesOf(attachments);
  const names = railNamesOf(attachments, targetNameOf);
  const nameOf = (attachment: AgentAttachment): RailName =>
    names.get(attachment.attachmentId) ?? railNamesOf([attachment], targetNameOf).get(attachment.attachmentId)!;
  const popup = useMenuPopup<string>();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // The open group's list sits beside its entry, over the conversation.
  const [flyoutTop, setFlyoutTop] = useState(0);
  const openEntry = entries.find((entry) => entry.key === popup.open) ?? null;

  // A group that dissolves (one of three detached) takes its list with it,
  // and the list's layer of the modal stack: the chat's Escape is its own
  // again. Formed again, the group comes back with its list closed.
  const listGone = popup.open !== null && openEntry === null;
  const { close } = popup;
  useEffect(() => {
    if (listGone) close();
  }, [listGone, close]);

  // Beside its entry, moved up as far as it takes to end inside the panel.
  // Read on the screen, so the rail's own scroll counts once.
  useLayoutEffect(() => {
    const anchor = popup.anchorRef.current;
    const wrap = wrapRef.current;
    if (popup.open === null || !anchor || !wrap) return;
    const panel = wrap.getBoundingClientRect();
    const listHeight = popup.menuRef.current?.getBoundingClientRect().height ?? 0;
    setFlyoutTop(listTopWithin(anchor.getBoundingClientRect().top - panel.top, listHeight, panel.height));
  }, [popup.open, popup.anchorRef, popup.menuRef]);

  return (
    <div ref={wrapRef} className={styles.railWrap}>
      <nav className={styles.rail} aria-label="Agents on this dataflow">
        {entries.map((entry) => {
          const first = entry.members[0];
          const open = entry.members.find((m) => m.attachmentId === selectedId) ?? null;
          const working = entry.members.map(workingOf).find(Boolean) ?? null;
          const waiting = entry.members.filter(waitsForYou).length;
          if (entry.members.length === 1) {
            const { name, label, phrase } = nameOf(first);
            const named = `${name} ${phrase.header}`;
            return (
              <button
                key={entry.key}
                type="button"
                className={clsx(styles.entry, open && styles.entryOpen)}
                aria-current={open ? "true" : undefined}
                aria-label={[named, waiting ? "waits for you" : null, working ? "at work" : null].filter(Boolean).join(", ")}
                data-tooltip={named}
                data-curio-rail-entry={first.attachmentId}
                onClick={() => onOpen(first.attachmentId)}
              >
                <span className={clsx(styles.glyph, agentChipClass(first.category))}>
                  <AgentGlyph category={first.category} working={working} waiting={waiting > 0} />
                </span>
                <span className={styles.name}>{label}</span>
                {phrase.short ? <span className={styles.sub}>{phrase.short}</span> : null}
              </button>
            );
          }
          // A group is the agent's: its name is the agent's, and the open
          // node is named as its row in the list.
          const places = placesOf(entry.members);
          const openName = open ? nameOf(open) : null;
          const atWork = entry.members.filter((member) => workingOf(member)).length;
          const label = [
            `${first.name} on ${places}`,
            openName ? `open ${openName.rowHeader}` : null,
            waiting ? `${waiting === 1 ? "one waits" : `${waiting} wait`} for you` : null,
            atWork ? `${atWork === 1 ? "one" : atWork} at work` : null,
          ].filter(Boolean).join(", ");
          return (
            <button
              key={entry.key}
              type="button"
              className={clsx(styles.entry, open && styles.entryOpen, popup.open === entry.key && styles.entryExpanded)}
              aria-current={open ? "true" : undefined}
              aria-haspopup="menu"
              aria-expanded={popup.open === entry.key}
              aria-label={label}
              data-tooltip={`${first.name} on ${places}`}
              data-curio-rail-group={first.coord}
              onClick={(event) => {
                popup.anchorRef.current = event.currentTarget;
                popup.toggle(entry.key);
              }}
            >
              <span className={clsx(styles.glyph, agentChipClass(first.category))}>
                <AgentGlyph category={first.category} working={working} waiting={waiting > 0} />
                <span className={styles.count} aria-hidden="true">{entry.members.length}</span>
              </span>
              <span className={styles.name}>{first.name}</span>
              <span className={styles.sub}>{openName?.row ?? places}</span>
            </button>
          );
        })}
      </nav>
      {openEntry ? (
        <div
          ref={popup.menuRef}
          className={styles.flyout}
          style={{ top: flyoutTop }}
          role="menu"
          aria-label={`${openEntry.members[0].name} on`}
          onKeyDown={popup.onMenuKeyDown}
        >
          <div className={styles.flyoutHead} aria-hidden="true">
            {openEntry.members[0].name} on
          </div>
          {openEntry.members.map((member) => {
            const { name, phrase, row } = nameOf(member);
            const working = workingOf(member);
            const waiting = waitsForYou(member);
            const current = member.attachmentId === selectedId;
            return (
              <button
                key={member.attachmentId}
                type="button"
                role="menuitem"
                className={clsx(styles.flyoutItem, current && styles.flyoutItemOpen)}
                aria-current={current ? "true" : undefined}
                data-tooltip={`${name} ${phrase.header}`}
                data-curio-rail-entry={member.attachmentId}
                onClick={() => {
                  // The focus goes back to the group's entry, as Escape hands
                  // it, rather than to the page with the list.
                  popup.close(true);
                  onOpen(member.attachmentId);
                }}
              >
                <span
                  className={clsx(styles.flyoutDot, working && styles.flyoutDotWorking, waiting && styles.flyoutDotWaiting)}
                  aria-hidden="true"
                />
                <span className={styles.flyoutName}>{row}</span>
                {waiting ? <span className={clsx(styles.flyoutNote, styles.flyoutNoteWaiting)}>waits for you</span> : null}
                {working ? <span className={styles.flyoutNote}>at work</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};
