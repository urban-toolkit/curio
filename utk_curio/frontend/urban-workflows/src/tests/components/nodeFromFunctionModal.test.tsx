import fs from "fs";
import path from "path";
import React from "react";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * New node from a Python function (#662, step 21: SCOUT's Compute Catalog,
 * the Curio way).
 *
 * The dialog lists the functions installed packages' modules define, starts
 * each parameter at what the backend suggests, asks the backend to write the
 * template, and adds it to a package the way Save as package node does: the
 * same destination picker, the same draft builder (`buildTemplateInstallDraft`)
 * and the same install (`installDraftToProject`: the factory, then the
 * project's lockfile, then the registry). A template written into another
 * package than the function's depends on the function's package.
 */

const mockListFunctions = jest.fn();
const mockFunctionTemplate = jest.fn();
const mockListInstalled = jest.fn();
const mockFactoryInstall = jest.fn();
const mockInstallToProject = jest.fn();
const mockSetCurrentProjectPackages = jest.fn();
const mockRefreshRegistry = jest.fn();
const mockEnsureProjectId = jest.fn();
const mockShowToast = jest.fn();
const mockPaletteTypes: { current: unknown[] } = { current: [] };

jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: {
    listFunctions: (...args: unknown[]) => mockListFunctions(...args),
    functionTemplate: (...args: unknown[]) => mockFunctionTemplate(...args),
    listInstalled: (...args: unknown[]) => mockListInstalled(...args),
    factoryInstall: (...args: unknown[]) => mockFactoryInstall(...args),
    installToProject: (...args: unknown[]) => mockInstallToProject(...args),
  },
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: (...args: unknown[]) => mockRefreshRegistry(...args),
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  setCurrentProjectPackages: (...args: unknown[]) => mockSetCurrentProjectPackages(...args),
}));
jest.mock("../../registry", () => ({
  getPaletteNodeTypes: () => mockPaletteTypes.current,
  subscribeToRegistry: () => () => {},
}));
jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: () => undefined,
}));
jest.mock("../../providers/StarterProvider", () => ({
  useStarterContext: () => ({ getStarters: () => [] }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ ensureProjectId: mockEnsureProjectId }),
}));

import { NodeFromFunctionModal } from "../../components/packages/editing/NodeFromFunctionModal";

const SOURCE_DIR = "ai.test.fnsrc@1";
const SCALE_KEY = `${SOURCE_DIR}|fn_scale.ops|scale`;

function functionsPayload(readOnly: boolean) {
  return {
    packages: [{
      dirName: SOURCE_DIR,
      packageId: "ai.test.fnsrc",
      major: 1,
      name: "Function source",
      readOnly,
      modules: [
        { module: "fn_broken", problem: "fn_broken does not parse: line 1: invalid syntax", functions: [] },
        {
          module: "fn_scale.ops",
          problem: null,
          functions: [
            {
              name: "scale",
              doc: "Scale a value.",
              problem: null,
              parameters: [
                { name: "value", kind: "positional-or-keyword", annotation: null, hasDefault: false, widget: null, use: "input" },
                {
                  name: "factor", kind: "positional-or-keyword", annotation: "int", hasDefault: true, defaultText: "2",
                  widget: { name: "factor", type: "number", label: "Factor", default: 2, options: { step: 1 } },
                  use: "widget",
                },
                {
                  name: "label", kind: "keyword-only", annotation: null, hasDefault: true, defaultText: "os.sep",
                  widget: null, use: "default",
                },
              ],
            },
            {
              name: "spread", doc: "", parameters: [],
              problem: "spread takes *values, any number of values; a node calls a function whose parameters each have a name.",
            },
          ],
        },
      ],
    }],
  };
}

const WRITTEN = {
  template: {
    id: "scale-it", label: "Scale it", category: "computation", engine: "python", editor: "code",
    behavior: "code", iconRef: "fa-brands:python", description: "Scale a value. Calls scale from fn_scale.ops.",
    hasCode: true, hasWidgets: true, hasGrammar: false,
    inputPorts: [{ types: ["VALUE"], cardinality: "1" }],
    outputPorts: [{ types: ["VALUE"], cardinality: "[1,n]" }],
    source: "sources/scale-it.py",
    widgets: [{ name: "factor", type: "number", label: "Factor", default: 2, options: { step: 1 } }],
  },
  source: {
    filename: "scale-it.py",
    code: "from fn_scale.ops import scale\n\nreturn scale(\n    value=[!! input 0 !!],\n    factor=[!! factor !!],\n    label='scaled',\n)\n",
  },
  package: { dirName: SOURCE_DIR, packageId: "ai.test.fnsrc", major: 1, readOnly: false },
  dependency: { [SOURCE_DIR]: "*" },
};

