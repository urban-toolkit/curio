/**
 * The canvas's zoom and lock buttons: React Flow's Controls, drawn as they draw
 * them, the same buttons, classes and icons, but each button's words in its
 * Curio tooltip (`data-tooltip`) instead of a `title`, which drew the
 * browser's own. Its name stays the same aria-label.
 */
import React, { memo, useEffect, useState } from "react";
import { ControlButton, Panel, useReactFlow, useStore, useStoreApi, type ReactFlowState } from "reactflow";

// The icons of @reactflow/controls, as it draws them.
const PlusIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
    <path d="M32 18.133H18.133V32h-4.266V18.133H0v-4.266h13.867V0h4.266v13.867H32z" />
  </svg>
);

const MinusIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 5">
    <path d="M0 0h32v4.2H0z" />
  </svg>
);

const FitViewIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 30">
    <path d="M3.692 4.63c0-.53.4-.938.939-.938h5.215V0H4.708C2.13 0 0 2.054 0 4.63v5.216h3.692V4.631zM27.354 0h-5.2v3.692h5.17c.53 0 .984.4.984.939v5.215H32V4.631A4.624 4.624 0 0027.354 0zm.954 24.83c0 .532-.4.94-.939.94h-5.215v3.768h5.215c2.577 0 4.631-2.13 4.631-4.707v-5.139h-3.692v5.139zm-23.677.94c-.531 0-.939-.4-.939-.94v-5.138H0v5.139c0 2.577 2.13 4.707 4.708 4.707h5.138V25.77H4.631z" />
  </svg>
);

const LockIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 25 32">
    <path d="M21.333 10.667H19.81V7.619C19.81 3.429 16.38 0 12.19 0 8 0 4.571 3.429 4.571 7.619v3.048H3.048A3.056 3.056 0 000 13.714v15.238A3.056 3.056 0 003.048 32h18.285a3.056 3.056 0 003.048-3.048V13.714a3.056 3.056 0 00-3.048-3.047zM12.19 24.533a3.056 3.056 0 01-3.047-3.047 3.056 3.056 0 013.047-3.048 3.056 3.056 0 013.048 3.048 3.056 3.056 0 01-3.048 3.047zm4.724-13.866H7.467V7.619c0-2.59 2.133-4.724 4.723-4.724 2.591 0 4.724 2.133 4.724 4.724v3.048z" />
  </svg>
);

const UnlockIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 25 32">
    <path d="M21.333 10.667H19.81V7.619C19.81 3.429 16.38 0 12.19 0c-4.114 1.828-1.37 2.133.305 2.438 1.676.305 4.42 2.59 4.42 5.181v3.048H3.047A3.056 3.056 0 000 13.714v15.238A3.056 3.056 0 003.048 32h18.285a3.056 3.056 0 003.048-3.048V13.714a3.056 3.056 0 00-3.048-3.047zM12.19 24.533a3.056 3.056 0 01-3.047-3.047 3.056 3.056 0 013.047-3.048 3.056 3.056 0 013.048 3.048 3.056 3.056 0 01-3.048 3.047z" />
  </svg>
);

const interactiveOf = (s: ReactFlowState) => s.nodesDraggable || s.nodesConnectable || s.elementsSelectable;
const atMinZoom = (s: ReactFlowState) => s.transform[2] <= s.minZoom;
const atMaxZoom = (s: ReactFlowState) => s.transform[2] >= s.maxZoom;

function CanvasControlsInner() {
  const store = useStoreApi();
  // As React Flow's: drawn from the second render on.
  const [isVisible, setIsVisible] = useState(false);
  const isInteractive = useStore(interactiveOf);
  const minZoomReached = useStore(atMinZoom);
  const maxZoomReached = useStore(atMaxZoom);
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  useEffect(() => {
    setIsVisible(true);
  }, []);
  if (!isVisible) return null;
  const toggleInteractivity = () => {
    store.setState({
      nodesDraggable: !isInteractive,
      nodesConnectable: !isInteractive,
      elementsSelectable: !isInteractive,
    });
  };
  return (
    <Panel className="react-flow__controls" position="bottom-left" data-testid="rf__controls">
      <ControlButton
        onClick={() => zoomIn()}
        className="react-flow__controls-zoomin"
        data-tooltip="zoom in"
        aria-label="zoom in"
        disabled={maxZoomReached}
      >
        <PlusIcon />
      </ControlButton>
      <ControlButton
        onClick={() => zoomOut()}
        className="react-flow__controls-zoomout"
        data-tooltip="zoom out"
        aria-label="zoom out"
        disabled={minZoomReached}
      >
        <MinusIcon />
      </ControlButton>
      <ControlButton
        className="react-flow__controls-fitview"
        onClick={() => fitView()}
        data-tooltip="fit view"
        aria-label="fit view"
      >
        <FitViewIcon />
      </ControlButton>
      <ControlButton
        className="react-flow__controls-interactive"
        onClick={toggleInteractivity}
        data-tooltip="toggle interactivity"
        aria-label="toggle interactivity"
      >
        {isInteractive ? <UnlockIcon /> : <LockIcon />}
      </ControlButton>
    </Panel>
  );
}

export const CanvasControls = memo(CanvasControlsInner);

export default CanvasControls;
