/**
 * A save the server never answers gives up after 2 minutes. Saves of the open
 * dataflow go through one queue, so a save left waiting forever would hold
 * every save behind it. The request is aborted, and the save rejects with a
 * sentence callers show as it is.
 */
import { projectsApi } from "../../api/projectsApi";

const TWO_MINUTES = 2 * 60 * 1000;
const realFetch = global.fetch;

/** A fetch that never answers, and rejects as a browser's does once aborted. */
function unansweredFetch(): jest.Mock {
  return jest.fn(
    (_url: string, opts: RequestInit = {}) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      }),
  );
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  jest.useRealTimers();
  global.fetch = realFetch;
});

describe("a save the server never answers", () => {
  it.each<[string, () => Promise<unknown>]>([
    ["an update", () => projectsApi.update("proj-1", { spec: {} })],
    ["a create", () => projectsApi.create({ name: "wf", spec: {}, outputs: [] })],
  ])("%s gives up after 2 minutes with a message a person can read", async (_kind, save) => {
    const fetchMock = unansweredFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    let outcome: unknown = "waiting";
    save().then(
      () => {
        outcome = "answered";
      },
      (err: unknown) => {
        outcome = err;
      },
    );

    await jest.advanceTimersByTimeAsync(TWO_MINUTES - 1);
    expect(outcome).toBe("waiting");

    await jest.advanceTimersByTimeAsync(1);
    expect(outcome).toBeInstanceOf(Error);
    const message = (outcome as Error).message;
    expect(message).toMatch(/longer than 2 minutes/);
    expect(message).toMatch(/save again/);
    expect(message).not.toMatch(/abort/i);
    // The request itself is cut off, not just left behind.
    const sent = fetchMock.mock.calls[0][1] as RequestInit;
    expect(sent.signal?.aborted).toBe(true);
  });
});

describe("a save the server answers in time", () => {
  it("returns the answer and leaves no timer behind", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "proj-1" }),
    }) as unknown as typeof fetch;

    await expect(projectsApi.update("proj-1", { spec: {} })).resolves.toEqual({ id: "proj-1" });
    expect(jest.getTimerCount()).toBe(0);
  });

  it("still reports the server's own refusal", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ error: "Reload the project." }),
    }) as unknown as typeof fetch;

    await expect(projectsApi.update("proj-1", { spec: {} })).rejects.toMatchObject({
      message: "Reload the project.",
      status: 409,
    });
    expect(jest.getTimerCount()).toBe(0);
  });
});
