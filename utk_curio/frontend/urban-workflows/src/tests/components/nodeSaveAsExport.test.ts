/**
 * The wizard's **Export** button.
 *
 * `POST /api/packages/factory/build` builds a `.curio.zip` from an
 * *un-installed* draft — it is the only way to get a package out of Curio
 * without first installing it. The route and its client method survived a
 * loose-endpoint sweep with zero callers, because the button that drove them
 * had been dropped from `NodeSaveAsModal`. This guards the wiring so the
 * endpoint cannot go orphaned again silently.
 *
 * Two halves:
 *  - the real units: `factoryBuild`'s response parsing and
 *    `triggerBlobDownload`'s DOM handoff, both exercised for real;
 *  - a structural check that the modal's Export path still calls them.
 *    Rendering the modal needs ReactFlow plus the Starter/Toast/Flow
 *    providers and a populated registry; the source check fails on the
 *    regression that matters (Export losing its call to `factoryBuild`, or
 *    the button disappearing again) at a fraction of the setup.
 */

import fs from "fs";
import path from "path";

// `packagesApi` re-exports `refreshPackageRegistry`, which drags in the whole
// node-adapter graph (packagesClient -> adapters/node -> vegaBehavior ->
// FlowProvider -> registry -> adapters/node) and deadlocks on the cycle under
// Jest's CommonJS interop. Stubbing the bootstrap module cuts the edge; nothing
// under test touches it.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

import { packagesApi, triggerBlobDownload } from "../../api/packagesApi";

const MODAL_SOURCE = path.resolve(
  __dirname,
  "../../components/packages/editing/NodeSaveAsModal.tsx",
);

function modalSource(): string {
  return fs.readFileSync(MODAL_SOURCE, "utf8");
}

describe("triggerBlobDownload", () => {
  test("hands the blob to an <a download> and revokes the object URL", () => {
    const createObjectURL = jest.fn(() => "blob:fake-url");
    const revokeObjectURL = jest.fn();
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, writable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, writable: true });

    const clicked: HTMLAnchorElement[] = [];
    const realCreate = document.createElement.bind(document);
    jest.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreate(tag);
      if (tag === "a") {
        jest.spyOn(el as HTMLAnchorElement, "click").mockImplementation(() => {
          clicked.push(el as HTMLAnchorElement);
        });
      }
      return el;
    });

    try {
      triggerBlobDownload(new Blob(["zip-bytes"]), "ai.test.pack@1.curio.zip");
    } finally {
      (document.createElement as jest.Mock).mockRestore();
    }

    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("ai.test.pack@1.curio.zip");
    expect(clicked[0].getAttribute("href")).toBe("blob:fake-url");
    // Not revoking leaks the blob for the lifetime of the document.
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake-url");
  });
});

describe("packagesApi.factoryBuild", () => {
  const realFetch = global.fetch;
  afterEach(() => {
    global.fetch = realFetch;
  });

  function mockZipResponse(headers: Record<string, string>) {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      headers: { get: (k: string) => headers[k] ?? null },
      blob: async () => new Blob(["zip-bytes"]),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    return fetchMock;
  }

  test("POSTs the draft to /factory/build and reads the filename from Content-Disposition", async () => {
    const fetchMock = mockZipResponse({
      "Content-Disposition": 'attachment; filename="ai.test.pack@1.curio.zip"',
    });

    const draft = { manifest: { id: "ai.test.pack" } };
    const { blob, filename } = await packagesApi.factoryBuild(draft);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/packages/factory/build");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(draft);
    expect(filename).toBe("ai.test.pack@1.curio.zip");
    expect(blob).toBeInstanceOf(Blob);
  });

  test("falls back to a generic filename when the header is absent", async () => {
    mockZipResponse({});
    const { filename } = await packagesApi.factoryBuild({});
    expect(filename).toBe("package.curio.zip");
  });

  test("surfaces the server error message", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: "manifest.id is required" }),
    }) as unknown as typeof fetch;

    await expect(packagesApi.factoryBuild({})).rejects.toThrow("manifest.id is required");
  });
});

// Source-text guards on the Export wiring. Belt-and-braces now: the behaviour
// itself is covered by test_save_as_package.py (e2e, mutation-verified) and the
// payload shaping by tests/utils/saveAsDraft.test.ts. These stay because they
// are ~1ms and catch a wiring regression before a 45s browser test does.
describe("NodeSaveAsModal Export wiring", () => {
  test("onExport builds the draft, calls factoryBuild, and downloads the result", () => {
    const src = modalSource();
    const start = src.indexOf("const onExport");
    expect(start).toBeGreaterThan(-1);
    // Find the end of the useCallback by SHAPE, not by the literal dependency
    // list. Keying on the exact deps meant that reordering them made indexOf
    // return -1, and slice(start, -1) then handed back nearly the whole file —
    // so these assertions kept passing against unrelated code. A false pass is
    // worse than a false failure, hence the explicit end-marker check.
    const endMatch = /\}, \[[^\]]*\]\);/.exec(src.slice(start));
    expect(endMatch).not.toBeNull();
    const body = src.slice(start, start + endMatch!.index + endMatch![0].length);

    expect(body).toContain("buildDraft()");
    expect(body).toContain("packagesApi.factoryBuild(");
    expect(body).toContain("triggerBlobDownload(blob, filename)");
  });

  test("the footer offers an Export button that is disabled while busy", () => {
    const src = modalSource();
    expect(src).toMatch(/onClick=\{\(\) => void onExport\(\)\}/);
    expect(src).toMatch(/busyKind === "export" \? "Exporting…" : "Export"/);
  });

  test("Save and Export share the busy gate so they cannot overlap", () => {
    const src = modalSource();
    // Both handlers bail on `busy` and set it before awaiting anything.
    expect(src.match(/if \(!canvasNode \|\| busy\) return;\s*\n\s*setBusy\(true\);/g)).toHaveLength(2);
  });
});
