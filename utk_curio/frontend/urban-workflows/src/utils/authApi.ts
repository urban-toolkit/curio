import Cookies from "js-cookie";
import { backendUrl } from "./backendUrl";
import { basePath } from "./basePath";

const BACKEND_URL = backendUrl();

// The app's base path names the cookie and scopes it, so two instances on one
// host (/app and /app-dev) keep separate sign-ins. At the root it is
// session_token.
function tokenCookie(): { name: string; path: string } {
  const base = basePath();
  return { name: `session_token${base.replace(/\//g, "_")}`, path: base || "/" };
}

export function getToken(): string | undefined {
  return Cookies.get(tokenCookie().name);
}

export function setToken(token: string): void {
  const { name, path } = tokenCookie();
  Cookies.set(name, token, { path, expires: 30 });
}

export function clearToken(): void {
  const { name, path } = tokenCookie();
  Cookies.remove(name, { path });
}

/**
 * Whether a failed request says the session is over. The server answers a dead
 * session (no token, an unknown or expired one, a deleted account) with 401
 * and nothing else. An aborted request, a network failure or a server error
 * says nothing about the session.
 */
export function isUnauthorized(error: unknown): boolean {
  return (error as { status?: number } | null)?.status === 401;
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: RequestInit = {}
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(opts.headers as Record<string, string>),
  };
  if (opts.body != null && !("Content-Type" in headers)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BACKEND_URL}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.error || `HTTP ${res.status}`);
    (err as any).status = res.status;
    (err as any).body = body;
    throw err;
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

export interface AuthResponse {
  user: UserData;
  token: string;
}

export interface UserData {
  id: number;
  username: string;
  name: string;
  email: string | null;
  profile_image: string | null;
  type: string | null;
  is_guest: boolean;
  /** The Data source keys this account saved, by the secret id their sources
   * declare, each as `true`. A key itself never leaves the server. */
  has_source_keys?: Record<string, boolean>;
}

export interface PublicConfig {
  allow_guest_login: boolean;
  curio_no_auth: boolean;
  curio_no_project: boolean;
  skip_project_page: boolean;
  curio_env: string;
  shared_guest_username: string;
  collab_namespace: string;
  default_save_node_output: boolean;
}

export const authApi = {
  signup(data: {
    name: string;
    username: string;
    password: string;
    email?: string;
  }): Promise<AuthResponse> {
    return apiFetch("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  signin(data: {
    identifier: string;
    password: string;
  }): Promise<AuthResponse> {
    return apiFetch("/api/auth/signin", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  signinGuest(): Promise<AuthResponse> {
    return apiFetch("/api/auth/signin/guest", { method: "POST" });
  },

  signinAutoGuest(): Promise<AuthResponse> {
    return apiFetch("/api/auth/signin/auto-guest", { method: "POST" });
  },

  signout(): Promise<void> {
    return apiFetch("/api/auth/signout", { method: "POST" });
  },

  getMe(): Promise<UserData> {
    return apiFetch("/api/auth/me");
  },

  /** Profile fields, and Data source keys by secret id (an API Settings row's
   *  `slot`): an empty string removes one, and a key left out stays. */
  patchMe(data: {
    name?: string;
    email?: string;
    type?: string;
    source_keys?: Record<string, string>;
  }): Promise<UserData> {
    return apiFetch("/api/auth/me", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  getPublicConfig(): Promise<PublicConfig> {
    return apiFetch("/api/config/public");
  },
};
