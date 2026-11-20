/**
 * The tab bar API Settings and the monitor share (components/layout/TabBar.tsx):
 * a tablist whose tabs control the panels their caller renders, the shown tab
 * selected and alone in the tab order, a click or the arrow keys moving
 * between them, wrapping round. API Settings' own tests (agentConfiguration,
 * apiKeys, llmConfigurations) and the monitor page's (monitorPage) run it in
 * both places.
 */
import fs from "fs";
import path from "path";
import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { TabBar, tabPanelProps } from "../../components/layout/TabBar";

const TABS = [
  { key: "first", label: "First" },
  { key: "second", label: "Second" },
  { key: "third", label: "Third" },
];

function Tabs() {
  const [tab, setTab] = useState("first");
  return (
    <>
      <TabBar tabs={TABS} selected={tab} onSelect={setTab} label="Probe" idPrefix="probe" />
      <div {...tabPanelProps("probe", tab)}>{tab}</div>
    </>
  );
}

const tab = (name: string) => screen.getByRole("tab", { name });

test("a tablist whose tabs control their panels, the shown one selected and alone in the tab order", () => {
  render(<Tabs />);
  expect(screen.getByRole("tablist", { name: "Probe" })).toBeInTheDocument();
  expect(
    screen.getAllByRole("tab").map((each) => [
      each.id, each.getAttribute("aria-controls"), each.getAttribute("aria-selected"), each.getAttribute("tabindex"),
      each.className,
    ])
  ).toEqual([
    ["probe-tab-first", "probe-panel-first", "true", "0", "tab tabActive"],
    ["probe-tab-second", "probe-panel-second", "false", "-1", "tab"],
    ["probe-tab-third", "probe-panel-third", "false", "-1", "tab"],
  ]);
  const panel = screen.getByRole("tabpanel");
  expect([panel.id, panel.getAttribute("aria-labelledby")]).toEqual(["probe-panel-first", "probe-tab-first"]);
});

test("a click shows a tab, and the arrow keys move to the next and the one before, wrapping round", () => {
  render(<Tabs />);
  fireEvent.click(tab("Third"));
  expect(tab("Third")).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel")).toHaveTextContent("third");

  fireEvent.keyDown(tab("Third"), { key: "ArrowRight" });
  expect(tab("First")).toHaveAttribute("aria-selected", "true");
  expect(tab("First")).toHaveFocus();
  fireEvent.keyDown(tab("First"), { key: "ArrowLeft" });
  expect(tab("Third")).toHaveAttribute("aria-selected", "true");
  expect(tab("Third")).toHaveFocus();
  fireEvent.keyDown(tab("Third"), { key: "ArrowLeft" });
  expect(tab("Second")).toHaveFocus();

  // Any other key leaves the tab shown as it is.
  fireEvent.keyDown(tab("Second"), { key: "Enter" });
  expect(tab("Second")).toHaveAttribute("aria-selected", "true");
});

test("API Settings and the monitor show their tabs with it, its look in its own stylesheet", () => {
  const src = path.resolve(__dirname, "../..");
  const read = (rel: string) => fs.readFileSync(path.join(src, rel), "utf8");
  expect(read("components/apiSettings/ApiSettingsPanel.tsx")).toMatch(/<TabBar\b[^>]*idPrefix="api-settings"/);
  expect(read("pages/monitor/MonitorContent.tsx")).toMatch(/<TabBar\b[^>]*idPrefix="monitor"/);
  expect(read("components/layout/TabBar.module.css")).toMatch(/\.tab:hover:not\(\.tabActive\)/);
  // One look: API Settings keeps no tab rules of its own.
  expect(read("components/apiSettings/ApiSettings.module.css")).not.toMatch(/^\.tab(s|Active)?\b/m);
});