const INSTALLED_SOURCE = {
  packageId: "ai.test.fnsrc", major: 1, version: "1.0.0", name: "Function source", publisher: "Test",
  description: "", license: "MIT", permissions: [],
  dependencies: { python: { numpy: "*" }, js: {}, packages: {} },
  templates: [{
    templateId: "caller", label: "Caller", category: "computation", engine: "python", editor: "code",
    description: "", hasCode: true, hasWidgets: false, hasGrammar: false,
    inputPorts: [], outputPorts: [{ types: ["JSON"], cardinality: "1" }], source: "sources/caller.py",
  }],
  dirName: SOURCE_DIR, lineage: null, familyKey: SOURCE_DIR, channel: "stable",
};

beforeEach(() => {
  jest.clearAllMocks();
  mockPaletteTypes.current = [];
  mockListFunctions.mockResolvedValue(functionsPayload(true));
  mockFunctionTemplate.mockResolvedValue(WRITTEN);
  mockFactoryInstall.mockImplementation(async (envelope: { manifest: { id: string; name: string } }) => ({
    package: { dirName: `${envelope.manifest.id}@1`, name: envelope.manifest.name, templates: [] },
  }));
  mockInstallToProject.mockImplementation(async (_project: string, dirName: string) => ({ packages: [dirName] }));
  mockEnsureProjectId.mockResolvedValue("project-1");
  mockRefreshRegistry.mockResolvedValue(undefined);
});

async function openAndPick(onClose = jest.fn(), onSaved = jest.fn()) {
  render(<NodeFromFunctionModal show onClose={onClose} onSaved={onSaved} />);
  const choice = await screen.findByLabelText("Function");
  await waitFor(() => expect(within(choice).getByRole("option", { name: "fn_scale.ops.scale(value, factor, label)" })).toBeInTheDocument());
  fireEvent.change(choice, { target: { value: SCALE_KEY } });
  return { onClose, onSaved };
}

