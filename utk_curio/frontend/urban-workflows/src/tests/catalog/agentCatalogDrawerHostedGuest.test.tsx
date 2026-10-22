/**
 * The Agent Catalog drawer's Add and Remove on a dataflow a hosted guest never
 * saved (`isHostedGuest`: a guest on a Curio started with --deploy). Both act
 * on a saved dataflow, and such a guest cannot save one, so the drawer tells
 * it to sign in, in place of "Couldn't save this dataflow, so nothing was
 * added to it.", which talks about a save it cannot make. On a dataflow it
 * has, the drawer acts on it as before; the local shared guest and a
 * signed-in account keep today's behavior.
 *
 * The harness is AgentCatalogDrawer.test.tsx's.
 */
import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    catalog: jest.fn(),
    listImports: jest.fn(),
    listProjectAgents: jest.fn(),
    import: jest.fn(),
    removeImport: jest.fn(),
    installToProject: jest.fn(),
    uninstallFromProject: jest.fn(),
    publish: jest.fn(),
    unpublish: jest.fn(),
    uploadImport: jest.fn(),
  },
}));

const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

import { agentsApi } from "../../services/agents";
import { AgentCatalogDrawer } from "../../components/agents/catalog/AgentCatalogDrawer";
import { UserContext } from "../../providers/userContext";
import type { UserData } from "../../utils/authApi";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

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

/** The ConfirmDialog ModalShell renders (see AgentCatalogDrawer.test.tsx). */
function confirmModal(): HTMLElement {
  const el = document.querySelector('[data-curio-modal-shell="true"]');
  if (!el) throw new Error("no confirmation dialog is open");
  return el as HTMLElement;
}

/** Clicks a card action and accepts the confirmation it raises (#196, #197). */
async function clickAndConfirm(cardAction: string, confirmLabel: string) {
  fireEvent.click(screen.getByRole("button", { name: cardAction }));
  const modal = await waitFor(confirmModal);
  fireEvent.click(within(modal).getByRole("button", { name: confirmLabel }));
}

function card(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    version: "1.0.0",
    dirName: `${id}@1`,
    name: id.replace("agent.", ""),
    category: "node",
    purpose: "does a thing",
    capabilities: ["node.explain"],
    hooks: ["node"],
    provenance: { publisher: "curio", trust: "built-in" },
    imported: false,
    installedInProject: false,
    published: false,
    publishable: false,
    requiresAgents: [],
    scope: "browse",
    ...over,
  };
}

function renderDrawerAs(
  value: UserContextValue,
  projectId: string | null,
  onEnsureProject: () => Promise<string | null>,
) {
  return render(
    <UserContext.Provider value={value}>
      <AgentCatalogDrawer
        presented
        projectId={projectId}
        onEnsureProject={onEnsureProject}
        pinned={false}
        onPinToggle={jest.fn()}
      />
    </UserContext.Provider>,
  );
}

/** An agent the account already has, which a never-saved dataflow shows with Remove. */
function anAgentTheAccountHas() {
  api.catalog.mockResolvedValue({ agents: [card("agent.test.my-explainer", { imported: true })] } as any);
}

beforeEach(() => {
  jest.clearAllMocks();
  api.catalog.mockResolvedValue({ agents: [card("agent.test.my-explainer")] } as any);
  api.listImports.mockResolvedValue({ agents: [] } as any);
  api.listProjectAgents.mockResolvedValue({ agents: [] } as any);
  api.installToProject.mockResolvedValue({ agents: [] } as any);
  api.uninstallFromProject.mockResolvedValue({ agents: [] } as any);
});

describe("a hosted guest, on a dataflow it never saved", () => {
  // No id comes back for it, since a guest's save is skipped.
  const neverSaved = () => jest.fn().mockResolvedValue(null);

  it("is told to sign in when it adds an agent, and nothing is added", async () => {
    renderDrawerAs(HOSTED_GUEST, null, neverSaved());
    await waitFor(() => expect(screen.getByText("my-explainer")).toBeInTheDocument());

    await clickAndConfirm("Add to project", "Add to project");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Sign in to add agents."));
    expect(screen.getByRole("alert")).not.toHaveTextContent(/save/i);
    expect(api.installToProject).not.toHaveBeenCalled();
  });

  it("is told to sign in when it removes an agent, and nothing is removed", async () => {
    anAgentTheAccountHas();
    renderDrawerAs(HOSTED_GUEST, null, neverSaved());
    await waitFor(() => expect(screen.getByText("my-explainer")).toBeInTheDocument());

    await clickAndConfirm("Remove from project", "Remove");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Sign in to remove agents."));
    expect(api.uninstallFromProject).not.toHaveBeenCalled();
  });
});

describe("a hosted guest, on a dataflow it has", () => {
  it("adds an agent to it, as before", async () => {
    const onEnsureProject = jest.fn();
    renderDrawerAs(HOSTED_GUEST, "p1", onEnsureProject);
    await waitFor(() => expect(screen.getByText("my-explainer")).toBeInTheDocument());

    await clickAndConfirm("Add to project", "Add to project");

    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.test.my-explainer@1"),
    );
    expect(onEnsureProject).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe.each([
  ["the local shared guest", LOCAL_GUEST],
  ["a signed-in account", SIGNED_IN_USER],
])("%s, on a dataflow never saved", (_who, value) => {
  it("adds an agent once the save has created the dataflow", async () => {
    const onEnsureProject = jest.fn().mockResolvedValue("created-1");
    renderDrawerAs(value, null, onEnsureProject);
    await waitFor(() => expect(screen.getByText("my-explainer")).toBeInTheDocument());

    await clickAndConfirm("Add to project", "Add to project");

    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("created-1", "agent.test.my-explainer@1"),
    );
  });

  it("is told the save failed, not to sign in, when it could not be saved", async () => {
    renderDrawerAs(value, null, jest.fn().mockResolvedValue(null));
    await waitFor(() => expect(screen.getByText("my-explainer")).toBeInTheDocument());

    await clickAndConfirm("Add to project", "Add to project");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/nothing was added/i));
    expect(screen.getByRole("alert")).not.toHaveTextContent(/sign in/i);
    expect(api.installToProject).not.toHaveBeenCalled();
  });
});
