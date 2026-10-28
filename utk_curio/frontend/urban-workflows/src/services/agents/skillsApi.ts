/**
 * REST client for skills in the Agent Catalog (`routes/skills.py`): the skills
 * Curio ships, one skill's text, an agent's skills with this account's changes
 * to them, and the skills a chat's next run lists.
 *
 * Its own module beside `agentsApi`, so a surface that only reads skills
 * reaches no other agent route.
 */

import { apiFetch } from "../../utils/authApi";

import type { AgentSkills, RunSkill, SkillListResponse, SkillText } from "./types";

function coordParam(coord: string): string {
  return encodeURIComponent(coord);
}

export const skillsApi = {
  /** Every skill Curio ships, with what it serves and the agents that use it. */
  list(): Promise<SkillListResponse> {
    return apiFetch("/api/agents/skills");
  },

  /** One skill's text as an agent reads it, and its other files. */
  read(name: string): Promise<SkillText> {
    return apiFetch(`/api/agents/skills/${encodeURIComponent(name)}`);
  },

  /** An agent's skills for this account, and the skills it may add. */
  agentSkills(coord: string): Promise<AgentSkills> {
    return apiFetch(`/api/agents/definitions/${coordParam(coord)}/skills`);
  },

  /** Add a skill to an agent, for this account. */
  addSkill(coord: string, name: string): Promise<AgentSkills> {
    return apiFetch(`/api/agents/definitions/${coordParam(coord)}/skills`, {
      method: "POST",
      body: JSON.stringify({ skill: name }),
    });
  },

  /** Remove a skill from an agent, for this account. */
  removeSkill(coord: string, name: string): Promise<AgentSkills> {
    return apiFetch(
      `/api/agents/definitions/${coordParam(coord)}/skills/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    );
  },

  /** Give an agent back the skills its manifest names, for this account. */
  restoreSkills(coord: string): Promise<AgentSkills> {
    return apiFetch(`/api/agents/definitions/${coordParam(coord)}/skills`, { method: "DELETE" });
  },

  /** The skills the next run of a chat lists: what `/` offers in it. */
  runSkills(projectId: string, attachmentId: string): Promise<{ skills: RunSkill[] }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/skills`,
    );
  },
};
