/**
 * Pure logic the surfaces share about skills: the skills a reply's run used,
 * as the line under the reply names them; the `/` command a message starts
 * with, as the composer's menu reads and writes it; and the words for what a
 * skill serves.
 */

import type { AgentExecution } from "./types";

/** How a reply's run came to hold a skill. */
export type SkillUse = "handed" | "named" | "kept" | "loaded";

export interface UsedSkill {
  name: string;
  use: SkillUse;
}

/** What each way of holding a skill says, on hover of its name. */
export const SKILL_USE_WORDS: Record<SkillUse, string> = {
  handed: "Handed for this chat's node or instruction",
  named: "Named with / in the message",
  kept: "Kept from earlier in this chat",
  loaded: "Loaded for this reply",
};

/**
 * The skills a reply's run held or loaded, each once, as its record keeps
 * them: those it was handed for its node or its instruction, those its
 * message named, those earlier turns took in, then those it loaded. None for
 * a run that predates the record's skills.
 */
export function skillsUsedBy(execution: AgentExecution | null | undefined): UsedSkill[] {
  const held = execution?.pins?.skills ?? {};
  const found: UsedSkill[] = [];
  const add = (names: unknown, use: SkillUse) => {
    for (const name of Array.isArray(names) ? names : []) {
      if (typeof name === "string" && name && !found.some((skill) => skill.name === name)) {
        found.push({ name, use });
      }
    }
  };
  add(held.handed, "handed");
  add(held.named, "named");
  add(held.kept, "kept");
  add(execution?.skillsLoaded, "loaded");
  return found;
}

/** Where the first word of *text* ends. */
function firstWordEnd(text: string): number {
  const end = text.search(/\s/);
  return end < 0 ? text.length : end;
}

/**
 * The `/` command being typed at the start of *text*: what follows the slash
 * in its first word, while the caret at *caret* is still in that word. Null
 * when the message starts with no slash, or the caret has left the word.
 */
export function slashQuery(text: string, caret: number): string | null {
  if (!text.startsWith("/")) return null;
  const end = firstWordEnd(text);
  if (caret < 1 || caret > end) return null;
  return text.slice(1, end);
}

/** *text* with its first word, a `/` command, replaced by `/<name>` and a space. */
export function withSlashCommand(text: string, name: string): string {
  const rest = text.slice(firstWordEnd(text)).replace(/^\s+/, "");
  return `/${name} ${rest}`;
}

/** The skills of *skills* whose name holds *query*, those that start with it first. */
export function skillsMatching<T extends { name: string }>(skills: T[], query: string): T[] {
  const wanted = query.toLowerCase();
  const starting = skills.filter((skill) => skill.name.startsWith(wanted));
  const holding = skills.filter((skill) => !skill.name.startsWith(wanted) && skill.name.includes(wanted));
  return [...starting, ...holding];
}

/** The words for each feature of a dataflow a skill can serve (its `curio-features`). */
export const SKILL_FEATURE_WORDS: Record<string, string> = {
  "scenario-boxes": "Dataflows with scenario boxes",
  "interaction-edges": "Dataflows with interaction edges",
  "pinned-tiles": "Dataflows with pinned tiles",
};

/** What a skill serves, in the words its details show: each kind of node by
 *  its label, then each feature of a dataflow. */
export function skillServes(skill: { nodeKinds: string[]; features: string[] }): string[] {
  return [
    ...skill.nodeKinds,
    ...skill.features.map((feature) => SKILL_FEATURE_WORDS[feature] ?? feature),
  ];
}
