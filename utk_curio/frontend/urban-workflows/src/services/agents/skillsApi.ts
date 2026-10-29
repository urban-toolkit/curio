/**
 * REST client for skills in the Agent Catalog (`routes/skills.py`): the skills
 * the account sees, one skill's text, an agent's skills with this account's
 * changes to them, the skills a chat's next run lists, and the account's own
 * skills, imported through a review, exported, published and removed.
 *
 * Its own module beside `agentsApi`, so a surface that only reads skills
 * reaches no other agent route. JSON goes through `apiFetch`; an upload is
 * multipart and an export a zip, which go through `fetch` here, as the
 * packages' archive transport does.
 */

import { apiFetch, getToken } from "../../utils/authApi";
import { backendUrl } from "../../utils/backendUrl";
import { triggerBlobDownload } from "../packages/packagesBlobTransport";

import type {
  AgentSkills,
  RunSkill,
  SkillImportResult,
  SkillImportReview,
  SkillListResponse,
  SkillText,
  SkillUploadFile,
} from "./types";

const BACKEND_URL = backendUrl();

function coordParam(coord: string): string {
  return encodeURIComponent(coord);
}

/**
 * The form of a skill's upload: each file under `files`, and `paths`, their
 * paths in what was picked, in the same order, which a picked folder keeps
 * and a file's own name cannot. `name` keeps the skill under another name,
 * and `agents` lists the agents given it.
 */
export function skillUploadForm(
  files: SkillUploadFile[],
  fields: { name?: string | null; agents?: string[] } = {},
): FormData {
  const form = new FormData();
  for (const { path, file } of files) {
    form.append("files", file, path.split("/").pop() || "file");
  }
  form.append("paths", JSON.stringify(files.map(({ path }) => path)));
  if (fields.name) form.append("name", fields.name);
  if (fields.agents) form.append("agents", JSON.stringify(fields.agents));
  return form;
}

function authHeaders(): Record<string, string> | undefined {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : undefined;
}

/** The error a failed response carries, its server's own words first. */
async function failure(res: Response): Promise<Error> {
  const body = await res.json().catch(() => ({}));
  const err = new Error(body.error || `HTTP ${res.status}`);
  (err as { status?: number }).status = res.status;
  return err;
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, { method: "POST", body: form, headers: authHeaders() });
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

export const skillsApi = {
  /** Every skill the account sees, with what it serves, whose it is and the agents that use it. */
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

  /** What the import review shows of an upload, kept under *name* when given; nothing is kept. */
  checkImport(files: SkillUploadFile[], name?: string | null): Promise<SkillImportReview> {
    return postForm("/api/agents/skills/imports/check", skillUploadForm(files, { name }));
  },

  /** Keep an upload as this account's skill, and give it to the agents at *agents*. */
  importSkill(
    files: SkillUploadFile[],
    { name, agents }: { name?: string | null; agents: string[] },
  ): Promise<SkillImportResult> {
    return postForm("/api/agents/skills/imports", skillUploadForm(files, { name, agents }));
  },

  /** Save a skill as a zip of its folder, which agentskills.io's tools read. */
  async exportSkill(name: string): Promise<void> {
    const res = await fetch(`${BACKEND_URL}/api/agents/skills/${encodeURIComponent(name)}/export`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw await failure(res);
    triggerBlobDownload(await res.blob(), `${name}.zip`);
  },

  /** Delete a skill this account holds, and take it off every agent's list. */
  removeOwnSkill(name: string): Promise<{ name: string; removed: boolean; agents: string[] }> {
    return apiFetch(`/api/agents/skills/${encodeURIComponent(name)}`, { method: "DELETE" });
  },

  /** Publish one of this account's own skills to the shared catalog. */
  publishSkill(name: string): Promise<{ name: string; published: boolean }> {
    return apiFetch("/api/agents/skills/publications", { method: "POST", body: JSON.stringify({ name }) });
  },

  /** Take a skill this account published out of the shared catalog. */
  unpublishSkill(name: string): Promise<{ name: string; published: boolean }> {
    return apiFetch(`/api/agents/skills/publications/${encodeURIComponent(name)}`, { method: "DELETE" });
  },
};
