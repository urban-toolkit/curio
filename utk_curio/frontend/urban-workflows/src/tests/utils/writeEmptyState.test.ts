/**
 * A grammar node's empty state, written into the element it draws into: the
 * Vega-Lite node's writer, which the Autark node uses too.
 */
import { clearEmptyState, writeEmptyState } from "../../utils/writeEmptyState";

describe("writeEmptyState", () => {
  test("replaces what the host held with the shared copy and marks the reason", () => {
    const host = document.createElement("div");
    host.appendChild(document.createElement("canvas"));

    writeEmptyState(host, "upstream-not-run");

    expect(host.getAttribute("data-curio-node-empty")).toBe("upstream-not-run");
    expect(host.querySelector("canvas")).toBeNull();
    expect(host.textContent).toBe("No data yetRun the node feeding this one.");
  });

  test("a specific explanation replaces the hint; a step can have its own title", () => {
    const host = document.createElement("div");
    writeEmptyState(host, "not-run", { title: "Not run yet", hint: "This step loads data." });
    expect(host.textContent).toBe("Not run yetThis step loads data.");
  });

  test("no reason, no host: nothing happens", () => {
    const host = document.createElement("div");
    writeEmptyState(host, null);
    expect(host.hasAttribute("data-curio-node-empty")).toBe(false);
    expect(() => writeEmptyState(null, "no-spec")).not.toThrow();
  });

  test("clearing removes the marker", () => {
    const host = document.createElement("div");
    writeEmptyState(host, "no-spec");
    clearEmptyState(host);
    expect(host.hasAttribute("data-curio-node-empty")).toBe(false);
  });
});
