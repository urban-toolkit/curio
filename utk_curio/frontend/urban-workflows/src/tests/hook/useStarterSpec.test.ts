/**
 * How every grammar node fills an empty editor from its input: the Vega-Lite
 * node's rules, shared with the Autark node.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { useStarterSpec } from "../../hook/useStarterSpec";
import type { GrammarInput } from "../../utils/grammarInput";

const INPUT = { dataType: "dataframe", data: { a: [1] } };
const READ: GrammarInput = { frames: [] };

function setup(initial: { input?: unknown; buffer?: string; written?: string } = {}) {
  const read = jest.fn().mockResolvedValue(READ);
  const choose = jest.fn().mockReturnValue('{"mark": "bar"}');
  const hook = renderHook(
    (props: { input?: unknown; buffer?: string; written?: string }) =>
      useStarterSpec({ input: props.input, buffer: props.buffer, written: props.written, read, choose }),
    { initialProps: initial },
  );
  return { ...hook, read, choose };
}

describe("useStarterSpec", () => {
  test("an edge alone carries no schema: nothing until an input arrives", async () => {
    const { result, read } = setup({ input: "" });
    await act(async () => {});
    expect(read).not.toHaveBeenCalled();
    expect(result.current).toBeUndefined();
  });

  test("fills an empty editor once an input arrives", async () => {
    const { result, read } = setup({ input: INPUT, buffer: "" });
    await waitFor(() => expect(result.current).toBe('{"mark": "bar"}'));
    expect(read).toHaveBeenCalledWith(INPUT);
  });

  test("never over text the user has typed", async () => {
    const { result, read } = setup({ input: INPUT, buffer: '{"mark": "line"}' });
    await act(async () => {});
    expect(read).not.toHaveBeenCalled();
    expect(result.current).toBeUndefined();
  });

  test("once per node: a later input does not fill again", async () => {
    const { result, rerender, read } = setup({ input: INPUT, buffer: "" });
    await waitFor(() => expect(result.current).toBeDefined());
    rerender({ input: { ...INPUT }, buffer: "" });
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(1);
  });

  test("steps aside for a document written in from outside", async () => {
    const { result, rerender } = setup({ input: INPUT, buffer: "" });
    await waitFor(() => expect(result.current).toBeDefined());
    rerender({ input: INPUT, buffer: "", written: '{"mark": "area"}' });
    expect(result.current).toBeUndefined();
  });

  test("a ladder with nothing to offer leaves the editor empty", async () => {
    const read = jest.fn().mockResolvedValue(READ);
    const { result } = renderHook(() =>
      useStarterSpec({ input: INPUT, buffer: "", written: undefined, read, choose: () => null }),
    );
    await act(async () => {});
    expect(result.current).toBeUndefined();
  });
});
