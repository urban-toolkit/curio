import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";

// UserProvider imports refreshPackageRegistry, which drags in the registry ->
// adapters chain that will not load on its own. Same stub the other suites
// that touch UserContext use.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

import { UserContext } from "../../providers/UserProvider";
import type { UserData } from "../../utils/authApi";
import type { DiscoverySourceRow } from "../../services/discoveryCatalog";
import { DiscoverySourceDetailModal } from "../../pages/discovery/DiscoverySourceDetailModal";
import { DiscoveryCatalogBrowseDrawer } from "../../pages/discovery/DiscoveryCatalogBrowseDrawer";
import {
  API_SETTINGS_EVENT,
  type ApiSettingsFocus,
} from "../../components/apiSettings/apiSettingsRequest";

/**
 * A source that sends a key offers "Add yours in API Settings" in its Access
 * list, in the drawer and in the details view. A guest on a Curio with sign-in
 * (a hosted guest, under --deploy) cannot save a data source key, and API
 * Settings lists no data source keys for that guest, so the button is not
 * offered to it: the Access list keeps the Credential line and "How to get
 * one", and says once that a guest cannot save a key. The local guest (sign-in
 * off) and a signed-in user still get the button.
 */

type UserContextValue = React.ContextType<typeof UserContext>;

function userContext(user: UserData, enableUserAuth: boolean): UserContextValue {
  return {
    user,
    loading: false,
    isAuthenticated: true,
    enableUserAuth,
    skipProjectPage: false,
    allowGuest: true,
    sharedGuestUsername: "guest_shared",
    isSharedGuest: user.is_guest && user.username === "guest_shared",
    signup: async () => null,
    signin: async () => null,
    signinGuest: async () => null,
    signout: async () => {},
    updateProfile: async () => {},
    updateTokens: async () => {},
    saveUserType: async () => {},
    logout: () => {},
  };
}

const GUEST: UserData = {
  id: 1,
  username: "guest_shared",
  name: "Guest",
  email: null,
  profile_image: null,
  type: null,
  is_guest: true,
};
const SIGNED_IN: UserData = { ...GUEST, id: 2, username: "ada", name: "Ada", is_guest: false };

const HOSTED_GUEST = userContext(GUEST, true);
const LOCAL_GUEST = userContext(GUEST, false);
const SIGNED_IN_USER = userContext(SIGNED_IN, true);

const GUEST_NOTE = "Personal keys cannot be saved on a shared guest account.";

const SOURCE = {
  sourceId: "source.a.portal",
  dirName: "source.a.portal@1",
  name: "Alpha Portal",
  publisher: "City of Alpha",
  provider: "socrata",
  kind: "portal",
  description: null,
  baseUrl: null,
  homepage: null,
  license: null,
  iconUrl: null,
  tags: [],
  capabilities: { search: true, formats: ["csv"], maxDownloadBytes: 1024 * 1024 },
  auth: {
    mode: "optional-token",
    required: false,
    usesToken: true,
    secretId: "socrata.app-token",
    present: false,
    helpUrl: "https://example.org/app-tokens",
  },
} as unknown as DiscoverySourceRow;

const VIEWS: Array<[string, (onClose: () => void) => React.ReactElement]> = [
  [
    "details view",
    (onClose) => <DiscoverySourceDetailModal source={SOURCE} onBrowse={jest.fn()} onClose={onClose} />,
  ],
  [
    "drawer",
    (onClose) => (
      <DiscoveryCatalogBrowseDrawer source={SOURCE} onBrowse={jest.fn()} onViewDetails={jest.fn()} onClose={onClose} />
    ),
  ],
];

function renderAs(value: UserContextValue, ui: React.ReactElement) {
  return render(<UserContext.Provider value={value}>{ui}</UserContext.Provider>);
}

/** The Access list: the one list holding the Credential line. */
function accessList(): HTMLElement {
  const credential = screen.getByText("socrata.app-token");
  const list = credential.closest("ul");
  if (!list) throw new Error("the Credential line is not in a list");
  return list as HTMLElement;
}

const addKey = () => screen.queryByRole("button", { name: /in API Settings/ });

describe.each(VIEWS)("a source's Access list, in the %s", (_view, view) => {
  it("offers a hosted guest no API Settings button, keeping the Credential line and How to get one", () => {
    renderAs(HOSTED_GUEST, view(jest.fn()));
    const access = accessList();
    expect(access).toHaveTextContent("Credential: socrata.app-token (not set)");
    expect(within(access).getByRole("link", { name: /How to get one/ })).toHaveAttribute(
      "href",
      "https://example.org/app-tokens",
    );
    expect(addKey()).toBeNull();
    expect(within(access).getAllByText(GUEST_NOTE, { exact: false })).toHaveLength(1);
  });

  it.each([
    ["the local guest", LOCAL_GUEST],
    ["a signed-in user", SIGNED_IN_USER],
  ])("offers %s Add yours in API Settings, which asks for that key's row", (_who, value) => {
    const seen: ApiSettingsFocus[] = [];
    const listener = (event: Event) => seen.push((event as CustomEvent<ApiSettingsFocus>).detail);
    window.addEventListener(API_SETTINGS_EVENT, listener);
    try {
      renderAs(value, view(jest.fn()));
      expect(accessList()).not.toHaveTextContent(GUEST_NOTE);
      fireEvent.click(screen.getByRole("button", { name: "Add yours in API Settings" }));
    } finally {
      window.removeEventListener(API_SETTINGS_EVENT, listener);
    }
    expect(seen).toEqual([{ section: "source-key", slot: "socrata.app-token" }]);
  });
});
