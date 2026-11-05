/**
 * A session check signs you out only when the server says the session is over.
 *
 * `UserProvider` asks `/api/auth/me` on every page load. The server answers a
 * dead session (no token, an unknown or expired one, a deleted account) with
 * 401 and nothing else. A check that was aborted because the page navigated
 * away, that could not connect, or that met a server error says nothing about
 * the session, so the token must survive it for the next load. With sign-in
 * on, the load asks again after each of `SESSION_CHECK_WAITS_MS` before it
 * shows the sign-in form: a browser drops every request in flight when the
 * machine's network changes (`net::ERR_NETWORK_CHANGED`), and one dropped
 * check showed a signed-in owner the sign-in form on CI. A check whose
 * provider unmounted before it answered must not touch the token either.
 *
 * Drives the real `apiFetch` and the real session cookie; only `fetch` is
 * scripted. With sign-in on the timers are fake, so the waits between checks
 * pass at once.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import Cookies from "js-cookie";

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(() => Promise.resolve()),
}));

import UserProvider, { SESSION_CHECK_WAITS_MS, useUserContext } from "../../providers/UserProvider";

const COOKIE = "session_token";
const SHARED = "guest_shared";
const ALICE = { id: 7, username: "alice", name: "Alice", email: null, profile_image: null, type: null, is_guest: false };
const GUEST = { id: 1, username: SHARED, name: "Guest", email: null, profile_image: null, type: null, is_guest: true };
/** Every wait of one load's checks, end to end. */
const ALL_WAITS_MS = SESSION_CHECK_WAITS_MS.reduce((sum, ms) => sum + ms, 0);

const answer = (status: number, body: unknown = {}) =>
  Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) });

let mockRoutes: Record<string, () => Promise<unknown>> = {};
const mockFetch = jest.fn((url: string) => {
  const path = Object.keys(mockRoutes).find((p) => String(url).endsWith(p));
  return path ? mockRoutes[path]() : Promise.reject(new TypeError(`unrouted ${url}`));
});

const Who = () => {
  const { user } = useUserContext();
  return <p data-testid="who">{user ? user.username : "signed out"}</p>;
};

const mount = () =>
  render(
    <UserProvider>
      <Who />
    </UserProvider>,
  );

/** Who the page shows once it has loaded, within *timeout* ms (fake ones while
 * the timers are fake). */
const who = async (timeout = 1000) =>
  (await screen.findByTestId("who", undefined, { timeout })).textContent;
const called = (path: string) => mockFetch.mock.calls.some(([url]) => String(url).endsWith(path));
/** How many times the page asked who is signed in. */
const checks = () => mockFetch.mock.calls.filter(([url]) => String(url).endsWith("/api/auth/me")).length;

beforeEach(() => {
  (global as any).fetch = mockFetch;
  mockFetch.mockClear();
  Cookies.set(COOKIE, "live-token");
});

afterEach(() => Cookies.remove(COOKIE));

