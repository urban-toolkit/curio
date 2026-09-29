/**
 * The app's base path comes from the page's <base>, which the frontend server
 * points at `curio.py start --base-path`. The sign-in cookie is named and
 * scoped by it, so two instances on one host (/app and /app-dev) never read or
 * clear each other's session.
 */
import { basePath } from "../../utils/basePath";
import { clearToken, getToken, setToken } from "../../utils/authApi";

function setBase(href: string | null) {
  document.querySelectorAll("base").forEach((el) => el.remove());
  if (href === null) return;
  const el = document.createElement("base");
  el.setAttribute("href", href);
  document.head.appendChild(el);
}

afterEach(() => {
  clearToken();
  setBase(null);
  clearToken();
  window.history.pushState({}, "", "/");
});

describe("basePath", () => {
  test.each([
    [null, ""],
    ["/", ""],
    ["/app/", "/app"],
    ["/lab/curio/", "/lab/curio"],
  ])("<base href=%p> is %p", (href, expected) => {
    setBase(href);
    expect(basePath()).toBe(expected);
  });
});

describe("the sign-in cookie", () => {
  test("at the root of the host it is session_token", () => {
    setToken("root-token");
    expect(document.cookie).toContain("session_token=root-token");
    expect(getToken()).toBe("root-token");
  });

  test("under a base path it is named after it and kept to it", () => {
    window.history.pushState({}, "", "/app-dev/projects");
    setBase("/app-dev/");
    setToken("dev-token");
    expect(document.cookie).toContain("session_token_app-dev=dev-token");
    expect(getToken()).toBe("dev-token");

    window.history.pushState({}, "", "/app/projects");
    setBase("/app/");
    expect(document.cookie).not.toContain("dev-token");
    expect(getToken()).toBeUndefined();
    setToken("stable-token");
    clearToken();

    window.history.pushState({}, "", "/app-dev/projects");
    setBase("/app-dev/");
    expect(getToken()).toBe("dev-token");
  });
});
