/**
 * A Simple View card reads a collection's files through the dataflow of the
 * canvas, by the rule its Data Catalog lists with (`useAgentsDataflowId`): the
 * owner's canvas the dataflow it saves, an invited editor's the dataflow its
 * route opened, a watcher's none. The backend then serves an editor the files
 * of a collection the owner's dataflow lists, from her store, where with no
 * dataflow it answers 404: the card's thumbnail, and the signed link its Play
 * asks for.
 *
 * The test draws the same collection row on three canvases of alice's
 * dataflow, hers, an editor's and a watcher's, and compares what each asked.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";

jest.mock("reactflow", () => ({ useEdges: () => [{ source: "up", target: "sv-1" }] }));
jest.mock("../../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
let mockFlow: Record<string, unknown> = {};
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    workflowNameRef: { current: "wf" },
    updateDataNode: jest.fn(),
    projectId: null,
    viewerMode: "owner",
    ...mockFlow,
  }),
}));
// The tab's role in the dataflow's room.
let mockRole: string | null = null;
jest.mock("../../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    connected: false,
    users: [],
    lockedNodes: {},
    role: mockRole,
    onRemote: () => () => undefined,
  }),
}));
jest.mock("../../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../../services/api", () => ({ fetchData: jest.fn() }));
jest.mock("../../../utils/backendUrl", () => ({ backendUrl: () => "http://backend.test" }));
const mockApiFetch = jest.fn();
jest.mock("../../../utils/authApi", () => ({
  getToken: () => "tok-123",
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

import { useSimpleVisBehavior } from "../../../adapters/node/simpleVisBehavior";
import { clearCurrentProject, setCurrentProject } from "../../../registry/projectPackagesStore";

const ALICES = "alices-dataflow";
const SURVEY = "imported.xsurvey";
const CLIP = "b".repeat(16);
const THUMBNAIL = `/api/datasets/${SURVEY}/media/${CLIP}?variant=thumb`;
const LINK = `/api/datasets/${SURVEY}/media/${CLIP}/link`;

/** A row of alice's survey collection, as `curio_load_collection` gives it. */
const COLLECTION_ROWS = {
  dataType: "dataframe",
  data: {
    name: { 0: "clip_01.mp4" },
    kind: { 0: "video" },
    dataset_id: { 0: SURVEY },
    file_id: { 0: CLIP },
    thumbnail: { 0: THUMBNAIL },
  },
};

const nodeState = { setOutput: jest.fn() } as any;

function SimpleView() {
  const { contentComponent } = useSimpleVisBehavior(
    {
      nodeId: "sv-1",
      input: COLLECTION_ROWS,
      outputCallback: jest.fn(),
      interactionsCallback: jest.fn(),
    } as any,
    nodeState,
  );
  return <>{contentComponent}</>;
}

type Canvas = "owner" | "editor" | "watcher";

/** Three tabs on alice's dataflow, each opened from its route. Only hers saves
 *  it, so only hers has the flow state's `projectId`. */
const CANVASES: Record<Canvas, { flow: Record<string, unknown>; role: string | null }> = {
  owner: { flow: { projectId: ALICES, viewerMode: "owner" }, role: "owner" },
  editor: { flow: { projectId: null, viewerMode: "shared" }, role: "editor" },
  watcher: { flow: { projectId: null, viewerMode: "shared" }, role: "watcher" },
};

let fetched: string[] = [];

beforeEach(() => {
  fetched = [];
  (global as any).fetch = jest.fn((url: string) => {
    fetched.push(String(url).replace("http://backend.test", ""));
    return Promise.resolve({ ok: true, blob: () => Promise.resolve(new Blob()) });
  });
  (global as any).URL.createObjectURL = jest.fn(() => "blob:stub");
  (global as any).URL.revokeObjectURL = jest.fn();
  mockApiFetch.mockReset();
  mockApiFetch.mockResolvedValue({ url: "/api/media/signed-token" });
});

afterEach(() => {
  clearCurrentProject();
  mockFlow = {};
  mockRole = null;
});

test("a collection's thumbnail and Play read through the dataflow on the owner's canvas and an editor's, and through none on a watcher's", async () => {
  const seen = {} as Record<Canvas, { thumbnail: string[]; link: string[] }>;
  for (const canvas of Object.keys(CANVASES) as Canvas[]) {
    mockFlow = CANVASES[canvas].flow;
    mockRole = CANVASES[canvas].role;
    setCurrentProject(ALICES, []);
    fetched = [];
    mockApiFetch.mockClear();
    let view!: ReturnType<typeof render>;
    await act(async () => {
      view = render(<SimpleView />);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Play clip_01.mp4" }));
    });
    seen[canvas] = {
      thumbnail: Array.from(new Set(fetched)),
      link: Array.from(new Set(mockApiFetch.mock.calls.map(([path]) => String(path)))),
    };
    view.unmount();
  }

  expect(seen).toEqual({
    owner: {
      thumbnail: [`${THUMBNAIL}&dataflowId=${ALICES}`],
      link: [`${LINK}?dataflowId=${ALICES}`],
    },
    editor: {
      thumbnail: [`${THUMBNAIL}&dataflowId=${ALICES}`],
      link: [`${LINK}?dataflowId=${ALICES}`],
    },
    watcher: { thumbnail: [THUMBNAIL], link: [LINK] },
  });
});
