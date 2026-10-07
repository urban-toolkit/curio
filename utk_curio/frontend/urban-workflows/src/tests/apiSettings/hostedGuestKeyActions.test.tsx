import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

// UserProvider imports refreshPackageRegistry, which drags in the registry ->
// adapters chain that will not load on its own. Same stub the other suites
// that touch UserContext use.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

import { UserContext } from "../../providers/UserProvider";
import type { UserData } from "../../utils/authApi";
import type { AgentRemedy } from "../../services/agents";
import { AddKeyAction } from "../../components/connectionKeys/AddKeyAction";
import { SolveFeedback } from "../../components/agents/attach/builderStrip/SolveFeedback";
import { CredentialHint } from "../../components/editing/CredentialHint";
import { subscribeApiSettingsRequests } from "../../components/apiSettings/apiSettingsRequest";
import { HOSTED_GUEST_KEYS_NOTE } from "../../components/apiSettings/useHostedGuest";

/**
 * A guest on a Curio with sign-in (a hosted guest, under --deploy) cannot save
 * a key for node code: the server refuses it and API Settings shows that guest
 * no form. So the two buttons that open that form, "Add key for <host>" and
 * the code editor's "Save as API key", are not offered to a hosted guest. The
 * local guest (sign-in off) and a signed-in user still get both. The code
 * editor's hint gives a hosted guest advice it can follow: the note API
 * Settings shows it, and signing in with its own account.
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

const MISSING_KEY: AgentRemedy = { kind: "connection-key", host: "api.census.gov", suggestedName: "census" };
const SAVED_KEY: AgentRemedy = { kind: "use-connection-key", host: "api.census.gov", name: "census" };

function renderAs(value: UserContextValue, ui: React.ReactElement) {
  return render(<UserContext.Provider value={value}>{ui}</UserContext.Provider>);
}

const addKey = () => screen.queryByRole("button", { name: "Add key for api.census.gov" });
const saveAsKey = () => screen.queryByRole("button", { name: "Save this key in API Settings" });

describe("Add key for <host>", () => {
  it("is not offered to a hosted guest", () => {
    renderAs(HOSTED_GUEST, <AddKeyAction remedy={MISSING_KEY} />);
    expect(addKey()).toBeNull();
  });

  it("is not offered to a hosted guest in the Solve strip, which shows no empty key group", () => {
    renderAs(
      HOSTED_GUEST,
      <SolveFeedback reasons={["needs a key"]} notices={[]} remedies={[MISSING_KEY]} selectionRemedies={[]} />,
    );
    expect(screen.getByText("needs a key")).toBeInTheDocument();
    expect(addKey()).toBeNull();
    expect(screen.queryByRole("group", { name: "Missing connection keys" })).toBeNull();
  });

  it.each([
    ["the local guest", LOCAL_GUEST],
    ["a signed-in user", SIGNED_IN_USER],
  ])("is offered to %s and asks for the settings form", (_who, value) => {
    const seen: unknown[] = [];
    const off = subscribeApiSettingsRequests((f) => seen.push(f));
    try {
      renderAs(value, <AddKeyAction remedy={MISSING_KEY} />);
      fireEvent.click(addKey()!);
      expect(seen).toEqual([{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }]);
    } finally {
      off();
    }
  });

  it.each([
    ["the local guest", LOCAL_GUEST],
    ["a signed-in user", SIGNED_IN_USER],
  ])("is offered to %s in the Solve strip", (_who, value) => {
    renderAs(
      value,
      <SolveFeedback reasons={[]} notices={[]} remedies={[MISSING_KEY]} selectionRemedies={[]} />,
    );
    expect(screen.getByRole("group", { name: "Missing connection keys" })).toContainElement(addKey());
  });

  it("a saved key that was not used is still a sentence for a signed-in user", () => {
    renderAs(SIGNED_IN_USER, <AddKeyAction remedy={SAVED_KEY} />);
    expect(screen.getByText(/A connection key "census" is saved for api.census.gov/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("the code editor's Save as API key", () => {
  const FINDINGS = [{ name: "api_key", line: 3 }];

  it("is not offered to a hosted guest, who still gets the hint and Dismiss", () => {
    renderAs(
      HOSTED_GUEST,
      <CredentialHint findings={FINDINGS} host="api.census.gov" onDismiss={jest.fn()} />,
    );
    expect(screen.getByTestId("credential-hint")).toHaveTextContent("Line 3 looks like an API key.");
    expect(screen.getByRole("button", { name: "Dismiss this hint" })).toBeInTheDocument();
    expect(saveAsKey()).toBeNull();
  });

  it.each([
    ["the local guest", LOCAL_GUEST],
    ["a signed-in user", SIGNED_IN_USER],
  ])("is offered to %s and asks for the settings form", (_who, value) => {
    const seen: unknown[] = [];
    const off = subscribeApiSettingsRequests((f) => seen.push(f));
    try {
      renderAs(value, <CredentialHint findings={FINDINGS} host="api.census.gov" onDismiss={jest.fn()} />);
      fireEvent.click(saveAsKey()!);
      expect(seen).toEqual([{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }]);
    } finally {
      off();
    }
  });
});

describe("the advice in the code editor's key hint", () => {
  const FINDINGS = [{ name: "api_key", line: 3 }];
  const hint = () => screen.getByTestId("credential-hint");

  it("tells a hosted guest what it can do, not to save the key in API Settings", () => {
    renderAs(HOSTED_GUEST, <CredentialHint findings={FINDINGS} host="api.census.gov" onDismiss={jest.fn()} />);
    // The server refuses that save for a hosted guest, and resolves no
    // curio_secret name for it either.
    expect(hint()).not.toHaveTextContent("Save it in API Settings and write");
    expect(hint()).not.toHaveTextContent("curio_secret");
    expect(hint()).toHaveTextContent(
      "Line 3 looks like an API key. Keys in node code are saved with the dataflow and shared with it. " +
        `${HOSTED_GUEST_KEYS_NOTE} Sign in with your own account to save it in API Settings.`,
    );
  });

  it.each([
    ["the local guest", LOCAL_GUEST],
    ["a signed-in user", SIGNED_IN_USER],
  ])("tells %s to save the key in API Settings and read it by name", (_who, value) => {
    renderAs(value, <CredentialHint findings={FINDINGS} host="api.census.gov" onDismiss={jest.fn()} />);
    expect(hint()).toHaveTextContent(
      "Line 3 looks like an API key. Keys in node code are saved with the dataflow and shared with it. " +
        'Save it in API Settings and write api_key = curio_secret("<name>") instead.',
    );
    expect(hint()).not.toHaveTextContent(HOSTED_GUEST_KEYS_NOTE);
  });
});
