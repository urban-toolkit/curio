/**
 * The projects page tells a list that failed from an empty one (#1274).
 *
 * A guest on stable got an empty projects page after "Continue as Guest", and a
 * reload showed every dataflow. In those days stable's backend was out of open
 * files and failed some requests, and the page loaded with
 * `projectsApi.list().catch(() => [])`: a failed list drew the same gallery as
 * an account with no dataflows, with no message and no second try. Before the
 * first answer the page already said "No projects yet" too.
 *
 * Now the page says it is loading until the list answers, asks again when a
 * request gets no answer or a server error, and when every try failed it says
 * so, with the server's reason and Retry, and reports it to the monitor. A list
 * that fails after the page showed dataflows keeps them on the page.
 *
 * The timers are fake, so the waits between tries pass at once.
 */
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: { name: "Guest" }, signout: jest.fn(), enableUserAuth: true }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
const mockList = jest.fn();
jest.mock("../../api/projectsApi", () => ({
  projectsApi: {
    list: (...args: unknown[]) => mockList(...args),
    update: jest.fn(),
    duplicate: jest.fn(),
    delete: jest.fn(),
    create: jest.fn(),
  },
}));
jest.mock("../../api/monitorApi", () => ({ postClientError: jest.fn() }));
jest.mock("../../NotebookConvertor", () => ({ notebookToTrill: jest.fn() }));
jest.mock("../../components/DataflowThumbnail", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/VersionBadge", () => ({ __esModule: true, default: () => null }));

import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ProjectsList from "../../pages/projects/ProjectsList";

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { postClientError } = require("../../api/monitorApi") as { postClientError: jest.Mock };

const project = (id: string, name: string) => ({
  id,
  name,
  slug: id,
  description: null,
  thumbnail_accent: "sky",
  spec_revision: 1,
  last_opened_at: null,
  created_at: "2026-01-01T10:00:00Z",
  updated_at: "2026-01-02T10:00:00Z",
  graph_preview: null,
  categories: { source: "example", auto: { tags: [], data_type: [] }, hand: {} },
});
const PROJECTS = [project("p1", "Air quality"), project("p2", "Bike lanes")];

const NO_PROJECTS = "No projects yet. Create a new dataflow!";
/** Longer than every wait the page takes between tries before it gives up. */
const PATIENCE_MS = 20_000;

/** What `apiFetch` throws for an answer that is not OK. */
const failure = (status: number, error: string) => Object.assign(new Error(error), { status, body: { error } });

const cards = () => document.querySelectorAll("[data-project-id]").length;
const alertText = () => screen.queryByRole("alert")?.textContent ?? null;

async function renderPage() {
  await act(async () => {
    render(
      <MemoryRouter initialEntries={["/projects"]}>
        <ProjectsList />
      </MemoryRouter>,
    );
  });
}

async function waitOut(ms = PATIENCE_MS) {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });
}

let warn: jest.SpyInstance;

beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ["requestAnimationFrame", "cancelAnimationFrame"] });
  mockList.mockReset();
  postClientError.mockClear();
  // Each try asked again says so in the console.
  warn = jest.spyOn(console, "warn").mockImplementation(() => undefined);
});

afterEach(() => {
  warn.mockRestore();
  jest.useRealTimers();
});

describe("the projects page, when its list is slow or fails", () => {
  test("says it is loading until the list answers, never that there are no projects", async () => {
    let answer: (rows: unknown[]) => void = () => undefined;
    mockList.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
    await renderPage();

    expect(screen.getByText("Loading dataflows…")).toBeTruthy();
    expect(screen.queryByText(NO_PROJECTS)).toBeNull();

    await act(async () => answer(PROJECTS));
    expect(cards()).toBe(2);
    expect(screen.queryByText("Loading dataflows…")).toBeNull();
  });

  test("asks again when the list fails, and shows what the next answer lists", async () => {
    mockList
      .mockRejectedValueOnce(failure(500, "[Errno 24] Too many open files"))
      .mockResolvedValue(PROJECTS);
    await renderPage();

    // The failed request is not an empty account.
    expect(screen.queryByText(NO_PROJECTS)).toBeNull();

    await waitOut();
    expect(cards()).toBe(2);
    expect(mockList).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(NO_PROJECTS)).toBeNull();
    expect(alertText()).toBeNull();
  });

  test("asks again when a request gets no answer at all", async () => {
    mockList.mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValue(PROJECTS);
    await renderPage();
    await waitOut();
    expect(cards()).toBe(2);
    expect(mockList).toHaveBeenCalledTimes(2);
  });

  test("when every try fails it says so with the reason and Retry, reports it once, and Retry lists", async () => {
    mockList.mockRejectedValue(failure(500, "[Errno 24] Too many open files"));
    await renderPage();
    await waitOut();

    expect(mockList.mock.calls.length).toBeGreaterThan(1);
    expect(alertText()).toContain("Couldn't load your dataflows: [Errno 24] Too many open files");
    expect(screen.queryByText(NO_PROJECTS)).toBeNull();
    expect(cards()).toBe(0);
    expect(postClientError).toHaveBeenCalledTimes(1);
    expect(postClientError.mock.calls[0][0].message).toContain("Couldn't load your dataflows");

    mockList.mockReset();
    mockList.mockResolvedValue(PROJECTS);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    });
    await waitOut();
    expect(cards()).toBe(2);
    expect(alertText()).toBeNull();
  });

  test("a refused session is not asked again", async () => {
    mockList.mockRejectedValue(failure(401, "Authorization required."));
    await renderPage();
    await waitOut();

    expect(mockList).toHaveBeenCalledTimes(1);
    expect(alertText()).toContain("Couldn't load your dataflows: Authorization required.");
    expect(screen.queryByText(NO_PROJECTS)).toBeNull();
  });

  test("a list that fails after the page showed dataflows keeps them, and says it failed", async () => {
    mockList.mockResolvedValueOnce(PROJECTS).mockRejectedValue(failure(502, "Bad gateway"));
    await renderPage();
    expect(cards()).toBe(2);

    // A new sort lists again, through the same loader as a rename or a delete.
    await act(async () => {
      fireEvent.change(screen.getByRole("combobox", { name: "Sort projects" }), { target: { value: "name" } });
    });
    await waitOut();

    expect(cards()).toBe(2);
    expect(alertText()).toContain("Couldn't load your dataflows: Bad gateway");
  });
});
