/**
 * The owner's dashboard link lets whoever opens it run the dashboard: copying
 * it publishes the dataflow as saved, and the link carries the run token.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockShowToast = jest.fn();
const mockCopyText = jest.fn();
const mockApi = { publish: jest.fn() };

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../utils/clipboard", () => ({
  copyText: (...args: any[]) => mockCopyText(...args),
}));
jest.mock("../../services/published/publishedApi", () => ({
  ...jest.requireActual("../../services/published/publishedApi"),
  get publishedApi() {
    return mockApi;
  },
}));

import ShareMenu, { RUN_LINK_COPIED } from "../../components/menus/top/ShareMenu";
import { runLink } from "../../services/published/publishedApi";

const ID = "11111111-2222-3333-4444-555555555555";
const ORIGIN = window.location.origin;
const DASHBOARD = `${ORIGIN}/curio/dashboard/${ID}`;

function renderMenu(canPublish: boolean, projectDirty = false) {
  render(
    <MemoryRouter basename="/curio" initialEntries={[`/curio/dataflow/${ID}`]}>
      <ShareMenu id={ID} includeOpenDashboard={false} open onToggle={() => {}} onClose={() => {}}
        canPublish={canPublish} projectDirty={projectDirty} />
    </MemoryRouter>,
  );
}

const copyDashboardLink = async () => {
  await act(async () => {
    fireEvent.click(screen.getByText("Copy dashboard link"));
  });
};

beforeEach(() => {
  jest.clearAllMocks();
  mockCopyText.mockResolvedValue(true);
});

test("there is no separate Publish row", () => {
  renderMenu(true);
  expect(screen.queryByTestId("publish-menu-item")).toBeNull();
});

test("the owner's link publishes the dataflow and carries the run token", async () => {
  mockApi.publish.mockResolvedValue({ token: "tok_123" });
  renderMenu(true);
  await copyDashboardLink();
  expect(mockApi.publish).toHaveBeenCalledWith(ID, "link");
  expect(mockCopyText).toHaveBeenCalledWith(`${DASHBOARD}?run=tok_123`, "dashboard link");
  expect(mockShowToast).toHaveBeenCalledWith(RUN_LINK_COPIED, "success");
});

test("with unsaved edits, it says the link runs the saved version", async () => {
  mockApi.publish.mockResolvedValue({ token: "tok_123" });
  renderMenu(true, true);
  await copyDashboardLink();
  expect(mockShowToast.mock.calls[0][0]).toContain("Save to update it.");
});

test("a dataflow that cannot be published gets the plain link, and is told why", async () => {
  mockApi.publish.mockRejectedValue(new Error("Pin at least one node to the dashboard before publishing it."));
  renderMenu(true);
  await copyDashboardLink();
  expect(mockCopyText).toHaveBeenCalledWith(DASHBOARD, "dashboard link");
  expect(mockShowToast).toHaveBeenCalledWith(
    "Dashboard link copied, for viewing only: Pin at least one node to the dashboard before publishing it.",
    "info",
  );
});

test("anyone else copies the plain link, and nothing is published", async () => {
  renderMenu(false);
  await copyDashboardLink();
  expect(mockApi.publish).not.toHaveBeenCalled();
  expect(mockCopyText).toHaveBeenCalledWith(DASHBOARD, "dashboard link");
});

test("the run link is the dashboard's address with the link token", () => {
  expect(runLink("https://curio.example/dashboard/abc", "t/1")).toBe("https://curio.example/dashboard/abc?run=t%2F1");
});
