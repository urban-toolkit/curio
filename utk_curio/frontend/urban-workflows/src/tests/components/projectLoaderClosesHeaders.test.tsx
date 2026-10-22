/**
 * A node's header keeps its categories open while the dataflow is open (#662),
 * and the next dataflow opened starts with every header closed: one opened
 * from the projects page, a new one, or a file File > Load picked, its node ids
 * the same as the last one's or not.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";

const mockLoadProject = jest.fn();
const mockLoadTrill = jest.fn();

let mockRouteId = "new";

jest.mock("react-router-dom", () => ({
  useParams: () => ({ id: mockRouteId }),
  useNavigate: () => jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    loadProject: mockLoadProject,
    loadSharedProject: jest.fn(),
    setOutputs: jest.fn(),
    hydrateRestoredOutputs: jest.fn(),
    loadParsedTrill: jest.fn(),
    projectId: null,
    attachLatestRun: jest.fn(),
    markDirty: jest.fn(),
  }),
}));
jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: mockLoadTrill }),
}));
jest.mock("../../providers/packages/useEnsureWorkflowDeps", () => ({
  useEnsureWorkflowDeps: () => jest.fn(),
}));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: { reset: jest.fn() },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  clearCurrentProject: jest.fn(),
  beginProjectLoad: jest.fn(),
  settleProjectLoad: jest.fn(),
  setCurrentProject: jest.fn(),
  setUnsavedDataflow: jest.fn(),
  setCurrentProjectPackages: jest.fn(),
}));
jest.mock("../../services/packages", () => ({
  packagesApi: { getDefaults: jest.fn().mockResolvedValue({ packages: [] }) },
}));

import { ProjectLoader } from "../../components/ProjectLoader";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import { openDataflowFile, takeOpenedDataflowFile } from "../../utils/openedDataflowFile";
import { headerRow, openCategory } from "../_support/stripCategories";

const FIRST_ID = "11111111-2222-3333-4444-555555555555";
const SECOND_ID = "66666666-7777-8888-9999-000000000000";
const SPEC = { dataflow: { name: "Shadows", nodes: [{ id: "chart" }], edges: [] } };

// The same node id in every dataflow: a copy of one keeps its nodes' ids.
const canvas = () => (
  <ProjectLoader>
    <ReferenceStrip nodeId="chart" widgets={[{ name: "y", type: "text", default: "y" }]} onInsert={jest.fn()} />
  </ProjectLoader>
);

const widgetsOpen = (container: HTMLElement) => headerRow(container).find((entry) => entry.category === "widgets")?.open;

beforeEach(() => {
  jest.clearAllMocks();
  takeOpenedDataflowFile();
  mockLoadProject.mockResolvedValue({ spec: SPEC, outputs: [] });
  mockLoadTrill.mockReturnValue({ nodes: [], edges: [] });
});

test("a category opened stays open while the dataflow is open, and closes when another dataflow opens", async () => {
  mockRouteId = FIRST_ID;
  const view = render(canvas());
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalledWith(FIRST_ID));
  openCategory(view.container, "widgets");
  view.rerender(canvas());
  expect(widgetsOpen(view.container)).toBe(true);

  mockRouteId = SECOND_ID;
  view.rerender(canvas());
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalledWith(SECOND_ID));
  expect(headerRow(view.container)).toEqual([{ category: "widgets", label: "Widgets 1", open: false }]);
});

test("a new dataflow starts with its headers closed", async () => {
  mockRouteId = FIRST_ID;
  const view = render(canvas());
  await waitFor(() => expect(mockLoadProject).toHaveBeenCalledWith(FIRST_ID));
  openCategory(view.container, "widgets");

  mockRouteId = "new";
  view.rerender(canvas());
  await waitFor(() => expect(widgetsOpen(view.container)).toBe(false));
});

test("a file File > Load picked opens with its headers closed", async () => {
  mockRouteId = "new";
  const view = render(canvas());
  openCategory(view.container, "widgets");
  expect(widgetsOpen(view.container)).toBe(true);

  act(() => openDataflowFile(SPEC));
  await waitFor(() => expect(mockLoadTrill).toHaveBeenCalledWith(SPEC));
  expect(widgetsOpen(view.container)).toBe(false);
});
