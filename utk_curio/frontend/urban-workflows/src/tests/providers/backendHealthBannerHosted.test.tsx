/**
 * @jest-environment-options {"url": "https://dev.urbantk.org/"}
 */
/**
 * The backend banner on a hosted page (dev.urbantk.org, flow.urbantk.org).
 *
 * A visitor cannot start the backend, and it is down because the site is being
 * updated or its server is. A deploy also restarts the frontend, whose server
 * comes up first, so the page loads while the backend is still starting and
 * the banner is what explains the wait. Behind Caddy a dead backend answers
 * 502, not a network error. A hosted page keeps asking while the backend is up
 * and the tab is visible, so an outage that starts while it is open is shown.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";

jest.mock("../../standalone/dashboardPayload", () => ({
  isStandaloneDashboard: () => false,
}));

import {
  BackendHealthBanner,
  DOWN_RECHECK_MS,
  UP_RECHECK_MS,
  isLocalPage,
} from "../../providers/BackendHealthBanner";

const OFFLINE = "Curio is offline: it is being updated or its server is down.";

let live: "up" | "down" = "down";
const mockFetch = jest.fn((url: string) => {
  if (!String(url).endsWith("/live")) return Promise.reject(new TypeError(`unrouted ${url}`));
  return Promise.resolve({ ok: live === "up", status: live === "up" ? 200 : 502 });
});

const mount = () =>
  render(
    <BackendHealthBanner>
      <p>the app</p>
    </BackendHealthBanner>,
  );
const advance = (ms: number) => act(() => jest.advanceTimersByTimeAsync(ms));

const setVisibility = (state: "visible" | "hidden") =>
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });

beforeEach(() => {
  jest.useFakeTimers();
  (global as any).fetch = mockFetch;
  mockFetch.mockClear();
  live = "down";
  setVisibility("visible");
});

afterEach(() => {
  jest.useRealTimers();
  setVisibility("visible");
});

test("the page under test is hosted", () => {
  expect(window.location.hostname).toBe("dev.urbantk.org");
  expect(isLocalPage()).toBe(false);
});

test("a hosted page whose backend is down says Curio is offline, not how to start it", async () => {
  mount();
  await advance(0);

  const banner = screen.getByRole("alert");
  expect(banner.textContent).toContain(OFFLINE);
  expect(banner.textContent).not.toContain("curio.py");
  expect(screen.getByText("the app")).toBeTruthy();
});

test("the banner says Curio is back once /live answers", async () => {
  mount();
  await advance(0);
  await advance(DOWN_RECHECK_MS);
  expect(screen.getByRole("alert").textContent).toContain(OFFLINE);

  live = "up";
  await advance(DOWN_RECHECK_MS);

  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("status").textContent).toContain("Curio is back. Reload the page to continue.");
  expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
});

test("an outage that starts while the page is open is shown", async () => {
  live = "up";
  mount();
  await advance(0);
  expect(mockFetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).toBeNull();

  await advance(UP_RECHECK_MS);
  expect(mockFetch).toHaveBeenCalledTimes(2);

  live = "down";
  await advance(UP_RECHECK_MS);
  expect(screen.getByRole("alert").textContent).toContain(OFFLINE);
});

test("a hidden tab whose backend is up does not ask until it is visible", async () => {
  live = "up";
  mount();
  await advance(0);
  expect(mockFetch).toHaveBeenCalledTimes(1);

  setVisibility("hidden");
  await advance(3 * UP_RECHECK_MS);
  expect(mockFetch).toHaveBeenCalledTimes(1);

  setVisibility("visible");
  await advance(UP_RECHECK_MS);
  expect(mockFetch).toHaveBeenCalledTimes(2);
});
