/**
 * The handle at a node's bottom-right corner resizes the node, and only an
 * owner resizes: a read-only canvas (`useSharedView`, the rule MainCanvas and
 * the top bar read) keeps every node at its size. There the handle is not
 * drawn, nothing listens for a drag, and a drag at the corner changes nothing.
 */
import React, { useRef } from "react";
import { render } from "@testing-library/react";

const mockFlow: { viewerMode: "owner" | "shared" } = { viewerMode: "owner" };
const mockCollab = { enabled: false };

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));

import { NodeResizeHandle } from "../../components/nodes/NodeResizeHandle";

type Sized = (width: number, height: number) => void;

/** A node's box beside its corner handle, as NodeContainer draws them. */
function Card({ onResize, onResizeEnd }: { onResize: Sized; onResizeEnd: Sized }) {
  const box = useRef<HTMLDivElement>(null);
  return (
    <div>
      <NodeResizeHandle nodeId="n1" box={box} onResize={onResize} onResizeEnd={onResizeEnd} />
      <div ref={box} id="n1resizable" style={{ width: "525px", height: "350px" }} />
    </div>
  );
}

function draw() {
  const onResize = jest.fn();
  const onResizeEnd = jest.fn();
  const view = render(<Card onResize={onResize} onResizeEnd={onResizeEnd} />);
  const box = document.getElementById("n1resizable") as HTMLElement;
  // jsdom lays nothing out, so the box's offset size is read from its style.
  Object.defineProperty(box, "offsetWidth", { configurable: true, get: () => parseFloat(box.style.width) || 0 });
  Object.defineProperty(box, "offsetHeight", { configurable: true, get: () => parseFloat(box.style.height) || 0 });
  return { view, box, onResize, onResizeEnd, handle: () => document.getElementById("n1resizer") };
}

/** Press at `target`, move the pointer 120 right and 80 down, release, then
 *  move it on, as a drag from the corner does. */
function dragFrom(target: Element) {
  target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 600, clientY: 400 }));
  window.dispatchEvent(new MouseEvent("mousemove", { clientX: 660, clientY: 440 }));
  window.dispatchEvent(new MouseEvent("mousemove", { clientX: 720, clientY: 480 }));
  window.dispatchEvent(new MouseEvent("mouseup", { clientX: 720, clientY: 480 }));
  window.dispatchEvent(new MouseEvent("mousemove", { clientX: 800, clientY: 520 }));
}

const size = (box: HTMLElement) => [box.style.width, box.style.height];

afterEach(() => {
  mockFlow.viewerMode = "owner";
  mockCollab.enabled = false;
});

describe("a node's corner handle", () => {
  test("on an owner's canvas, a drag from it resizes the node and keeps the size it ends at", () => {
    const { box, onResize, onResizeEnd, handle } = draw();
    expect(handle()).not.toBeNull();
    dragFrom(handle() as HTMLElement);
    expect(size(box)).toEqual(["645px", "430px"]);
    expect(onResize).toHaveBeenLastCalledWith(645, 430);
    expect(onResizeEnd).toHaveBeenCalledTimes(1);
    expect(onResizeEnd).toHaveBeenCalledWith(645, 430);
  });

  test("on a read-only canvas, it is not drawn and a drag at the node's corner changes no size", () => {
    mockFlow.viewerMode = "shared";
    const { box, onResize, onResizeEnd, handle } = draw();
    expect(handle()).toBeNull();
    dragFrom(box);
    expect(size(box)).toEqual(["525px", "350px"]);
    expect(onResize).not.toHaveBeenCalled();
    expect(onResizeEnd).not.toHaveBeenCalled();
  });

  test("a canvas that turns read-only drops the handle, and a drag then changes no size", () => {
    const { view, box, onResize, onResizeEnd, handle } = draw();
    const owned = handle() as HTMLElement;
    expect(owned).not.toBeNull();
    mockFlow.viewerMode = "shared";
    view.rerender(<Card onResize={onResize} onResizeEnd={onResizeEnd} />);
    expect(handle()).toBeNull();
    dragFrom(owned);
    dragFrom(box);
    expect(size(box)).toEqual(["525px", "350px"]);
    expect(onResize).not.toHaveBeenCalled();
    expect(onResizeEnd).not.toHaveBeenCalled();
  });

  test("with collaboration on, another user's dataflow is not read-only, and the handle resizes", () => {
    mockFlow.viewerMode = "shared";
    mockCollab.enabled = true;
    const { box, onResizeEnd, handle } = draw();
    expect(handle()).not.toBeNull();
    dragFrom(handle() as HTMLElement);
    expect(size(box)).toEqual(["645px", "430px"]);
    expect(onResizeEnd).toHaveBeenCalledWith(645, 430);
  });
});
