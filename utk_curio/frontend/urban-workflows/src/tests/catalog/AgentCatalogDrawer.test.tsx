import React from "react";
import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";

jest.mock("../../api/agentsApi", () => ({
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

import { agentsApi } from "../../api/agentsApi";
import { AgentCatalogDrawer } from "../../components/agents/catalog/AgentCatalogDrawer";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

/** The ConfirmDialog ModalShell renders. `getByRole("dialog")` cannot be used:
 *  the drawer itself carries role="dialog" too, so the query is ambiguous
 *  whenever a confirmation is open. */
function confirmModal(): HTMLElement {
  const el = document.querySelector('[data-curio-modal-shell="true"]');
  if (!el) throw new Error("no confirmation dialog is open");
  return el as HTMLElement;
}

/** Clicks a card action and accepts the confirmation it now raises (#196,
 *  #197). The card button and the dialog's confirm can share a label, so the
 *  second click is scoped to the dialog. */
async function clickAndConfirm(cardAction: string | RegExp, confirmLabel: string) {
  fireEvent.click(screen.getByRole("button", { name: cardAction }));
  const modal = await waitFor(confirmModal);
  fireEvent.click(within(modal).getByRole("button", { name: confirmLabel }));
}

function card(id: string, over: Record<string, unknown> = {}) {
  return {
    id,
    version: "1.0.0",
    dirName: `${id}@1.0.0`,
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

beforeEach(() => {
  jest.clearAllMocks();
  api.catalog.mockResolvedValue({ agents: [card("agent.node-explainer")] } as any);
  api.listImports.mockResolvedValue({ agents: [card("agent.chat-agent", { scope: "imports", imported: true })] } as any);
  api.listProjectAgents.mockResolvedValue({ agents: [] } as any);
  api.installToProject.mockResolvedValue({ agents: [] } as any);
  api.uninstallFromProject.mockResolvedValue({ agents: [] } as any);
  api.publish.mockResolvedValue({ coord: "x", published: true } as any);
});

// AI Settings reads UserProvider, which reaches the package registry and
// through it vega (ESM, unloadable under jest). projectsPageChrome and
// projectsListScroll mock it for the same reason. What this file asserts is
// that the cog opens it - not what it contains.
jest.mock("../../components/AiSettingsModal", () => ({
  __esModule: true,
  default: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="ai-settings-modal">AI Settings</div> : null,
}));

describe("AgentCatalogDrawer", () => {
  it("is hidden (not accessible) when not presented", () => {
    // dev/43: the drawer stays mounted through the exit slide; while not
    // presented it is aria-hidden and pointer-inert, never abruptly removed.
    const { container } = render(
      <AgentCatalogDrawer presented={false} projectId="p1" pinned={false} onPinToggle={jest.fn()} />,
    );
    expect(screen.queryByRole("dialog", { name: "Agent Catalog" })).not.toBeInTheDocument();
    const root = container.querySelector("[data-curio-agent-catalog-drawer]");
    expect(root).toHaveAttribute("aria-hidden", "true");
  });

  it("renders the two tabs and the browse cards", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    expect(screen.getByText("Browse all")).toBeInTheDocument();
    expect(screen.getByText("In project")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Add to project" })).toBeInTheDocument();
  });

  it("offers only per-project actions, and never reads the account import list", async () => {
    // The drawer had a third scope, "My imports", listing the ACCOUNT's
    // imported definitions inside a per-dataflow panel. Its cards carried four
    // account-level controls - a publish pill, an Unpublish, "Remove from all
    // projects" and "Add to all projects" - none of which are about the
    // dataflow this drawer is open on.
    //
    // It was also the surface reporting built-ins like "Dataflow builder" as
    // the user's own imports, because its row button was the one thing in the
    // product that wrote them into the account list.
    //
    // All of it moved to the Agent Catalog PAGE, the surface that has no
    // project and can only speak about the account. This drawer adds straight
    // to the open project.
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.queryByText("My imports")).toBeNull();
    expect(api.listImports).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Remove from all projects" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add to all projects" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Unpublish$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  // ── issue 199 / 190: a never-saved dataflow ────────────────────────────────
  //
  // This used to assert the opposite - that Add is DISABLED without a project -
  // which is the bug both issues report. A dataflow that has not been saved is
  // `projectId === null`, and that is the ordinary state of one you just
  // created, so the drawer was unusable until you happened to save. Both peer
  // catalogs create the dataflow on the click instead: the Data drawer awaits
  // `ensureProjectId`, the Node drawer saves by hand. This one now does the
  // same, through the shared helper.

  it("Add to project stays enabled on a dataflow that was never saved", async () => {
    render(<AgentCatalogDrawer presented projectId={null} pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Add to project" })).toBeEnabled();
  });

  it("Remove from project stays enabled on a dataflow that was never saved", async () => {
    // The other branch of the same decision, and the half that stayed broken.
    // `inThisDataflow` counts an agent already in the ACCOUNT as present, so on
    // an unsaved dataflow that card renders Remove rather than Add - and Remove
    // was still gated on `hasProject`. The card then offered a disabled control
    // and nothing else, which is the dead end #190 and #199 describe.
    api.catalog.mockResolvedValue({
      agents: [card("agent.node-explainer", { imported: true })],
    } as any);
    render(<AgentCatalogDrawer presented projectId={null} pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Remove from project" })).toBeEnabled();
  });

  it("shows no unsaved-dataflow banner", async () => {
    // The banner is gone from all three catalogs. It only ever appeared on an
    // unsaved dataflow, so it read as a state the other two surfaces did not
    // have, and the add explains itself: the confirmation says what will
    // happen and the save indicator shows that it did.
    render(<AgentCatalogDrawer presented projectId={null} pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    expect(screen.queryByText(/isn.{0,6}t saved yet/i)).not.toBeInTheDocument();
  });

  it("saves the dataflow, then installs into the id that comes back", async () => {
    const onEnsureProject = jest.fn().mockResolvedValue("created-1");
    render(
      <AgentCatalogDrawer
        presented
        projectId={null}
        onEnsureProject={onEnsureProject}
        pinned={false}
        onPinToggle={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    await clickAndConfirm("Add to project", "Add to project");

    await waitFor(() => expect(onEnsureProject).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("created-1", "agent.node-explainer@1.0.0"),
    );
  });

  it("reports a failed save instead of silently adding nothing", async () => {
    // The old code answered `Promise.resolve()` when there was no project, so
    // `run` reported success for an add that never happened.
    const onEnsureProject = jest.fn().mockResolvedValue(null);
    render(
      <AgentCatalogDrawer
        presented
        projectId={null}
        onEnsureProject={onEnsureProject}
        pinned={false}
        onPinToggle={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    await clickAndConfirm("Add to project", "Add to project");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/nothing was added/i));
    expect(api.installToProject).not.toHaveBeenCalled();
  });

  it("shows the agent as added straight after the auto-save", async () => {
    // The refresh that follows an install must be scoped to the dataflow, or
    // `installedInProject` comes back false for everything and the agent you
    // just added still offers "Add to project". The prop cannot carry the new
    // id yet - the save is what created it - so the id has to be threaded
    // through from the action itself.
    api.catalog.mockImplementation((projectId?: string) =>
      Promise.resolve({
        agents: [card("agent.node-explainer", { installedInProject: Boolean(projectId) })],
      }) as any,
    );
    render(
      <AgentCatalogDrawer
        presented
        projectId={null}
        onEnsureProject={jest.fn().mockResolvedValue("created-1")}
        pinned={false}
        onPinToggle={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    await clickAndConfirm("Add to project", "Add to project");

    // The card offers nothing once the agent is in: there is no "Remove from
    // project" any more, because an agent reaches a dataflow by being in the
    // account and `save_project` seeds it into every one. So the tell that the
    // add landed is that Add is gone.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^Add to project/ })).toBeNull(),
    );
    expect(api.catalog).toHaveBeenLastCalledWith("created-1");
  });

  it("never publishes an unscoped listing over a scoped one", async () => {
    // The race this closes: a listing requested before the dataflow existed can
    // answer AFTER the one that knows about it. It cannot know
    // `installedInProject`, so publishing it silently un-marks every installed
    // agent - the same wrong screen as the bug above, by a slower route.
    let releaseUnscoped: (value: unknown) => void = () => {};
    const unscoped = new Promise((resolve) => {
      releaseUnscoped = resolve;
    });
    api.catalog.mockImplementation(((projectId?: string) => {
      const agents = [card("agent.node-explainer", { installedInProject: Boolean(projectId) })];
      // The unscoped call is held open until the scoped one has landed.
      return projectId ? Promise.resolve({ agents }) : unscoped.then(() => ({ agents }));
    }) as any);

    render(
      <AgentCatalogDrawer
        presented
        projectId={null}
        onEnsureProject={jest.fn().mockResolvedValue("created-1")}
        pinned={false}
        onPinToggle={jest.fn()}
      />,
    );
    // Let the held listing answer once, so there is a card to click.
    await act(async () => {
      releaseUnscoped(null);
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());

    await clickAndConfirm("Add to project", "Add to project");
    // The card offers nothing once the agent is in: there is no "Remove from
    // project" any more, because an agent reaches a dataflow by being in the
    // account and `save_project` seeds it into every one. So the tell that the
    // add landed is that Add is gone.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^Add to project/ })).toBeNull(),
    );

    // Any further unscoped answer must be dropped, not rendered.
    await act(async () => {
      releaseUnscoped(null);
      await Promise.resolve();
    });
    // The card offers nothing once the agent is in: there is no "Remove from
    // project" any more, because an agent reaches a dataflow by being in the
    // account and `save_project` seeds it into every one. Removing it from a
    // single dataflow put the catalog's "In all projects" in permanent
    // disagreement with that dataflow.
    expect(screen.queryByRole("button", { name: /^Add to project/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add to project" })).toBeNull();
  });

  it("uses the open dataflow directly when there is one", async () => {
    const onEnsureProject = jest.fn();
    render(
      <AgentCatalogDrawer
        presented
        projectId="p1"
        onEnsureProject={onEnsureProject}
        pinned={false}
        onPinToggle={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    await clickAndConfirm("Add to project", "Add to project");

    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0"),
    );
    expect(onEnsureProject).not.toHaveBeenCalled();
  });

  it("shows no Publish control on any card, publishable or not", async () => {
    // Publishing puts an agent into the catalog everyone on this Curio shares -
    // a decision about the agent, not about the dataflow this drawer is open on
    // - so it lives on the Agent Catalog page's detail drawer, gated there on
    // the same `publishable` flag.
    api.catalog.mockResolvedValue({
      agents: [
        card("agent.my-custom", { publishable: true }),
        card("agent.node-explainer", { publishable: false }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("my-custom")).toBeInTheDocument());
    expect(screen.queryAllByRole("button", { name: /^publish$/i })).toHaveLength(0);
    expect(api.publish).not.toHaveBeenCalled();
  });

  it("clicking Add to project calls the install endpoint", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    await clickAndConfirm("Add to project", "Add to project");
    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0"),
    );
  });

  it("discloses a missing required dependency on the card and the Add button", async () => {
    api.catalog.mockResolvedValue({
      agents: [
        card("agent.dataflow-builder", {
          name: "Dataflow Builder",
          category: "canvas",
          requiresAgents: [{
            id: "agent.node-content-builder", name: "Node Content Builder",
            coord: "agent.node-content-builder@1.0.0", visible: true, installedInProject: false,
          }],
        }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Dataflow Builder")).toBeInTheDocument());
    expect(screen.getByText(/Requires:/)).toBeInTheDocument();
    expect(screen.getByText("Node Content Builder (not installed)")).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: "Add to project (+1 required)" });
    expect(btn).toHaveAttribute("title", "Also adds Node Content Builder (required)");
    await clickAndConfirm("Add to project (+1 required)", "Add to project");
    await waitFor(() =>
      expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.dataflow-builder@1.0.0"),
    );
  });

  it("a satisfied dependency renders a check and a plain Add to project", async () => {
    api.catalog.mockResolvedValue({
      agents: [
        card("agent.dataflow-builder", {
          name: "Dataflow Builder",
          requiresAgents: [{
            id: "agent.node-content-builder", name: "Node Content Builder",
            coord: "agent.node-content-builder@1.0.0", visible: true, installedInProject: true,
          }],
        }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Dataflow Builder")).toBeInTheDocument());
    expect(screen.getByText("Node Content Builder ✓")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to project" })).toBeInTheDocument();
  });

  // The "409 from uninstalling a required dependency" case left with the
  // control: this drawer has no uninstall any more. The backend guard is intact
  // and covered where it lives, in
  // test_agents/test_routes.py::test_uninstalling_a_required_dependency_409s_naming_the_dependent.


  it("header carries the Pin and a Close, like the other catalog drawers", async () => {
    const onPinToggle = jest.fn();
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={onPinToggle} />);
    const pin = screen.getByRole("button", { name: "Pin drawer open" });
    expect(pin).toHaveAttribute("aria-pressed", "false");
    // The drawer used to omit this, on the grounds that the other catalog
    // drawers dismiss through the scrim. They do not - both render a close
    // button from the shared DrawerHeader - so a dialog with no in-dialog
    // dismissal was the odd one out, and the harder one to leave by keyboard.
    const dialog = screen.getByRole("dialog", { name: "Agent Catalog" });
    expect(
      within(dialog).getByRole("button", { name: "Close Agent Catalog drawer" }),
    ).toBeInTheDocument();
    fireEvent.click(pin);
    expect(onPinToggle).toHaveBeenCalledTimes(1);
  });

  it("a pinned roster header exposes Unpin", () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned onPinToggle={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Unpin drawer" })).toHaveAttribute("aria-pressed", "true");
  });

  it("no card offers a per-agent settings cog, in any scope", async () => {
    // There used to be one per In-dataflow card, opening a run/spend policy
    // editor. Curio no longer caps either, so the editor and its three scopes
    // are gone and a card's actions are add, remove, publish.
    api.listProjectAgents = jest.fn().mockResolvedValue({
      agents: [card("agent.chat-agent", { scope: "installed", installedInProject: true })],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    for (const tab of ["In project"]) {
      fireEvent.click(screen.getByText(tab));
      await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
      // Scoped to the card: the drawer header keeps its own AI Settings
      // button, which is the provider, not a per-agent policy.
      const row = screen.getByText("chat-agent").closest("article")!;
      expect(
        within(row).queryByRole("button", { name: /settings/i }),
      ).not.toBeInTheDocument();
    }
  });

  it("the header cog opens AI Settings, which owns the account scope", async () => {
    // The account policy moved into AI Settings, on its "Agent limits" tab,
    // beside the provider those limits apply to. The drawer opens that one
    // surface instead of a second modal holding half the answer. AI Settings
    // is loaded lazily here (a static import would pull UserProvider, the
    // package registry and vega into every canvas), so the assertion waits.
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /ai settings/i }));
    await waitFor(() =>
      expect(screen.getByTestId("ai-settings-modal")).toBeInTheDocument(),
    );
  });

  it("the footer Import agent button opens the upload modal", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Import agent" }));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: "Import agent package" })).toBeInTheDocument(),
    );
  });
});

describe("AgentCatalogDrawer tab transitions + state sync (memo dev/47)", () => {
  it("a previously visited tab renders its cache instantly — no Loading reset", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("In project"));
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByText("Browse all"));
    // Cached rows are visible immediately; no Loading… flash, no blanking.
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).toBeNull();
  });

  it("an installed agent offers no action at all, not even Add", async () => {
    api.listProjectAgents.mockResolvedValue({
      agents: [
        card("agent.node-content-builder", {
          scope: "installed",
          installedInProject: true,
        }),
      ],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.click(screen.getByText("In project"));
    await waitFor(() => expect(screen.getByText("node-content-builder")).toBeInTheDocument());
    // The card offers nothing once the agent is in: there is no "Remove from
    // project" any more, because an agent reaches a dataflow by being in the
    // account and `save_project` seeds it into every one. Removing it from a
    // single dataflow put the catalog's "In all projects" in permanent
    // disagreement with that dataflow.
    expect(screen.queryByRole("button", { name: /^Add to project/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add to project" })).toBeNull();
  });

  it("the project scope is fetched with the open project's id (lockfile truth)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("In project"));
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalledWith("p1"));
  });

  it("a lifecycle action refreshes every scope so all tabs agree", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    api.catalog.mockClear();
    api.listProjectAgents.mockClear();
    api.listProjectAgents.mockClear();
    await clickAndConfirm("Add to project", "Add to project");
    await waitFor(() => expect(api.installToProject).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0"));
    await waitFor(() => {
      expect(api.catalog).toHaveBeenCalled();
      expect(api.listProjectAgents).toHaveBeenCalled();
      expect(api.listProjectAgents).toHaveBeenCalled();
    });
  });

  it("a refresh error keeps the cached rows (banner over content)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    api.listProjectAgents.mockRejectedValue(new Error("network down"));
    fireEvent.click(screen.getByText("In project"));
    // First visit fails → error banner; switch back: Global cache intact.
    await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Browse all"));
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
  });

  it("search filters the visible rows and clearing restores them (dev/68)", async () => {
    api.catalog.mockResolvedValue({
      agents: [card("agent.node-explainer"), card("agent.dataset-finder", { category: "data" })],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    const input = screen.getByPlaceholderText("Search agents, publishers, tags…");
    fireEvent.change(input, { target: { value: "explainer" } });
    expect(screen.getByText("node-explainer")).toBeInTheDocument();
    expect(screen.queryByText("dataset-finder")).toBeNull();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByText("dataset-finder")).toBeInTheDocument();
  });

  it("a no-match query shows the search-specific empty message (dev/68)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Search agents, publishers, tags…"), {
      target: { value: "zzz-no-such-agent" },
    });
    expect(
      screen.getByText("No agents match the current filters."),
    ).toBeInTheDocument();
  });

  it('"Sort: Name" reorders rows alphabetically; "Sort: New" keeps roster order (dev/68)', async () => {
    api.catalog.mockResolvedValue({
      agents: [card("agent.zeta-agent"), card("agent.alpha-agent")],
    } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("zeta-agent")).toBeInTheDocument());
    const names = () =>
      screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    // Default "new" = the server roster order.
    expect(names()).toEqual(["zeta-agent", "alpha-agent"]);
    fireEvent.change(screen.getByRole("combobox", { name: "Sort agents" }), {
      target: { value: "name" },
    });
    expect(names()).toEqual(["alpha-agent", "zeta-agent"]);
  });

  it("the search query persists across scope tab switches (dev/68)", async () => {
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    const input = screen.getByPlaceholderText("Search agents, publishers, tags…");
    fireEvent.change(input, { target: { value: "chat" } });
    fireEvent.click(screen.getByText("In project"));
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    expect(input).toHaveValue("chat");
  });

  it("each row leads with a per-category avatar, tint and glyph (dev/68)", async () => {
    api.catalog.mockResolvedValue({
      agents: [card("agent.node-explainer"), card("agent.dataset-finder", { category: "data" })],
    } as any);
    const { container } = render(
      <AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />,
    );
    await waitFor(() => expect(screen.getByText("node-explainer")).toBeInTheDocument());
    const avatars = container.querySelectorAll(".cardAvatar");
    expect(avatars).toHaveLength(2);
    // Each category keeps its own key. These two used to be `avatar_package`
    // and `avatar_data`, because `node` folded onto the package neutral - the
    // collapse that left three quarters of the roster the same grey.
    expect(avatars[0].className).toContain("avatar_node");
    expect(avatars[1].className).toContain("avatar_data");
    // And the glyph differs too, which the tint alone never achieved: every
    // card drew the same robot.
    const glyphs = [...avatars].map(
      (el) => el.querySelector("svg")?.getAttribute("data-icon"),
    );
    expect(glyphs).toEqual(["circle-nodes", "database"]);
    // No longer decorative: the square opens the agent's details, so it is a
    // real button with a real name, and the GLYPH inside it is what is hidden.
    avatars.forEach((el) => {
      expect(el.tagName).toBe("BUTTON");
      expect(el).toHaveAttribute("aria-label", expect.stringContaining("details"));
      expect(el.querySelector("svg")).toHaveAttribute("aria-hidden");
    });
  });

  it("out-of-order responses are dropped (race guard)", async () => {
    let resolveSlow: (v: unknown) => void = () => undefined;
    const slow = new Promise((r) => {
      resolveSlow = r;
    });
    // First Global fetch hangs; the revisit's fetch resolves fresh data first.
    api.catalog
      .mockImplementationOnce(() => slow as any)
      .mockResolvedValue({ agents: [card("agent.fresh-agent")] } as any);
    render(<AgentCatalogDrawer presented projectId="p1" pinned={false} onPinToggle={jest.fn()} />);
    fireEvent.click(screen.getByText("In project"));
    await waitFor(() => expect(api.listProjectAgents).toHaveBeenCalled());
    fireEvent.click(screen.getByText("Browse all"));
    await waitFor(() => expect(screen.getByText("fresh-agent")).toBeInTheDocument());
    // The slow FIRST response lands late: it must be dropped, not repainted.
    await act(async () => {
      resolveSlow({ agents: [card("agent.stale-agent")] });
    });
    expect(screen.queryByText("stale-agent")).toBeNull();
    expect(screen.getByText("fresh-agent")).toBeInTheDocument();
  });
});