describe("with sign-in on", () => {
  let warn: jest.SpyInstance;

  beforeEach(() => {
    jest.useFakeTimers();
    // Each check asked again says so in the console.
    warn = jest.spyOn(console, "warn").mockImplementation(() => undefined);
    mockRoutes = {
      "/api/config/public": () => answer(200, { curio_no_auth: false, allow_guest_login: true, shared_guest_username: SHARED }),
    };
  });

  afterEach(() => {
    warn.mockRestore();
    jest.useRealTimers();
  });

  it("keeps a session the server confirms", async () => {
    mockRoutes["/api/auth/me"] = () => answer(200, ALICE);
    mount();
    expect(await who()).toBe("alice");
    expect(Cookies.get(COOKIE)).toBe("live-token");
  });

  it("signs out when the server says the session is over", async () => {
    mockRoutes["/api/auth/me"] = () => answer(401, { error: "Authorization required." });
    mount();
    expect(await who()).toBe("signed out");
    expect(Cookies.get(COOKIE)).toBeUndefined();
    // A refused session is not asked again.
    expect(checks()).toBe(1);
  });

  it.each([
    ["an aborted check (the page navigated away)",
      () => Promise.reject(new DOMException("The user aborted a request.", "AbortError"))],
    ["a check that could not connect", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a server error", () => answer(502, { error: "Bad gateway" })],
  ])("keeps the token after %s", async (_what, me) => {
    mockRoutes["/api/auth/me"] = me;
    mount();
    expect(await who(2 * ALL_WAITS_MS)).toBe("signed out");
    expect(Cookies.get(COOKIE)).toBe("live-token");
    // Asked again after each wait, and only the last failure stands.
    expect(checks()).toBe(SESSION_CHECK_WAITS_MS.length + 1);
  });

  // The CI flake: the browser dropped the page's one check when the machine's
  // network changed, and the owner's dataflow opened on the sign-in form.
  it.each([
    ["could not connect (the browser dropped it when the network changed)",
      () => Promise.reject(new TypeError("Failed to fetch"))],
    ["met a server error", () => answer(502, { error: "Bad gateway" })],
  ])("asks again when a check %s, and keeps the session the next one confirms", async (_what, first) => {
    let asked = 0;
    mockRoutes["/api/auth/me"] = () => (asked++ === 0 ? first() : answer(200, ALICE));
    mount();
    expect(await who(2 * ALL_WAITS_MS)).toBe("alice");
    expect(checks()).toBe(2);
    expect(Cookies.get(COOKIE)).toBe("live-token");
  });

  it("asks no more once the provider unmounted, and leaves the token alone", async () => {
    mockRoutes["/api/auth/me"] = () => Promise.reject(new TypeError("Failed to fetch"));
    const view = mount();
    await waitFor(() => expect(checks()).toBe(1));
    view.unmount();
    await jest.advanceTimersByTimeAsync(2 * ALL_WAITS_MS);
    expect(checks()).toBe(1);
    expect(Cookies.get(COOKIE)).toBe("live-token");
  });
});

describe("with sign-in off (the shared guest)", () => {
  beforeEach(() => {
    mockRoutes = {
      "/api/config/public": () => answer(200, { curio_no_auth: true, shared_guest_username: SHARED }),
      "/api/auth/signin/auto-guest": () => answer(200, { user: GUEST, token: "new-token" }),
    };
  });

  it("keeps the shared guest's session", async () => {
    mockRoutes["/api/auth/me"] = () => answer(200, GUEST);
    mount();
    expect(await who()).toBe(SHARED);
    expect(Cookies.get(COOKIE)).toBe("live-token");
    expect(called("/api/auth/signin/auto-guest")).toBe(false);
  });

  it("replaces a token that belongs to another account", async () => {
    mockRoutes["/api/auth/me"] = () => answer(200, ALICE);
    mount();
    expect(await who()).toBe(SHARED);
    expect(Cookies.get(COOKIE)).toBe("new-token");
  });

  it("replaces a token the server refused", async () => {
    mockRoutes["/api/auth/me"] = () => answer(401, { error: "Authorization required." });
    mount();
    expect(await who()).toBe(SHARED);
    expect(Cookies.get(COOKIE)).toBe("new-token");
  });

  it("leaves the token alone when the check ends after the provider unmounted", async () => {
    let settle: (value: unknown) => void = () => undefined;
    mockRoutes["/api/auth/me"] = () => new Promise((resolve) => { settle = resolve; });
    const view = mount();
    await waitFor(() => expect(called("/api/auth/me")).toBe(true));
    view.unmount();
    settle(await answer(200, GUEST));
    // Let the bootstrap's remaining awaits run.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(Cookies.get(COOKIE)).toBe("live-token");
    expect(called("/api/auth/signin/auto-guest")).toBe(false);
  });
});
