/**
 * A session check signs you out only when the server says the session is over.
 *
 * `UserProvider` asks `/api/auth/me` on every page load. The server answers a
 * dead session (no token, an unknown or expired one, a deleted account) with
 * 401 and nothing else. A check that was aborted because the page navigated
 * away, that could not connect, or that met a server error says nothing about
 * the session, so the token must survive it for the next load. A check whose
 * provider unmounted before it answered must not touch the token either.
 *
 * Drives the real `apiFetch` and the real session cookie; only `fetch` is
 * scripted.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import Cookies from "js-cookie";

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(() => Promise.resolve()),
}));

import UserProvider, { useUserContext } from "../../providers/UserProvider";

const COOKIE = "session_token";
const SHARED = "guest_shared";
const ALICE = { id: 7, username: "alice", name: "Alice", email: null, profile_image: null, type: null, is_guest: false };
const GUEST = { id: 1, username: SHARED, name: "Guest", email: null, profile_image: null, type: null, is_guest: true };

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

const who = async () => (await screen.findByTestId("who")).textContent;
const called = (path: string) => mockFetch.mock.calls.some(([url]) => String(url).endsWith(path));

beforeEach(() => {
  (global as any).fetch = mockFetch;
  mockFetch.mockClear();
  Cookies.set(COOKIE, "live-token");
});

afterEach(() => Cookies.remove(COOKIE));

describe("with sign-in on", () => {
  beforeEach(() => {
    mockRoutes = {
      "/api/config/public": () => answer(200, { curio_no_auth: false, allow_guest_login: true, shared_guest_username: SHARED }),
    };
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
  });

  it.each([
    ["an aborted check (the page navigated away)",
      () => Promise.reject(new DOMException("The user aborted a request.", "AbortError"))],
    ["a check that could not connect", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a server error", () => answer(502, { error: "Bad gateway" })],
  ])("keeps the token after %s", async (_what, me) => {
    mockRoutes["/api/auth/me"] = me;
    mount();
    expect(await who()).toBe("signed out");
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