describe("New node from a Python function", () => {
  test("lists the functions the modules define, and why one cannot be picked", async () => {
    render(<NodeFromFunctionModal show onClose={jest.fn()} />);
    const choice = await screen.findByLabelText("Function");
    const scale = await within(choice).findByRole("option", { name: "fn_scale.ops.scale(value, factor, label)" });
    expect(scale).not.toBeDisabled();
    const spread = within(choice).getByRole("option", { name: "fn_scale.ops.spread()" });
    expect(spread).toBeDisabled();
    expect(spread).toHaveAttribute("title", expect.stringContaining("takes *values"));
    expect(within(choice).getByRole("option", { name: /^fn_broken: fn_broken does not parse/ })).toBeDisabled();
    expect(within(choice).getByRole("group", { name: "Function source" })).toBeInTheDocument();
  });

  test("starts each parameter at its suggestion, and a read-only package's function in a new package", async () => {
    await openAndPick();
    expect(screen.getByLabelText("What value is given")).toHaveValue("input");
    expect(screen.getByLabelText("What factor is given")).toHaveValue("widget");
    expect(screen.getByLabelText("What label is given")).toHaveValue("default");
    // Only a parameter with a default offers it.
    expect(within(screen.getByLabelText("What value is given")).queryByRole("option", { name: /^Its default/ })).toBeNull();
    expect(screen.getByText("Number, starting at 2")).toBeInTheDocument();
    expect(screen.getByText("The node's input 0.")).toBeInTheDocument();
    expect(screen.getByLabelText("Node name")).toHaveValue("Scale");
    expect(screen.getByLabelText("Destination package")).toHaveValue("__save_as_new__");
  });

  test("writes the template and adds it to a new package that depends on the function's package", async () => {
    const { onClose, onSaved } = await openAndPick();
    fireEvent.change(screen.getByLabelText("What label is given"), { target: { value: "fixed" } });
    fireEvent.change(screen.getByLabelText("Value of label"), { target: { value: "'scaled'" } });
    fireEvent.change(screen.getByLabelText("Node name"), { target: { value: "Scale it" } });
    fireEvent.change(screen.getByLabelText("New package name"), { target: { value: "My functions" } });
    const order: string[] = [];
    mockInstallToProject.mockImplementation(async (_p: string, dirName: string) => {
      order.push("project");
      return { packages: [dirName] };
    });
    mockRefreshRegistry.mockImplementation(async () => {
      order.push("refresh");
    });
    fireEvent.click(screen.getByRole("button", { name: "Create node" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mockFunctionTemplate).toHaveBeenCalledWith({
      dirName: SOURCE_DIR,
      module: "fn_scale.ops",
      function: "scale",
      label: "Scale it",
      bindings: {
        value: { use: "input" },
        factor: { use: "widget", widget: { name: "factor", type: "number", label: "Factor", default: 2, options: { step: 1 } } },
        label: { use: "fixed", value: "'scaled'" },
      },
    });
    const envelope = mockFactoryInstall.mock.calls[0][0];
    expect(envelope.replace).toBeUndefined();
    expect(envelope.manifest.id).toMatch(/^curio\.canvas\.draft\./);
    expect(envelope.manifest.name).toBe("My functions");
    expect(envelope.manifest.dependencies.packages).toEqual({ [SOURCE_DIR]: "*" });
    expect(envelope.manifest.templates).toEqual([
      expect.objectContaining({
        id: "scale-it",
        label: "Scale it",
        editor: "code",
        behavior: "code",
        source: "sources/scale-it.py",
        inputPorts: [{ types: ["VALUE"], cardinality: "1" }],
        widgets: WRITTEN.template.widgets,
      }),
    ]);
    expect(envelope.sources).toEqual({ "scale-it": { filename: "scale-it.py", code: WRITTEN.source.code } });
    const dirName = `${envelope.manifest.id}@1`;
    expect(mockInstallToProject).toHaveBeenCalledWith("project-1", dirName);
    expect(mockSetCurrentProjectPackages).toHaveBeenCalledWith([dirName]);
    expect(order).toEqual(["project", "refresh"]);
    expect(mockShowToast).toHaveBeenCalledWith(expect.stringContaining('Added "Scale it" to My functions.'), "success");
    expect(onSaved).toHaveBeenCalledWith(dirName);
  });

  test("into the function's own package, it replaces that package and adds no dependency", async () => {
    mockListFunctions.mockResolvedValue(functionsPayload(false));
    mockListInstalled.mockResolvedValue({ packages: [INSTALLED_SOURCE] });
    mockPaletteTypes.current = [{
      id: "ai.test.fnsrc/caller@1", label: "Caller", source: "package", category: "computation",
      package: { packageId: "ai.test.fnsrc", major: 1, name: "Function source", readOnly: false },
    }];
    const { onClose } = await openAndPick();
    expect(screen.getByLabelText("Destination package")).toHaveValue(SOURCE_DIR);
    fireEvent.click(screen.getByRole("button", { name: "Create node" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const envelope = mockFactoryInstall.mock.calls[0][0];
    expect(envelope.replace).toBe(true);
    expect(envelope.manifest.id).toBe("ai.test.fnsrc");
    expect(envelope.manifest.dependencies.packages).toEqual({});
    expect(envelope.manifest.dependencies.python).toEqual({ numpy: "*" });
    expect(envelope.manifest.templates.map((t: { id: string }) => t.id)).toEqual(["caller", "scale-it"]);
    expect(mockInstallToProject).toHaveBeenCalledWith("project-1", SOURCE_DIR);
  });

  test("the widget form edits a parameter's widget", async () => {
    await openAndPick();
    fireEvent.change(screen.getByLabelText("What value is given"), { target: { value: "widget" } });
    const row = document.querySelector('[data-function-parameter="value"]') as HTMLElement;
    expect(within(row).getByText("Text, starting at")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "Edit widget" }));
    // The name is the parameter's: the code's reference names it.
    expect(within(row).getByLabelText("Widget name")).toBeDisabled();
    fireEvent.change(within(row).getByLabelText("Widget type"), { target: { value: "number" } });
    fireEvent.change(within(row).getByLabelText("Widget default"), { target: { value: "21" } });
    // Creating waits for the open form.
    expect(screen.getByRole("button", { name: "Create node" })).toBeDisabled();
    fireEvent.click(within(row).getByRole("button", { name: "Save widget" }));
    expect(within(row).getByText("Number, starting at 21")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create node" }));
    await waitFor(() => expect(mockFunctionTemplate).toHaveBeenCalled());
    expect(mockFunctionTemplate.mock.calls[0][0].bindings.value).toEqual({
      use: "widget", widget: { name: "value", type: "number", label: "Value", default: 21 },
    });
  });

  test("Save as package node goes through the same picker, draft builder and install", () => {
    const read = (rel: string) => fs.readFileSync(path.join(__dirname, "..", "..", rel), "utf8");
    for (const file of [
      "components/packages/editing/NodeSaveAsModal.tsx",
      "components/packages/editing/NodeFromFunctionModal.tsx",
    ]) {
      const source = read(file);
      expect(source).toContain("<PackageTargetPicker");
      expect(source).toContain("installDraftToProject(buildFactoryInstallEnvelope(");
    }
    const drafts = read("utils/palettePackageFactoryDraft.ts");
    for (const builder of ["buildSaveAsInstallDraft", "buildFunctionInstallDraft"]) {
      const body = drafts.slice(drafts.indexOf(`export function ${builder}(`));
      expect(body.slice(0, body.indexOf("\n}\n"))).toContain("buildTemplateInstallDraft({");
    }
  });

  test("a refusal stays in the dialog, and nothing is installed", async () => {
    mockFunctionTemplate.mockRejectedValue(new Error("The value of label, 'two', is not a Python literal."));
    const { onClose } = await openAndPick();
    fireEvent.click(screen.getByRole("button", { name: "Create node" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("is not a Python literal");
    expect(onClose).not.toHaveBeenCalled();
    expect(mockFactoryInstall).not.toHaveBeenCalled();
  });
});
