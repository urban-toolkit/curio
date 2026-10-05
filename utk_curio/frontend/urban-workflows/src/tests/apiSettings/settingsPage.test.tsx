import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/**
 * API Settings as a page: the section pages' top bar links to /settings, the
 * tab is part of the path, and a card's request arrives as the query.
 */

jest.mock("../../components/layout/GlobalPageHeader", () => ({
  GlobalPageHeader: () => <header data-testid="global-header" />,
}));
jest.mock("../../components/layout/AppSectionTabs", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/VersionBadge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/apiSettings/ApiSettingsPanel", () => ({
  ApiSettingsPanel: (props: { tab: string; focus: unknown; onTabChange: (tab: string) => void }) => (
    <div data-testid="panel" data-tab={props.tab} data-focus={JSON.stringify(props.focus)}>
      <button type="button" onClick={() => props.onTabChange("agents")}>
        Agent configuration
      </button>
    </div>
  ),
}));

import SettingsPage from "../../pages/settings/SettingsPage";

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings/:tab?" element={<><SettingsPage /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );

const panel = () => screen.getByTestId("panel");
const focusOf = () => JSON.parse(panel().getAttribute("data-focus")!);

describe("the settings page", () => {
  it("wears the section pages' top bar and titles itself", () => {
    renderAt("/settings/keys");
    expect(screen.getByTestId("global-header")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "API Settings", level: 1 })).toBeInTheDocument();
    expect(panel()).toHaveAttribute("data-tab", "keys");
    expect(focusOf()).toBeNull();
  });

  it.each(["/settings", "/settings/evaluation"])("%s opens on API keys", (path) => {
    renderAt(path);
    expect(screen.getByTestId("where").textContent).toBe("/settings/keys");
    expect(panel()).toHaveAttribute("data-tab", "keys");
  });

  it("a tab is a path", () => {
    renderAt("/settings/keys");
    fireEvent.click(screen.getByRole("button", { name: "Agent configuration" }));
    expect(screen.getByTestId("where").textContent).toBe("/settings/agents");
    expect(panel()).toHaveAttribute("data-tab", "agents");
  });

  it.each([
    ["/settings/agents?agent=agent.chat-agent", { section: "agent-models", agentId: "agent.chat-agent" }],
    ["/settings/keys?service=mapillary.token", { section: "source-key", slot: "mapillary.token" }],
    ["/settings/keys?config=llm-1", { section: "llm-configs", configId: "llm-1" }],
    ["/settings/keys?add=node&host=api.census.gov&name=census",
      { section: "connection-keys", host: "api.census.gov", suggestedName: "census" }],
  ])("%s hands the panel the place a card asked for", (path, focus) => {
    renderAt(path);
    expect(focusOf()).toEqual(focus);
  });
});
