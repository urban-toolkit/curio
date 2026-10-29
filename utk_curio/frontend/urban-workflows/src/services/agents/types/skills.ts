/**
 * Skills as the Agent Catalog shows them, an agent's skills for this account,
 * a chat's skills, and what a run's record holds of the skills it used.
 *
 * The backend's shapes, from `application/skill_catalog.py` and the run
 * record (`application/skill_runs.py`).
 */

/** An agent that uses a skill, as a skill's details name it. */
export interface SkillAgentUse {
  id: string;
  name: string;
  coord: string;
  /** A catalog card, not one of Curio's helpers. */
  card: boolean;
  /** This account added the skill to it. */
  added: boolean;
  /** Its every call holds the skill, or its chat or a mode of it always does. */
  always: boolean;
}

/**
 * Whose a skill is: Curio's; one this account imported; or the shared
 * catalog's, which an account published, or this account's copy of one it
 * gave an agent.
 */
export type SkillSource = "curio" | "yours" | "shared";

/** One skill the account sees, as its card and details show it. */
export interface SkillCard {
  name: string;
  /** When an agent uses the skill, in the skill's own words. */
  description: string;
  license?: string | null;
  compatibility?: string | null;
  author?: string | null;
  version?: string | null;
  /** Its folder's other files, by their paths there. */
  files: string[];
  /** The node behaviors it serves (`curio-behaviors`). */
  behaviors: string[];
  /** The features of a dataflow it serves (`curio-features`). */
  features: string[];
  /** The labels of the node templates whose behavior it serves. */
  nodeKinds: string[];
  /** Every call holds it: the preamble Curio's agents read places it. */
  core: boolean;
  /** Whose it is; a listing that predates the field lists Curio's alone. */
  source?: SkillSource;
  /** It is in the shared catalog. */
  published?: boolean;
  /** This account published it. */
  publishedByYou?: boolean;
  /** This account may publish it: one it imported, unpublished or its own publication. */
  publishable?: boolean;
  /** This account holds it, so it may remove it from its skills. */
  removable?: boolean;
  agents: SkillAgentUse[];
}

/** One file of a skill's upload: its path in what was picked, and the file. */
export interface SkillUploadFile {
  path: string;
  file: Blob;
}

/** An agent an import review offers a skill to. */
export interface SkillImportAgent {
  id: string;
  coord: string;
  name: string;
}

/** What an import review shows of an upload: nothing is kept yet. */
export interface SkillImportReview {
  /** The name it is kept under: the one asked for, or the one its SKILL.md gives. */
  name: string;
  /** The name its SKILL.md gives. */
  givenName: string;
  description: string;
  /** What does not follow the format, which the import reads anyway. */
  warnings: string[];
  /** What keeping it in the format leaves out, and files outside its folder. */
  leftOut: string[];
  /** Its files besides SKILL.md. */
  files: string[];
  /** Why it cannot be kept under `name`, or null. */
  problem: string | null;
  /** The problem is its name: another name keeps it. */
  rename: boolean;
  /** It replaces this account's skill of that name, an older version. */
  replaces: boolean;
  agents: SkillImportAgent[];
}

/** What an import kept. */
export interface SkillImportResult {
  skill: SkillCard;
  /** The agents given the skill, by name. */
  agents: string[];
  replaced: boolean;
}

export interface SkillListResponse {
  skills: SkillCard[];
  /** This account may add a skill to an agent or remove one. */
  editable: boolean;
  reason: string | null;
}

/** One skill's text as an agent reads it. */
export interface SkillText {
  name: string;
  text: string;
  files: string[];
}

/** One skill of an agent, as the agent's details list it. */
export interface AgentSkillRow {
  name: string;
  description: string;
  /** Its preamble holds it, so every call does. */
  core: boolean;
  /** This account added it. */
  added: boolean;
  /** Its chat holds it from its first message whatever the agent's skills
   *  are: its instruction follows it. */
  chat: boolean;
  /** The modes that hold it whatever the agent's skills are. */
  modes: string[];
  /** A call another agent asks it for, which is none of its modes, holds it
   *  whatever its skills are. */
  asked: boolean;
  removable: boolean;
}

/** An agent's skills for this account. */
export interface AgentSkills {
  coord: string;
  agentId: string;
  skills: AgentSkillRow[];
  /** The skills it does not hold, which this account may add. */
  addable: { name: string; description: string }[];
  /** This account changed its skills, which Restore undoes. */
  changed: boolean;
  editable: boolean;
  reason: string | null;
}

/** A skill a chat's next run lists, which `/<name>` hands to it. */
export interface RunSkill {
  name: string;
  description: string;
  /** The chat holds it already. */
  held: boolean;
}

/** What a run's record holds of its skills (`pins.skills`). */
export interface AgentRunSkillPins {
  /** What its chat could load. */
  catalog?: string[];
  /** Handed for the node it is attached to, and the procedures its
   *  instruction follows. */
  handed?: string[];
  /** Taken in by an earlier turn, and held again. */
  kept?: string[];
  /** Named with `/<name>` in its message. */
  named?: string[];
}
