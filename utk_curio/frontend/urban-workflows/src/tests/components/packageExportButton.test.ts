/**
 * The palette's export path: `packagesApi.download(dirName)`.
 *
 * `nodeSaveAsExport.test.ts` covers `triggerBlobDownload` for the Save-As wizard,
 * but not this one - and they differ in the detail that matters. The wizard reads
 * its filename from `Content-Disposition`; this path *synthesises*
 * `${dirName}.curio.zip` client-side and ignores the header entirely. So a server
 * change to that header is invisible here (it is pinned in
 * `test_packages/test_routes.py` instead), while a change to the dirName -> name
 * mapping is invisible there.
 *
 * Kept as a unit test of the api layer rather than a render test of the accordion:
 * the accordion pulls in the whole node registry, and the only logic on that
 * button is `download(group.key)` plus an error toast, which the e2e test
 * exercises for real.
 */
// packagesApi -> packageRegistryBootstrap -> packagesClient -> adapters/node
// -> vegaBehavior -> FlowProvider -> registry -> adapters/node. That cycle
// deadlocks under Jest's CommonJS interop; same mock nodeSaveAsExport uses.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

import { packagesApi } from "../../api/packagesApi";

const ORIGINAL_FETCH = global.fetch;

type Clicked = { download: string; href: string };

function captureAnchorClicks(): Clicked[] {
  const clicked: Clicked[] = [];
  const realCreate = document.createElement.bind(document);
  jest.spyOn(document, "createElement").mockImplementation(((tag: string) => {
    const el = realCreate(tag);
    if (tag === "a") {
      jest.spyOn(el as HTMLAnchorElement, "click").mockImplementation(() => {
        clicked.push({
          download: (el as HTMLAnchorElement).download,
          href: el.getAttribute("href") ?? "",
        });
      });
    }
    return el;
  }) as typeof document.createElement);
  return clicked;
}

beforeEach(() => {
  (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest
    .fn()
    .mockReturnValue("blob:archive-url");
  (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = jest.fn();
});

afterEach(() => {
  jest.restoreAllMocks();
  global.fetch = ORIGINAL_FETCH;
});

describe("packagesApi.download", () => {
  it("names the file after the dirName, not the Content-Disposition header", () => {
    const clicked = captureAnchorClicks();
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      // Deliberately different from the dirName: this path must ignore it.
      headers: { get: () => 'attachment; filename="server-chosen.zip"' },
      blob: async () => new Blob(["PK"]),
    }) as unknown as typeof fetch;

    return packagesApi.download("curio.example-ui@1").then(() => {
      expect(clicked).toHaveLength(1);
      expect(clicked[0].download).toBe("curio.example-ui@1.curio.zip");
      expect(clicked[0].href).toBe("blob:archive-url");
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:archive-url");
    });
  });

  it("requests the archive endpoint for that package", async () => {
    captureAnchorClicks();
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => null },
      blob: async () => new Blob(["PK"]),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    await packagesApi.download("me.demo@2");

    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/packages/me.demo@2/archive");
  });

  it("surfaces the server's error message so the toast can show it", async () => {
    captureAnchorClicks();
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      headers: { get: () => null },
      json: async () => ({ error: "package me.missing@1 is neither installed nor in the catalog" }),
    }) as unknown as typeof fetch;

    await expect(packagesApi.download("me.missing@1")).rejects.toThrow(
      "package me.missing@1 is neither installed nor in the catalog",
    );
  });

  it("falls back to the status when the error body is unreadable", async () => {
    captureAnchorClicks();
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      headers: { get: () => null },
      json: async () => {
        throw new Error("not json");
      },
    }) as unknown as typeof fetch;

    await expect(packagesApi.download("me.demo@1")).rejects.toThrow("500");
  });

  it("does not start a download when the request fails", async () => {
    const clicked = captureAnchorClicks();
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 403,
      headers: { get: () => null },
      json: async () => ({ error: "nope" }),
    }) as unknown as typeof fetch;

    await expect(packagesApi.download("me.demo@1")).rejects.toThrow();
    expect(clicked).toHaveLength(0);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});

describe("packagesApi.uploadArchive", () => {
  const zip = () => new Blob(["PK"], { type: "application/zip" });

  const okResponse = () => ({
    ok: true,
    status: 201,
    headers: { get: () => null },
    json: async () => ({ package: { dirName: "me.demo@1" }, replacedExisting: false }),
  });

  it("posts to /upload with NO replace flag by default", async () => {
    // The drawer's onPickArchive never passes replace, and no UI path does - so a
    // duplicate coordinate is meant to 400 rather than silently overwrite an
    // installed package. A stray `?replace=true` here would make import
    // destructive.
    const fetchMock = jest.fn().mockResolvedValue(okResponse());
    global.fetch = fetchMock as unknown as typeof fetch;

    await packagesApi.uploadArchive(zip(), "pack.curio.zip");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/packages/upload");
    expect(String(url)).not.toContain("replace");
    expect(init.method).toBe("POST");
  });

  it("adds the replace flag only when explicitly asked", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse());
    global.fetch = fetchMock as unknown as typeof fetch;

    await packagesApi.uploadArchive(zip(), "pack.curio.zip", { replace: true });

    expect(String(fetchMock.mock.calls[0][0])).toContain("replace=true");
  });

  it("sends the archive as multipart under the field name the route reads", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse());
    global.fetch = fetchMock as unknown as typeof fetch;

    await packagesApi.uploadArchive(zip(), "pack.curio.zip");

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("file")).toBeTruthy();
    // Content-Type is deliberately left unset so the browser writes the
    // multipart boundary itself; forcing it breaks the parse server-side.
    expect(fetchMock.mock.calls[0][1].headers?.["Content-Type"]).toBeUndefined();
  });

  it("surfaces the duplicate-install error with its status attached", async () => {
    // The drawer keys its banner off this message, and callers branch on status.
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 400,
      headers: { get: () => null },
      json: async () => ({
        error: "package me.demo@1 already installed; pass replace=True to overwrite",
      }),
    }) as unknown as typeof fetch;

    await expect(
      packagesApi.uploadArchive(zip(), "pack.curio.zip"),
    ).rejects.toThrow("already installed");

    try {
      await packagesApi.uploadArchive(zip(), "pack.curio.zip");
    } catch (err) {
      expect((err as { status?: number }).status).toBe(400);
    }
  });
});

