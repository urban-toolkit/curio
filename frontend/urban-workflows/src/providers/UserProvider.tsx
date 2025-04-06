import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import Cookies from "js-cookie";

import { Loading } from "../components/login/Loading";
import { useProvenanceContext } from "./ProvenanceProvider";

interface IUser {
  name: string;
  profile_image: string;
  type: "expert" | "programmer" | null;
}

interface UserProviderProps {
  user: IUser | null;
  googleSignIn: (googleCode: string) => Promise<IUser | null>;
  saveUserType: (newType: "programmer" | "expert") => Promise<void>;
  logout: () => void;
}

export const UserContext = createContext<UserProviderProps>({
  user: null,
  googleSignIn: async () => {
    return null;
  },
  saveUserType: async () => {},
  logout: () => {},
});

const UserProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<IUser | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const { addUser } = useProvenanceContext();

  const googleSignIn = useCallback(async (googleCode: string) => {
    setLoading(true);
    try {
      const response = await fetch(process.env.BACKEND_URL + "/signin", {
        method: "POST",
        body: JSON.stringify({
          token: googleCode,
        }),
        headers: {
          "Content-type": "application/json; charset=UTF-8",
        },
      });
      const json = await response.json();

      // write user to the provenance database
      addUser(json.user.name, json.user.type, "");

      setUser(json.user);
      Cookies.set("session_token", json.token);
      setLoading(false);

      return json.user;
    } catch (error) {
      setLoading(false);
      console.error(error);
    }
  }, []);

  const saveUserType = useCallback(async (type: "programmer" | "expert") => {
    setLoading(true);
    try {
      const response = await fetch(process.env.BACKEND_URL + "/saveUserType", {
        method: "POST",
        body: JSON.stringify({
          type,
        }),
        headers: {
          "Content-type": "application/json; charset=UTF-8",
          Authorization: Cookies.get("session_token") || "",
        },
      });
      const json = await response.json();
      setUser(json.user);
    } catch (e) {}

    setLoading(false);
  }, []);

  const logout = useCallback(() => {
    Cookies.remove("session_token");
    setUser(null);
  }, []);

  useEffect(() => {
    const sessionToken = Cookies.get("session_token");
    if (!sessionToken) return;

    setLoading(true);
    fetch(process.env.BACKEND_URL + "/getUser", {
      method: "GET",
      headers: {
        Authorization: sessionToken,
      },
    })
      .then((response) => response.json())
      .then((json) => {
        setUser(json.user);
      })
      .finally(() => setLoading(false));
  }, []);

  // TODO: implement loading layout
  return (
    <UserContext.Provider
      value={{
        user,
        googleSignIn,
        saveUserType,
        logout,
      }}
    >
      {loading && <Loading />}
      {children}
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
