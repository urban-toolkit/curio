import { useUserContext } from "../../providers/userContext";
import type { UserData } from "../../utils/authApi";

/**
 * Is this a guest under --deploy? Such a guest shares one account with every
 * visitor, so it saves nothing personal: API Settings shows it no key form,
 * and no button elsewhere opens one for it. Without --deploy the shared guest
 * is the one local user.
 */
export function isHostedGuest(user: UserData | null, enableUserAuth: boolean): boolean {
  return Boolean(user?.is_guest) && enableUserAuth;
}

/** What a hosted guest is told where a key would be saved. */
export const HOSTED_GUEST_KEYS_NOTE = "Personal keys cannot be saved on a shared guest account.";

/** `isHostedGuest` for the signed-in user. */
export function useHostedGuest(): boolean {
  const { user, enableUserAuth } = useUserContext();
  return isHostedGuest(user, enableUserAuth);
}
