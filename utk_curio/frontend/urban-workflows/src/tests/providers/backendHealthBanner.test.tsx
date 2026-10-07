/**
 * The backend banner on a local page (jsdom serves the page from localhost).
 *
 * A local reader can start the backend themselves, so the banner keeps telling
 * them how. While the backend is down it asks /live again every 10 s, and when
 * the backend answers the banner says so and offers a reload: the page could
 * not sign in or load anything meanwhile. A local page whose backend is up
 * asks once, as it always has, so local and e2e traffic is unchanged. The
 * hosted wording is pinned in backendHealthBannerHosted.test.tsx.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";

let mockStandalone = false;
jest.mock("../../standalone/dashboardPayload", () => ({
  isStandaloneDashboard: () => mockStandalone,
}));

import {
  BackendHealthBanner,
  DOWN_RECHECK_MS,
  isLocalPage,
} from "../../providers/BackendHealthBanner";

let live: "up" | "down" | "refused" = "up";
const mockFetch = jest.fn((url: string) => {
  if (!String(url).endsWith("/live")) return Promise.reject(new TypeError(`unrouted ${url}`));
  if (live === "refused") return Promise.reject(new TypeError("Failed to fetch"));
  return Promise.resolve({ ok: live === "up", status: live === "up" ? 200 : 502 });
});

const mount = () =>
  render(
    <BackendHealthBanner>
      <p>the app</p>
    </BackendHealthBanner>,
  );
const advance = (ms: number) => act(() => jest.advanceTimersByTimeAsync(ms));

beforeEach(() => {
  jest.useFakeTimers();
  (global as any).fetch = mockFetch;
  mockFetch.mockClear();
  mockStandalone = false;
  live = "up";
});

afterEach(() => {
  jest.useRealTimers();
});

test("the page under test is local", () => {
  expect(window.location.hostname).toBe("localhost");
  expect(isLocalPage()).toBe(true);
  expect(isLocalPage("127.0.0.1")).toBe(true);
  expect(isLocalPage("dev.urbantk.org")).toBe(false);
});

test("a local page whose backend is down says how to start it, and asks again after 10 s", async () => {
  live = "refused";
  mount();
  await advance(0);

  expect(screen.getByRole("alert").textContent).toContain("python curio.py start backend");
  expect(screen.getByText("the app")).toBeTruthy();
  expect(mockFetch).toHaveBeenCalledTimes(1);

  await advance(DOWN_RECHECK_MS - 1);
  expect(mockFetch).toHaveBeenCalledTimes(1);
  await advance(1);
  expect(mockFetch).toHaveBeenCalledTimes(2);
});

test("a local backend that comes back is announced with a reload", async () => {
  live = "refused";
  mount();
  await advance(0);
  expect(screen.getByRole("alert")).toBeTruthy();

  live = "up";
  await advance(DOWN_RECHECK_MS);

  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("status").textContent).toContain("Curio is back. Reload the page to continue.");
  expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();

  // Back up, a local page stops asking.
  await advance(10 * DOWN_RECHECK_MS);
  expect(mockFetch).toHaveBeenCalledTimes(2);
});

test("a local page whose backend is up asks once and shows nothing", async () => {
  mount();
  await advance(0);
  await advance(10 * DOWN_RECHECK_MS);

  expect(mockFetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
});

test("dismiss hides the outage until the backend comes back", async () => {
  live = "down";
  mount();
  await advance(0);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByRole("alert")).toBeNull();

  await advance(DOWN_RECHECK_MS);
  expect(mockFetch).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).toBeNull();

  live = "up";
  await advance(DOWN_RECHECK_MS);
  expect(screen.getByRole("status").textContent).toContain("Curio is back");
});

test("a standalone dashboard never asks", async () => {
  mockStandalone = true;
  live = "refused";
  mount();
  await advance(10 * DOWN_RECHECK_MS);

  expect(mockFetch).not.toHaveBeenCalled();
  expect(screen.queryByRole("alert")).toBeNull();
});
