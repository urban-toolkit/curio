import React from "react";
import { useUserContext } from "../providers/UserProvider";
import { Loading } from "./login/Loading";
import SignIn from "../pages/auth/SignIn";

export const RequireAuth: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { user, loading, enableUserAuth } = useUserContext();

  if (loading) return <Loading />;
  /* this had a bug: when user auth is disabled (enableUserAuth = false) and there's no logged-in user, it
  showed <Loading /> indefinitely instead of rendering the app. The app would appear stuck loading forever.

  This fix moves the enableUserAuth check before the !user check — so when auth is disabled, the children are
  rendered immediately regardless of whether a user is logged in, which should the correct behavior for an
  auth-disabled deployment.
  TODO: can be removed if earlier behaviour is fine.
   */
  if (!enableUserAuth) return <>{children}</>;
  if (!user) return <SignIn />;

  return <>{children}</>;
};
