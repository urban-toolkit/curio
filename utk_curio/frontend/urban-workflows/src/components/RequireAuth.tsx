import React from "react";
import { useUserContext } from "../providers/UserProvider";
import { Loading } from "./login/Loading";
import SignIn from "../pages/auth/SignIn";

export const RequireAuth: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { user, loading, enableUserAuth } = useUserContext();

  if (loading) return <Loading />;
  if (!user) {
    if (!enableUserAuth) return <Loading />;
    return <SignIn />;
  }

  return <>{children}</>;
};
