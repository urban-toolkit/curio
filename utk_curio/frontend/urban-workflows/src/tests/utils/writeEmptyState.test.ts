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

  test("a dashboard tile whose upstream downloads says how far on a line of its own under Computing...", () => {
    // A chart or a map on a dashboard, below a step that downloads what it
    // reads on its first use: each download on its line, the hint kept.
    const weights = "Downloading model.safetensors, a file of the weights of model.curio.sam3: 1.21 of 3.44 GB (35%)";
    const dataset = "Downloading datasets/data.utk.milan-mrt@1/data/milan-mrt.tif: 4.00 of 13.04 MB (30%)";
    const host = document.createElement("div");
    // The downloads, whatever the types of the code under test name.
    writeEmptyState(host, "upstream-running", { progress: [weights, dataset] } as any);
    const lines = Array.from(host.querySelectorAll("span")).map((span) => span.textContent);
    expect(lines).toEqual(["Computing...", weights, dataset, "Results will be shown here once they are ready."]);
    expect(host.getAttribute("data-curio-node-empty")).toBe("upstream-running");
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
