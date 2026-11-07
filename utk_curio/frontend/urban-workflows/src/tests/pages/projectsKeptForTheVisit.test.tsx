/**
 * A hosted guest's gallery: the dataflows its File > New made come first, as
 * the server lists them (`kept_for_visit`), each marked Kept for this visit,
 * with the one Curio tooltip saying only an account saves a dataflow. The
 * server drops them when it starts again, so neither the drawer nor the
 * right-click menu offers to delete one. A hosted guest saves no dataflow, so
 * its Duplicate, of either kind of card, says to sign in before anything is
 * sent. The harness is projectsPageChrome.test.tsx's.
 */
import React from "react";
import { render, act, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { getAllByTooltip, queryAllByTooltip } from "../_support/tooltips";

const mockList = jest.fn();
const mockDuplicate = jest.fn();
const mockShowToast = jest.fn();
/** A guest with sign-in on: a hosted guest, unless a test signs in an account. */
const GUEST = { name: "Guest", is_guest: true };
let mockUser: { name: string; is_guest: boolean } = GUEST;

function mockSignedIn() {
  return { user: mockUser, signout: jest.fn(), enableUserAuth: true };
}

jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => mockSignedIn(),
}));
// What `useHostedGuest` reads: the same user, so the page knows a hosted guest
// as the app does.
jest.mock("../../providers/userContext", () => ({
  ...jest.requireActual("../../providers/userContext"),
  useUserContext: () => mockSignedIn(),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: jest.fn(),
    duplicate: (...args: unknown[]) => mockDuplicate(...args),
    delete: jest.fn(),
    create: jest.fn(),
  },
}));
jest.mock("../../NotebookConvertor", () => ({ notebookToTrill: jest.fn() }));
jest.mock("../../components/DataflowThumbnail", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/VersionBadge", () => ({ __esModule: true, default: () => null }));

import ProjectsList from "../../pages/projects/ProjectsList";
import { projectActions } from "../../pages/projects/projectActions";

const KEPT = "Kept for this visit";
const SIGN_IN_TO_SAVE = "Sign in to save dataflows.";
const SIGN_IN_TO_DUPLICATE = "Sign in to duplicate dataflows.";

function row(id: string, name: string, over: Record<string, unknown> = {}) {
  return {
    id,
    name,
    slug: id,
    description: null,
    thumbnail_accent: "peach",
    spec_revision: 2,
    last_opened_at: null,
    created_at: "2026-11-06T10:00:00Z",
    updated_at: "2026-11-06T11:00:00Z",
    graph_preview: null,
    categories: { source: null, auto: { tags: [], data_type: [] }, hand: {} },
    ...over,
  };
}

/** What the server lists for a hosted guest: its own new dataflow first, then an example. */
const LISTED = [
  row("mine", "My parks", { kept_for_visit: true }),
  row("ex1", "Example", { is_example: true, kept_for_visit: false }),
];

async function renderPage() {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(
      <MemoryRouter initialEntries={["/projects"]}>
        <ProjectsList />
      </MemoryRouter>,
    );
  });
  return utils!;
}

function card(container: HTMLElement, id: string): HTMLElement {
  return container.querySelector(`[data-project-id="${id}"]`) as HTMLElement;
}

beforeEach(() => {
  mockUser = GUEST;
  mockList.mockReset();
  mockList.mockResolvedValue(LISTED);
  mockDuplicate.mockReset();
  mockDuplicate.mockResolvedValue({ id: "copy" });
  mockShowToast.mockReset();
});

describe("a hosted guest's gallery", () => {
  test("lists its own new dataflow first, marked Kept for this visit with the Curio tooltip", async () => {
    const { container } = await renderPage();

    const cards = Array.from(container.querySelectorAll("[data-project-id]")).map((el) => el.getAttribute("data-project-id"));
    expect(cards).toEqual(["mine", "ex1"]);
    const mine = card(container, "mine");
    const mark = within(mine).getByText(KEPT);
    expect(mark.getAttribute("data-tooltip")).toBe(SIGN_IN_TO_SAVE);
    expect(mark.getAttribute("data-curio-kept-for-visit")).toBe("true");
    expect(mark.hasAttribute("title")).toBe(false);
    expect(getAllByTooltip(mine, SIGN_IN_TO_SAVE)).toEqual([mark]);
  });

  test("marks no example and no account's dataflow", async () => {
    const { container } = await renderPage();

    const example = card(container, "ex1");
    expect(within(example).queryByText(KEPT)).toBeNull();
    expect(queryAllByTooltip(example, SIGN_IN_TO_SAVE)).toEqual([]);
    expect(within(example).getByText("Rev 2")).toBeTruthy();
  });

  test("its drawer marks it too, and offers no Delete on either surface", async () => {
    const { container, getByRole, queryByRole } = await renderPage();

    // The drawer opens on the first card, the guest's own dataflow.
    expect(getByRole("heading", { name: "My parks" })).toBeTruthy();
    const drawerMarks = Array.from(container.querySelectorAll('[data-curio-kept-for-visit="true"]'));
    expect(drawerMarks.map((el) => el.textContent)).toEqual([KEPT, KEPT]);
    expect(queryByRole("button", { name: "Delete" })).toBeNull();
    for (const label of ["Rename", "Edit categories"]) {
      expect(getByRole("button", { name: label })).toBeTruthy();
    }

    await act(async () => {
      fireEvent.contextMenu(card(container, "mine"));
    });
    expect(queryByRole("menuitem", { name: "Delete" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Rename" })).toBeTruthy();
  });
});

describe("a hosted guest's Duplicate", () => {
  test("says to sign in before anything is sent, for its own dataflow and for an example", async () => {
    const { container, getByRole } = await renderPage();

    // The drawer is open on the guest's own dataflow; the example's card
    // offers Duplicate in its right-click menu.
    await act(async () => {
      fireEvent.click(getByRole("button", { name: "Duplicate" }));
    });
    await act(async () => {
      fireEvent.contextMenu(card(container, "ex1"));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Duplicate" }));
    });

    // One note for each, shown as the other sign-in notes are.
    expect(mockShowToast.mock.calls.filter(([, variant]) => variant === "warning")).toEqual([
      [SIGN_IN_TO_DUPLICATE, "warning"],
      [SIGN_IN_TO_DUPLICATE, "warning"],
    ]);
    expect(mockDuplicate).not.toHaveBeenCalled();
  });

  test("is an account's Duplicate as before: it is sent", async () => {
    mockUser = { name: "Ana", is_guest: false };
    const { container } = await renderPage();

    await act(async () => {
      fireEvent.contextMenu(card(container, "ex1"));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Duplicate" }));
    });

    expect(mockDuplicate).toHaveBeenCalledWith("ex1");
    expect(mockShowToast).not.toHaveBeenCalledWith(SIGN_IN_TO_DUPLICATE, "warning");
  });
});

describe("projectActions for a dataflow kept for the visit", () => {
  test("offers everything but Delete", () => {
    expect(projectActions({ keptForVisit: true }).map((a) => a.id)).toEqual([
      "open", "rename", "categories", "duplicate",
    ]);
    expect(projectActions({ keptForVisit: false }).map((a) => a.id)).toContain("delete");
  });
});
