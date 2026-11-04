import { apiFetch } from "../utils/authApi";

/** An account the owner invited to edit a dataflow (`projects/access.py`). */
export interface ProjectEditor {
  user_id: number;
  username: string;
  name: string;
  added_at: string | null;
}

interface EditorsResponse {
  editors: ProjectEditor[];
}

/**
 * A dataflow's editors, for its owner. Each call answers with the list as it
 * stands after it; a refusal rejects with the server's sentence, which the
 * Invite editors dialog shows as it is.
 */
export const projectEditorsApi = {
  list(projectId: string): Promise<ProjectEditor[]> {
    return apiFetch<EditorsResponse>(`/api/projects/${projectId}/editors`).then((r) => r.editors);
  },

  add(projectId: string, username: string): Promise<ProjectEditor[]> {
    return apiFetch<EditorsResponse>(`/api/projects/${projectId}/editors`, {
      method: "POST",
      body: JSON.stringify({ username }),
    }).then((r) => r.editors);
  },

  remove(projectId: string, userId: number): Promise<ProjectEditor[]> {
    return apiFetch<EditorsResponse>(`/api/projects/${projectId}/editors/${userId}`, {
      method: "DELETE",
    }).then((r) => r.editors);
  },
};
