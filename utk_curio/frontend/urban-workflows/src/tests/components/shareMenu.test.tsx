/**
 * The Share menu, which replaced View > Dashboard Mode on the dataflow's bar and
 * is the only way to the dashboard from it.
 *
 * What it must get right is small and easy to get subtly wrong:
 *
 *  - "Open dashboard" opens a NEW TAB. The dataflow the user is editing stays
 *    put; a real anchor is also what keeps a popup blocker out of the way.
 *  - The links are absolute and carry the router's basename, so a copied link
 *    works when Curio is served under a sub-path.
 *  - Before the first save there is nothing to link to, and it says so.
 *  - An unsaved edit is not in what the new tab will show, and it says that too.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockShowToast = jest.fn();
const mockCopyText = jest.fn();

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../utils/clipboard", () => ({
  copyText: (...args: any[]) => mockCopyText(...args),
}));

import ShareMenu, {
  SAVE_FIRST_MESSAGE,
  STALE_DASHBOARD_MESSAGE,
} from "../../components/menus/top/ShareMenu";

const ID = "11111111-2222-3333-4444-555555555555";
const ORIGIN = window.location.origin;

function renderMenu(props: Partial<React.ComponentProps<typeof ShareMenu>> = {}) {
  const onClose = jest.fn();
  const utils = render(
    <MemoryRouter basename="/curio" initialEntries={[`/curio/dataflow/${ID}`]}>
      <ShareMenu
        id={ID}
        includeOpenDashboard
        open
        onToggle={() => {}}
        onClose={onClose}
        {...props}
      />
    </MemoryRouter>,
  );
  return { ...utils, onClose };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockCopyText.mockResolvedValue(true);
});

describe("Open dashboard", () => {
  test("is a link to the dashboard that opens a new tab", () => {
    renderMenu();

    const link = screen.getByTestId("open-dashboard-link");
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe(`${ORIGIN}/curio/dashboard/${ID}`);
    expect(link.getAttribute("target")).toBe("_blank");
    // The new tab gets no handle back to this one.
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  test("says what the new tab will not show when there are unsaved edits", () => {
    const { onClose } = renderMenu({ projectDirty: true });

    fireEvent.click(screen.getByTestId("open-dashboard-link"));

    expect(mockShowToast).toHaveBeenCalledWith(STALE_DASHBOARD_MESSAGE, "info");
    expect(onClose).toHaveBeenCalled();
  });

  test("says nothing when the dataflow is saved", () => {
    renderMenu({ projectDirty: false });

    fireEvent.click(screen.getByTestId("open-dashboard-link"));

    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test("is not offered on the dashboard's own bar", () => {
    renderMenu({ includeOpenDashboard: false });

    expect(screen.queryByTestId("open-dashboard-link")).toBeNull();
    expect(screen.getByText("Copy dashboard link")).toBeTruthy();
  });
});

describe("the copy rows", () => {
  test("copy the absolute dashboard link", async () => {
    renderMenu();

    await act(async () => { fireEvent.click(screen.getByText("Copy dashboard link")); });

    expect(mockCopyText).toHaveBeenCalledWith(
      `${ORIGIN}/curio/dashboard/${ID}`, "dashboard link",
    );
    expect(mockShowToast).toHaveBeenCalledWith("Dashboard link copied.", "success");
  });

  test("copy the absolute dataflow link", async () => {
    renderMenu();

    await act(async () => { fireEvent.click(screen.getByText("Copy dataflow link")); });

    expect(mockCopyText).toHaveBeenCalledWith(`${ORIGIN}/curio/dataflow/${ID}`, "dataflow link");
    expect(mockShowToast).toHaveBeenCalledWith("Dataflow link copied.", "success");
  });

  test("a clipboard that refuses is reported, not ignored", async () => {
    mockCopyText.mockResolvedValue(false);
    renderMenu();

    await act(async () => { fireEvent.click(screen.getByText("Copy dashboard link")); });

    expect(mockShowToast).toHaveBeenCalledWith("Could not copy the dashboard link.", "error");
  });
});

describe("before the first save", () => {
  test("every row says to save first, and nothing is copied or opened", async () => {
    renderMenu({ id: null });

    const link = screen.getByTestId("open-dashboard-link");
    expect(link.getAttribute("href")).toBeNull();
    fireEvent.click(link);
    await act(async () => { fireEvent.click(screen.getByText("Copy dashboard link")); });
    await act(async () => { fireEvent.click(screen.getByText("Copy dataflow link")); });

    expect(mockCopyText).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledTimes(3);
    for (const call of mockShowToast.mock.calls) {
      expect(call).toEqual([SAVE_FIRST_MESSAGE, "info"]);
    }
  });
});

test("the menu closes after any row", async () => {
  const { onClose } = renderMenu();

  await act(async () => { fireEvent.click(screen.getByText("Copy dataflow link")); });

  expect(onClose).toHaveBeenCalled();
});

test("closed, it is just the button", () => {
  renderMenu({ open: false });

  expect(screen.getByTestId("share-menu-btn")).toBeTruthy();
  expect(screen.queryByText("Copy dashboard link")).toBeNull();
});
