import Cookies from "js-cookie";

const BACKEND_URL = process.env.BACKEND_URL || "";
const TOKEN_KEY = "session_token";

export function getToken(): string | undefined {
  return Cookies.get(TOKEN_KEY);
}

export function setToken(token: string): void {
  Cookies.set(TOKEN_KEY, token, { expires: 30 });
}

export function clearToken(): void {
  Cookies.remove(TOKEN_KEY);
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
  has_llm_api_key: boolean;
  llm_api_type: string | null;
  llm_base_url: string | null;
  llm_model: string | null;
}

export interface PublicConfig {
  allow_guest_login: boolean;
  curio_no_auth: boolean;
  curio_no_project: boolean;
  skip_project_page: boolean;
  google_client_id: string;
  curio_env: string;
  shared_guest_username: string;
  enable_collab: boolean;
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

  signinGoogle(code: string): Promise<AuthResponse> {
    return apiFetch("/api/auth/signin/google", {
      method: "POST",
      body: JSON.stringify({ code }),
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

  patchMe(data: {
    name?: string;
    email?: string;
    type?: string;
    llm_api_type?: string;
    llm_base_url?: string;
    llm_api_key?: string;
    llm_model?: string;
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
