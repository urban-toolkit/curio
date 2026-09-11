/**
 * The drag-hover store (#296).
 *
 * The dedupe case is the load-bearing one: `dragover` fires continuously, and
 * the whole reason this is a store rather than an event is that a pointer
 * resting on one edge must cost nothing.
 */
import {
  clearAgentDropHover,
  getAgentDropHoverEdgeId,
  setAgentDropHoverEdgeId,
  subscribeAgentDropHover,
} from "../../utils/agentDropHover";

afterEach(() => clearAgentDropHover());

describe("agentDropHover", () => {
  it("starts with nothing hovered", () => {
    expect(getAgentDropHoverEdgeId()).toBeNull();
  });

  it("reads back what was set", () => {
    setAgentDropHoverEdgeId("edge-1");
    expect(getAgentDropHoverEdgeId()).toBe("edge-1");
  });

  it("notifies subscribers when the hovered edge changes", () => {
    const listener = jest.fn();
    subscribeAgentDropHover(listener);
    setAgentDropHoverEdgeId("edge-1");
    expect(listener).toHaveBeenCalledTimes(1);
    setAgentDropHoverEdgeId("edge-2");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("does NOT notify when set to the value it already holds", () => {
    // This is the whole point. Without it, every dragover event while the
    // pointer sits on one edge would re-render that edge.
    const listener = jest.fn();
    setAgentDropHoverEdgeId("edge-1");
    subscribeAgentDropHover(listener);
    setAgentDropHoverEdgeId("edge-1");
    setAgentDropHoverEdgeId("edge-1");
    expect(listener).not.toHaveBeenCalled();
  });

  it("clearing is setting null, and is also deduped", () => {
    const listener = jest.fn();
    subscribeAgentDropHover(listener);
    clearAgentDropHover();
    expect(listener).not.toHaveBeenCalled();

    setAgentDropHoverEdgeId("edge-1");
    clearAgentDropHover();
    expect(getAgentDropHoverEdgeId()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("stops delivering after unsubscribe", () => {
    const listener = jest.fn();
    const unsubscribe = subscribeAgentDropHover(listener);
    unsubscribe();
    setAgentDropHoverEdgeId("edge-1");
    expect(listener).not.toHaveBeenCalled();
  });

  it("notifies every subscriber, and one unsubscribing leaves the others", () => {
    const first = jest.fn();
    const second = jest.fn();
    const unsubscribeFirst = subscribeAgentDropHover(first);
    subscribeAgentDropHover(second);
    setAgentDropHoverEdgeId("edge-1");
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);

    unsubscribeFirst();
    setAgentDropHoverEdgeId("edge-2");
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(2);
  });
});
