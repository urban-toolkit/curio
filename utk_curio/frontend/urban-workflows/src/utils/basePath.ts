/**
 * The path prefix the app is served under, without its trailing slash: "" at
 * the root of a host, "/app" under https://host/app/. Read from the page's
 * <base>, which `curio.py start --base-path` sets; index.tsx gives it to
 * `BrowserRouter` as its basename.
 */
export function basePath(): string {
  if (typeof document === "undefined") return "";
  const href = document.querySelector("base")?.getAttribute("href") ?? "/";
  return href.replace(/\/+$/, "");
}
