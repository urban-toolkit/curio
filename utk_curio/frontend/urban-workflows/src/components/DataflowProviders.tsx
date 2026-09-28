import React from "react";

import FlowProvider from "../providers/FlowProvider";
import { CollaborationProvider } from "../providers/CollaborationProvider";
import StarterProvider from "../providers/StarterProvider";
import DialogProvider from "../providers/DialogProvider";
import { NodeCatalogDrawerProvider } from "../providers/NodeCatalogDrawerProvider";
import { AgentCatalogDrawerProvider } from "../providers/AgentCatalogDrawerProvider";
import { DatasetCatalogDrawerProvider } from "../providers/datasetCatalog";
import { PackagePaletteProvider } from "../providers/PackagePaletteContext";
import { DatasetPaletteProvider } from "../providers/DatasetPaletteContext";
import { ProjectLoader } from "./ProjectLoader";
import { CanvasDatasetDetailsProvider } from "./datasets/catalog/CanvasDatasetDetailsProvider";

/**
 * Everything a dataflow's nodes need, for either route that renders them.
 *
 * The canvas and the dashboard mount the same node components, so they need the
 * same providers: the node header reads the dataset palette and the starter
 * store, an unresolved node offers the node catalog, and all of those throw
 * rather than degrade when their provider is missing. One stack, so a provider
 * added for the canvas cannot be missing from the dashboard.
 *
 * ``presentation`` says which route this is. It switches three things:
 * collaboration is left out (a dashboard is a view, not a session, and
 * ``useCollab`` is a no-op outside its provider by design), ``FlowProvider``
 * publishes ``dashboardOn``, and the loader lays the graph out as tiles instead
 * of a canvas.
 */
export const DataflowProviders: React.FC<{
  children: React.ReactNode;
  presentation?: boolean;
}> = ({ children, presentation = false }) => {
  const body = (
    // CollaborationProvider must wrap FlowProvider: FlowProvider's mutation
    // handlers call ``useCollab()`` to broadcast graph changes, and a context
    // only reaches *descendants*. Putting it on the inside would hand
    // FlowProvider the no-op default value and silently drop every broadcast.
    <FlowProvider dashboardOn={presentation}>
      {/* Above the drawers and the palettes: every one of them opens a
          dataset's details through it, and the modal reads the live graph. */}
      <CanvasDatasetDetailsProvider>
      {/* NodeCatalogDrawerProvider must sit INSIDE FlowProvider: the drawer
          calls useFlowContext to auto-save unsaved dataflows on Install, and
          a portal preserves React tree context, not DOM position. Outside
          FlowProvider, useFlowContext returns no-op defaults and Install
          silently does nothing. */}
      <NodeCatalogDrawerProvider>
        <DatasetCatalogDrawerProvider>
          <AgentCatalogDrawerProvider>
            <StarterProvider>
              <ProjectLoader presentation={presentation}>
                <PackagePaletteProvider>
                  <DatasetPaletteProvider>{children}</DatasetPaletteProvider>
                </PackagePaletteProvider>
              </ProjectLoader>
            </StarterProvider>
          </AgentCatalogDrawerProvider>
        </DatasetCatalogDrawerProvider>
      </NodeCatalogDrawerProvider>
      </CanvasDatasetDetailsProvider>
    </FlowProvider>
  );

  return (
    <DialogProvider>
      {presentation ? body : <CollaborationProvider>{body}</CollaborationProvider>}
    </DialogProvider>
  );
};

export default DataflowProviders;
