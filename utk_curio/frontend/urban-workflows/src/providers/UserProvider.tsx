import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  authApi,
  clearToken,
  getToken,
  setToken,
  UserData,
} from "../utils/authApi";
import { refreshPackRegistry } from "../registry/packRegistryBootstrap";
import { Loading } from "../components/login/Loading";

interface UserProviderProps {
  user: UserData | null;
  loading: boolean;
  isAuthenticated: boolean;
  enableUserAuth: boolean;
  skipProjectPage: boolean;
  allowGuest: boolean;
  sharedGuestUsername: string;
  googleClientId: string;
  signup: (data: {
    name: string;
    username: string;
    password: string;
    email?: string;
  }) => Promise<UserData | null>;
  signin: (identifier: string, password: string) => Promise<UserData | null>;
  signinGuest: () => Promise<UserData | null>;
  signinWithGoogle: (code: string) => Promise<UserData | null>;
  signout: () => Promise<void>;
  updateProfile: (data: {
    name?: string;
    email?: string;
    type?: string;
  }) => Promise<void>;
  updateLlmConfig: (config: {
    apiType?: string;
    baseUrl?: string;
    apiKey?: string;
    model?: string;
  }) => Promise<void>;
  saveUserType: (newType: "programmer" | "expert") => Promise<void>;
  googleSignIn: (googleCode: string) => Promise<UserData | null>;
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
  googleClientId: process.env.VITE_GOOGLE_OAUTH_CLIENT_ID || "",
  signup: async () => null,
  signin: async () => null,
  signinGuest: async () => null,
  signinWithGoogle: async () => null,
  signout: async () => {},
  updateProfile: async () => {},
  updateLlmConfig: async () => {},
  saveUserType: async () => {},
  googleSignIn: async () => null,
  logout: () => {},
});

const UserProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<UserData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [enableUserAuth, setEnableUserAuth] = useState<boolean>(true);
  const [skipProjectPage, setSkipProjectPage] = useState<boolean>(false);
  const [allowGuest, setAllowGuest] = useState<boolean>(false);
  const [sharedGuestUsername, setSharedGuestUsername] =
    useState<string>("guest_shared");
  const [googleClientId, setGoogleClientId] = useState<string>(
    process.env.VITE_GOOGLE_OAUTH_CLIENT_ID || ""
  );

  const applyUser = useCallback((nextUser: UserData) => {
    setUser(nextUser);
    // The per-user node-pack store only responds once we carry a Bearer token.
    // Sync immediately so palette + `/node-types` match Nodes hub — do not rely
    // solely on ``window.curio`` indirection which can silently no-op.
    void refreshPackRegistry();
    return nextUser;
  }, []);

  const handleAuth = useCallback(
    (res: { user: UserData; token: string }) => {
      setToken(res.token);
      return applyUser(res.user);
    },
    [applyUser]
  );

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      setLoading(true);
      try {
        const cfg = await authApi.getPublicConfig().catch(() => {
          console.error(
            "[Curio] Could not reach backend at /api/config/public. " +
            "Is the backend running? Check terminal output."
          );
          return null;
        });
        const projectPageSkipped = Boolean(
          cfg?.skip_project_page ?? cfg?.curio_no_project ?? false
        );
        // ``enable_user_auth`` was removed from the public config: auth is
        // considered enabled unless the backend has explicitly opted out via
        // ``CURIO_NO_AUTH`` or the ``CURIO_NO_PROJECT`` shortcut.
        const authSkipped =
          Boolean(cfg?.curio_no_auth ?? false) || projectPageSkipped;
        const authEnabled = !authSkipped;
        const sharedGuestUsername = cfg?.shared_guest_username ?? "guest_shared";

        if (cancelled) return;

        setEnableUserAuth(authEnabled);
        setSkipProjectPage(projectPageSkipped);
        setAllowGuest(Boolean(authEnabled && cfg?.allow_guest_login));
        setSharedGuestUsername(sharedGuestUsername);
        if (cfg?.google_client_id) {
          setGoogleClientId(cfg.google_client_id);
        }

        const token = getToken();

        if (!authEnabled) {
          if (token) {
            try {
              const current = await authApi.getMe();
              if (
                !cancelled &&
                current.is_guest &&
                current.username === sharedGuestUsername
              ) {
                applyUser(current);
                return;
              }
            } catch {
              // fall through to shared auto guest bootstrap
            }
            clearToken();
            if (!cancelled) setUser(null);
          }

          const res = await authApi.signinAutoGuest();
          if (!cancelled) handleAuth(res);
          return;
        }

        if (!token) {
          // Share-link bootstrap: when an unauthenticated visitor lands on a
          // /dataflow/<uuid> URL and guest login is allowed, sign them in as
          // the shared guest so they can view the linked dataflow without
          // facing a login form.
          const onShareUrl =
            /\/dataflow\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.test(
              window.location.pathname
            );
          if (onShareUrl && cfg?.allow_guest_login) {
            try {
              const res = await authApi.signinGuest();
              if (!cancelled) handleAuth(res);
            } catch {
              if (!cancelled) setUser(null);
            }
            return;
          }
          if (!cancelled) setUser(null);
          return;
        }

        try {
          const current = await authApi.getMe();
          if (!cancelled) {
            applyUser(current);
          }
        } catch {
          clearToken();
          if (!cancelled) setUser(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    bootstrap();

    return () => {
      cancelled = true;
    };
  }, []);

  const signup = useCallback(
    async (data: {
      name: string;
      username: string;
      password: string;
      email?: string;
    }) => {
      setLoading(true);
      try {
        const res = await authApi.signup(data);
        return handleAuth(res);
      } finally {
        setLoading(false);
      }
    },
    [handleAuth]
  );

  const signin = useCallback(
    async (identifier: string, password: string) => {
      setLoading(true);
      try {
        const res = await authApi.signin({ identifier, password });
        return handleAuth(res);
      } finally {
        setLoading(false);
      }
    },
    [handleAuth]
  );

  const signinWithGoogle = useCallback(
    async (code: string) => {
      setLoading(true);
      try {
        const res = await authApi.signinGoogle(code);
        return handleAuth(res);
      } catch (e) {
        console.error(e);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [handleAuth]
  );

  const signinGuest = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authApi.signinGuest();
      return handleAuth(res);
    } catch (e) {
      console.error(e);
      return null;
    } finally {
      setLoading(false);
    }
  }, [handleAuth]);

  const signout = useCallback(async () => {
    if (!enableUserAuth) {
      return;
    }
    try {
      await authApi.signout();
    } catch {
      return;
    }
    clearToken();
    setUser(null);
  }, [enableUserAuth]);

  const updateProfile = useCallback(
    async (data: { name?: string; email?: string; type?: string }) => {
      const updated = await authApi.patchMe(data);
      setUser(updated);
    },
    []
  );

  const updateLlmConfig = useCallback(
    async (config: {
      apiType?: string;
      baseUrl?: string;
      apiKey?: string;
      model?: string;
    }) => {
      const updated = await authApi.patchMe({
        llm_api_type: config.apiType,
        llm_base_url: config.baseUrl,
        llm_api_key: config.apiKey,
        llm_model: config.model,
      });
      setUser(updated);
    },
    []
  );

  const saveUserType = useCallback(
    async (newType: "programmer" | "expert") => {
      await updateProfile({ type: newType });
    },
    [updateProfile]
  );

  return (
    <UserContext.Provider
      value={{
        user,
        loading,
        isAuthenticated: !!user,
        enableUserAuth,
        skipProjectPage,
        allowGuest,
        sharedGuestUsername,
        googleClientId,
        signup,
        signin,
        signinGuest,
        signinWithGoogle,
        signout,
        updateProfile,
        updateLlmConfig,
        saveUserType,
        googleSignIn: signinWithGoogle,
        logout: signout,
      }}
    >
      {loading ? <Loading /> : children}
    </UserContext.Provider>
  );
};

export const useUserContext = () => {
  const context = useContext(UserContext);
  if (!context) {
    throw new Error("useUserContext must be used within a UserProvider");
  }
  return context;
};

export default UserProvider;
