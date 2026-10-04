import { useUserContext } from "../../providers/UserProvider";

/**
 * Is this a guest under --deploy? Such a guest shares one account with every
 * visitor, so it saves nothing personal: API Settings shows it no key form,
 * and no button elsewhere opens one for it. Without --deploy the shared guest
 * is the one local user.
 */
export function useHostedGuest(): boolean {
  const { user, enableUserAuth } = useUserContext();
  return Boolean(user?.is_guest) && enableUserAuth;
}
