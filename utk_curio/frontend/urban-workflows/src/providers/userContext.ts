import { createContext, useContext } from "react";
import type { UserData } from "../utils/authApi";

/**
 * The signed-in user, as UserProvider supplies it. Kept apart from
 * UserProvider, which loads the node registry, so a component anywhere can
 * read it without that import.
 */

export interface UserProviderProps {
  user: UserData | null;
  loading: boolean;
  isAuthenticated: boolean;
  enableUserAuth: boolean;
  skipProjectPage: boolean;
  allowGuest: boolean;
  sharedGuestUsername: string;
  /**
   * Is the session browsing as the ONE account every guest sign-in resolves to?
   *
   * Not the same question as ``user.is_guest``. The shared guest is a single
   * ``User`` row that every anonymous visitor shares, so anything scoped to
   * "this account" -- its dataset store, and the ``publisher`` recorded when it
   * publishes -- is really scoped to "all guests at once". Surfaces that offer
   * to write shared state use this to withhold the control; the server refuses
   * the request regardless (#222).
   */
  isSharedGuest: boolean;
  signup: (data: {
    name: string;
    username: string;
    password: string;
    email?: string;
  }) => Promise<UserData | null>;
  signin: (identifier: string, password: string) => Promise<UserData | null>;
  signinGuest: () => Promise<UserData | null>;
  signout: () => Promise<void>;
  updateProfile: (data: {
    name?: string;
    email?: string;
    type?: string;
  }) => Promise<void>;
  /** Save or clear account keys, by the field `PATCH /api/auth/me` takes each
   * under (an API Settings row's `field`). An empty string clears one. LLM
   * configurations are saved through `llmConfigsApi` instead. */
  updateTokens: (fields: Record<string, string>) => Promise<void>;
  saveUserType: (newType: "programmer" | "expert") => Promise<void>;
  logout: () => void;
}

export const UserContext = createContext<UserProviderProps>({
  user: null,
  loading: false,
  isAuthenticated: false,
  enableUserAuth: true,
  skipProjectPage: false,
  allowGuest: false,
  sharedGuestUsername: "guest_shared",
  isSharedGuest: false,
  signup: async () => null,
  signin: async () => null,
  signinGuest: async () => null,
  signout: async () => {},
  updateProfile: async () => {},
  updateTokens: async () => {},
  saveUserType: async () => {},
  logout: () => {},
});

export const useUserContext = () => {
  const context = useContext(UserContext);
  if (!context) {
    throw new Error("useUserContext must be used within a UserProvider");
  }
  return context;
};
