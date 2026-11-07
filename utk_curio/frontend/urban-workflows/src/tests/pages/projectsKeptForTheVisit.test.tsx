/**
 * A hosted guest's gallery: the dataflows its File > New made come first, as
 * the server lists them (`kept_for_visit`), each marked Kept for this visit,
 * with the one Curio tooltip saying only an account saves a dataflow. The
 * server drops them when it starts again, so neither the drawer nor the
 * right-click menu offers to delete one. The harness is
 * projectsPageChrome.test.tsx's.
 */
import React from "react";
import { render, act, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { getAllByTooltip, queryAllByTooltip } from "../_support/tooltips";

const mockList = jest.fn();

jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: { name: "Guest", is_guest: true }, signout: jest.fn(), enableUserAuth: true }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../api/projectsApi", () => ({
  projectsApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: jest.fn(),
    duplicate: jest.fn(),
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
  mockList.mockReset();
  mockList.mockResolvedValue(LISTED);
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

describe("projectActions for a dataflow kept for the visit", () => {
  test("offers everything but Delete", () => {
    expect(projectActions({ keptForVisit: true }).map((a) => a.id)).toEqual([
      "open", "rename", "categories", "duplicate",
    ]);
    expect(projectActions({ keptForVisit: false }).map((a) => a.id)).toContain("delete");
  });
});
