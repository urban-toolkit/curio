import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

/**
 * On the canvas and the dashboard, the top bar's API Settings and Monitor open
 * drawers instead of their pages, so the dataflow stays open. API Settings can
 * open over a catalog drawer (Discovery's "Add yours in API Settings"), so one
 * Escape must close the top drawer alone.
 */

jest.mock("../../components/apiSettings/ApiSettingsPanel", () => {
  const Panel = (props: { tab: string; focus: unknown; onTabChange: (tab: string) => void }) => (
    <div data-testid="panel" data-tab={props.tab} data-focus={JSON.stringify(props.focus)}>
      <button type="button" onClick={() => props.onTabChange("keys")}>
        Show keys
      </button>
    </div>
  );
  return { __esModule: true, ApiSettingsPanel: Panel, default: Panel };
});
jest.mock("../../pages/monitor/MonitorContent", () => ({
  __esModule: true,
  default: () => <div data-testid="monitor-content" />,
}));

import ModalShell, { modalStackDepth } from "../../components/ModalShell";
import { HeaderDrawer } from "../../components/layout/HeaderDrawer";
import {
  ApiSettingsDrawerProvider,
  useApiSettingsDrawerOptional,
} from "../../providers/ApiSettingsDrawerProvider";
import { MonitorDrawerProvider, useMonitorDrawerOptional } from "../../providers/MonitorDrawerProvider";

function SettingsOpener() {
  const drawer = useApiSettingsDrawerOptional()!;
  return (
    <>
      <button type="button" onClick={() => drawer.openApiSettings()}>
        open settings
      </button>
      <button
        type="button"
        onClick={() => drawer.openApiSettings({ section: "agent-models", agentId: "agent.chat-agent" })}
      >
        open on an agent
      </button>
    </>
  );
}

function MonitorOpener() {
  const drawer = useMonitorDrawerOptional()!;
  return (
    <button type="button" onClick={drawer.openMonitor}>
      open monitor
    </button>
  );
}

const drawerRoot = (name: string) => document.querySelector(`[data-curio-${name}-drawer="true"]`);

describe("the API Settings drawer", () => {
  it("opens on the keys tab, or on the tab and place a card asked for", async () => {
    render(
      <ApiSettingsDrawerProvider>
        <SettingsOpener />
      </ApiSettingsDrawerProvider>,
    );
    expect(drawerRoot("settings")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "open settings" }));
    expect(await screen.findByTestId("panel")).toHaveAttribute("data-tab", "keys");
    await waitFor(() => expect(drawerRoot("settings")).toHaveAttribute("aria-hidden", "false"));
    expect(screen.getByRole("heading", { name: "API Settings", level: 2 })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close API Settings" }));
    await waitFor(() => expect(drawerRoot("settings")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "open on an agent" }));
    const panel = await screen.findByTestId("panel");
    expect(panel).toHaveAttribute("data-tab", "agents");
    expect(JSON.parse(panel.getAttribute("data-focus")!)).toEqual({ section: "agent-models", agentId: "agent.chat-agent" });
    // The drawer keeps the tab in its own state.
    fireEvent.click(screen.getByRole("button", { name: "Show keys" }));
    expect(screen.getByTestId("panel")).toHaveAttribute("data-tab", "keys");
  });

  it("locks the page's scroll while open, and gives it back once closed", async () => {
    render(
      <ApiSettingsDrawerProvider>
        <SettingsOpener />
      </ApiSettingsDrawerProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "open settings" }));
    await screen.findByTestId("panel");
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss API Settings" }));
    await waitFor(() => expect(drawerRoot("settings")).toBeNull());
    expect(document.body.style.overflow).toBe("");
  });
});

describe("the Monitor drawer", () => {
  it("renders the monitor's content, and closes on its close button", async () => {
    render(
      <MonitorDrawerProvider>
        <MonitorOpener />
      </MonitorDrawerProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "open monitor" }));
    expect(await screen.findByTestId("monitor-content")).toBeInTheDocument();
    await waitFor(() => expect(drawerRoot("monitor")).toHaveAttribute("aria-hidden", "false"));
    expect(screen.getByRole("heading", { name: "Monitor", level: 2 })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close Monitor" }));
    await waitFor(() => expect(drawerRoot("monitor")).toBeNull());
  });
});

describe("Escape with a header drawer over another surface", () => {
  // The catalog drawers' and the chat panel's guard, as escapeDefersToModal
  // pins it in each of their sources.
  const lowerClose = jest.fn();
  const lowerListener = (ev: KeyboardEvent) => {
    if (modalStackDepth() > 0) return;
    if (ev.key === "Escape") lowerClose();
  };

  beforeEach(() => {
    lowerClose.mockReset();
    window.addEventListener("keydown", lowerListener);
  });
  afterEach(() => window.removeEventListener("keydown", lowerListener));

  const drawer = (onRequestClose: () => void, children: React.ReactNode = "Keys") => (
    <HeaderDrawer
      presented
      onRequestClose={onRequestClose}
      onExitComplete={() => undefined}
      title="API Settings"
      titleId="t"
      name="settings"
    >
      {children}
    </HeaderDrawer>
  );

  it("closes the header drawer alone, and the surface under it answers once it is gone", () => {
    const close = jest.fn();
    const { unmount } = render(drawer(close));
    expect(modalStackDepth()).toBe(1);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalledTimes(1);
    expect(lowerClose).not.toHaveBeenCalled();

    unmount();
    expect(modalStackDepth()).toBe(0);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(lowerClose).toHaveBeenCalledTimes(1);
  });

  it("a modal opened over it takes Escape, and the drawer stays", () => {
    const close = jest.fn();
    const closeModal = jest.fn();
    render(
      drawer(
        close,
        <ModalShell onClose={closeModal} label="Confirm">
          sure?
        </ModalShell>,
      ),
    );
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(closeModal).toHaveBeenCalledTimes(1);
    expect(close).not.toHaveBeenCalled();
    expect(lowerClose).not.toHaveBeenCalled();
  });
});
