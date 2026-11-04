import { useEffect } from "react";

import type { PackageKind } from "./types";

/**
 * Drop-to-Add: a card dropped on the canvas makes its package's node. When
 * the dataflow has not added the package, the drop asks the open catalog
 * drawer of the package's kind to run that drawer's own Add (the review, then
 * the install of the package and its libraries), and the node is made once
 * the package is added. A hosted guest's drop is refused before any of it:
 * guests never install. On the owner's dataflow, an invited editor's drop
 * makes the node at once and asks the owner to add the package
 * (`useAskForPackage`), whose review she applies.
 */

/** What a dropped card does. */
export type PackageDropAction = "create" | "refuse" | "add" | "ask";

/** Make the node when the dataflow has the package; otherwise refuse a
 *  hosted guest, make it and ask the owner on an invited editor's canvas
 *  (*asksTheOwner*), and ask anyone else to add it first. */
export function packageDropAction(
  { inDataflow, hostedGuest, asksTheOwner = false }: { inDataflow: boolean; hostedGuest: boolean; asksTheOwner?: boolean },
): PackageDropAction {
  if (inDataflow) return "create";
  if (hostedGuest) return "refuse";
  return asksTheOwner ? "ask" : "add";
}

/** What a hosted guest is told when a drop would add a package. */
export function guestAddRefusal(name: string): string {
  return `Adding ${name} is not available for guest users, because every guest shares one account. Sign in with an account to add it.`;
}

export interface PackageAddRequest {
  dirName: string;
  kind: PackageKind;
  /** Runs once the package is added to the dataflow; never after a cancelled review or a failed install. */
  onAdded: () => void;
}

export const PACKAGE_ADD_REQUEST_EVENT = "curio:package-add-request";

/** Ask the open drawer of `request.kind` to add the package; true when one took it. */
export function requestPackageAdd(request: PackageAddRequest): boolean {
  if (typeof window === "undefined") return false;
  const event = new CustomEvent<PackageAddRequest>(PACKAGE_ADD_REQUEST_EVENT, {
    detail: request,
    cancelable: true,
  });
  return !window.dispatchEvent(event);
}

/** A drawer's side: *take* answers whether it took a request, while *enabled*. */
export function usePackageAddRequests(
  take: (request: PackageAddRequest) => boolean,
  enabled = true,
): void {
  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;
    const onRequest = (event: Event) => {
      const request = (event as CustomEvent<PackageAddRequest>).detail;
      if (!event.defaultPrevented && request && take(request)) event.preventDefault();
    };
    window.addEventListener(PACKAGE_ADD_REQUEST_EVENT, onRequest);
    return () => window.removeEventListener(PACKAGE_ADD_REQUEST_EVENT, onRequest);
  }, [take, enabled]);
}
