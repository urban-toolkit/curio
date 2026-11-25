import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import clsx from "clsx";

import { attachmentDisplayName, type AgentAttachment } from "../../../../services/agents";
import { AgentGlyph } from "../AgentAvatarBadge";
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
   *  agent on one place that would read the same ("Dataset Finder (2)"). */
  name: string;
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
      phrase,
      row: `${phrase.short ?? phrase.object}${after}`,
      rowHeader: `${phrase.header}${after}`,
    });
  }
  return names;
}

/**
 * The agents on this dataflow, down the chat panel's left side, in the
 * attachments' order: each one's glyph in its category's tint, its name, and
 * what it is attached to. Each is named as its dock badge names it, with its
 * conversation's title once it has one, and numbered when two instances of
 * one agent on one place would read the same. The open chat's entry is
 * marked (`aria-current`); an
 * agent at work shows its running dot, from its job and from the room, as its
 * badge does; hovering an entry names what it is attached to. An agent
 * attached three times or more (six Node Builders) is one entry, which opens
 * the list of its nodes; each row opens that node's chat.
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
  const railRef = useRef<HTMLElement | null>(null);
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

  useLayoutEffect(() => {
    const anchor = popup.anchorRef.current;
    const rail = railRef.current;
    if (popup.open === null || !anchor || !rail) return;
    setFlyoutTop(anchor.offsetTop - rail.scrollTop);
  }, [popup.open, popup.anchorRef]);

  return (
    <div className={styles.railWrap}>
      <nav ref={railRef} className={styles.rail} aria-label="Agents on this dataflow">
        {entries.map((entry) => {
          const first = entry.members[0];
          const open = entry.members.find((m) => m.attachmentId === selectedId) ?? null;
          const working = entry.members.map(workingOf).find(Boolean) ?? null;
          if (entry.members.length === 1) {
            const { name, phrase } = nameOf(first);
            const named = `${name} ${phrase.header}`;
            return (
              <button
                key={entry.key}
                type="button"
                className={clsx(styles.entry, open && styles.entryOpen)}
                aria-current={open ? "true" : undefined}
                aria-label={working ? `${named}, at work` : named}
                data-tooltip={named}
                data-curio-rail-entry={first.attachmentId}
                onClick={() => onOpen(first.attachmentId)}
              >
                <span className={clsx(styles.glyph, agentChipClass(first.category))}>
                  <AgentGlyph category={first.category} working={working} />
                </span>
                <span className={styles.name}>{name}</span>
                {phrase.short ? <span className={styles.sub}>{phrase.short}</span> : null}
              </button>
            );
          }
          // A group is the agent's: its name is the agent's, and the open
          // node is named as its row in the list.
          const places = placesOf(entry.members);
          const openName = open ? nameOf(open) : null;
          const label = [
            `${first.name} on ${places}`,
            openName ? `open ${openName.rowHeader}` : null,
            working ? "one at work" : null,
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
                <AgentGlyph category={first.category} working={working} />
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
                  popup.close();
                  onOpen(member.attachmentId);
                }}
              >
                <span className={clsx(styles.flyoutDot, working && styles.flyoutDotWorking)} aria-hidden="true" />
                <span className={styles.flyoutName}>{row}</span>
                {working ? <span className={styles.flyoutNote}>at work</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};
