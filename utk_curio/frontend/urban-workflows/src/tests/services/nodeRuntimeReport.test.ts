import {
  reportFromNodeOutput,
  reportNodeRuntime,
  resetNodeRuntimeReports,
} from "../../services/nodeRuntimeReport";

/**
 * dev/135: the client's half of the journal. A render must never be delayed,
 * failed or visibly changed by reporting its outcome, and a repeat must cost
 * nothing — so the tests are about restraint as much as about the post.
 */

const IDENTITY = { dataflowId: "p-1", nodeId: "vega-1" };
const VEGA_ERROR = "outputs is not a valid input type for the 2D Plot (Vega-Lite)";

describe("reportFromNodeOutput", () => {
  it("turns a settled error into a report carrying its message", () => {
    const report = reportFromNodeOutput(
      { code: "error", content: VEGA_ERROR },
      { ...IDENTITY, code: '{"mark": "bar"}' },
    );
    expect(report).toEqual({
      dataflowId: "p-1",
      nodeId: "vega-1",
      status: "error",
      message: VEGA_ERROR,
      outputType: "",
      code: '{"mark": "bar"}',
    });
  });

  it("turns a success into ok with what it says it produced", () => {
    const report = reportFromNodeOutput(
      { code: "success", content: "", outputType: "dataframe" },
      IDENTITY,
    );
    expect(report?.status).toBe("ok");
    expect(report?.outputType).toBe("dataframe");
    expect(report?.message).toBe("");
  });

  it("does NOT report the transient running state", () => {
    // A render in flight is not an outcome, and the record would be
    // overwritten by the real one a moment later.
    expect(reportFromNodeOutput({ code: "exec", content: "" }, IDENTITY)).toBeNull();
    expect(reportFromNodeOutput({ code: "", content: "" }, IDENTITY)).toBeNull();
    expect(reportFromNodeOutput(undefined, IDENTITY)).toBeNull();
  });

  it("carries the kind a renderer stamped, and none when there is none", () => {
    // dev/136: an empty render travels as itself, so the harness reads a field
    // rather than matching the message's prose.
    const empty = reportFromNodeOutput(
      { code: "error", content: "rendered nothing — 0 rows arrived", kind: "empty-render:no-input-rows" },
      IDENTITY,
    );
    expect(empty?.kind).toBe("empty-render:no-input-rows");
    const threw = reportFromNodeOutput({ code: "error", content: "boom" }, IDENTITY);
    expect(threw).not.toHaveProperty("kind");
  });

  it("never reports an error with no message at all", () => {
    const report = reportFromNodeOutput({ code: "error", content: "   " }, IDENTITY);
    expect(report?.message).toBe("This node reported an error without a message.");
  });
});

describe("reportNodeRuntime", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    resetNodeRuntimeReports();
    (global as any).fetch = jest.fn().mockResolvedValue({ ok: true, status: 204 });
  });

  afterEach(() => {
    (global as any).fetch = originalFetch;
  });

  it("posts the outcome to the journal route", async () => {
    const sent = await reportNodeRuntime({
      ...IDENTITY, status: "error", message: VEGA_ERROR, durationMs: 12,
    });
    expect(sent).toBe(true);
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(String(url)).toContain("/nodeRuntime");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({
      dataflowId: "p-1", nodeId: "vega-1", status: "error", message: VEGA_ERROR,
      durationMs: 12,
    });
  });

  it("deduplicates the same outcome and re-reports a changed one", async () => {
    await reportNodeRuntime({ ...IDENTITY, status: "error", message: VEGA_ERROR });
    expect(await reportNodeRuntime({ ...IDENTITY, status: "error", message: VEGA_ERROR }))
      .toBe(false);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    // A real change always reports.
    await reportNodeRuntime({ ...IDENTITY, status: "ok", outputType: "dataframe" });
    expect(global.fetch).toHaveBeenCalledTimes(2);
    // …and the same node can report the first outcome again after a reset.
    resetNodeRuntimeReports("p-1::vega-1");
    await reportNodeRuntime({ ...IDENTITY, status: "ok", outputType: "dataframe" });
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });

  it("spends no request without a project or a node to write against", async () => {
    expect(await reportNodeRuntime({ dataflowId: "", nodeId: "n", status: "ok" })).toBe(false);
    expect(await reportNodeRuntime({ dataflowId: "p", nodeId: "", status: "ok" })).toBe(false);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("never rejects when the endpoint fails", async () => {
    (global as any).fetch = jest.fn().mockRejectedValue(new Error("offline"));
    await expect(
      reportNodeRuntime({ ...IDENTITY, status: "error", message: "boom" }),
    ).resolves.toBe(true);
  });

  it("posts the kind and re-reports when only the kind changed", async () => {
    await reportNodeRuntime({ ...IDENTITY, status: "error", message: "rendered nothing",
                              kind: "empty-render:nothing-drawn" });
    const body = JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body);
    expect(body.kind).toBe("empty-render:nothing-drawn");
    // The same sentence with a different CAUSE is a different outcome.
    await reportNodeRuntime({ ...IDENTITY, status: "error", message: "rendered nothing",
                              kind: "empty-render:no-input-rows" });
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("bounds the message it sends", async () => {
    await reportNodeRuntime({ ...IDENTITY, status: "error", message: "e".repeat(9000) });
    const body = JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body);
    expect(body.message.length).toBeLessThanOrEqual(2000);
  });
});
