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

/**
 * What a hosted guest is told when it does what only an account does: save a
 * dataflow, or change what every guest shares, such as the packages and the
 * Data Catalog of the account they all sign in to. *action* names what it
 * did, as in "publish datasets".
 */
export function hostedGuestSignInNote(action: string): string {
  return `Sign in to ${action}.`;
}

/** `isHostedGuest` for the signed-in user. */
export function useHostedGuest(): boolean {
  const { user, enableUserAuth } = useUserContext();
  return isHostedGuest(user, enableUserAuth);
}
