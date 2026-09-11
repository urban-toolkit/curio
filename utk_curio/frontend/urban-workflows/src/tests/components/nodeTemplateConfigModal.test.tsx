import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * The Node settings modal is step one of making a package: whatever it emits
 * becomes ``packageTemplateConfig`` on the canvas node, which
 * ``templateDraftFromCanvasNode`` later merges into the factory draft. Nothing
 * tested it at any layer.
 *
 * The e2e round trip (``test_package_metadata_roundtrip_e2e.py``) drives the
 * fields that reach the manifest and leaves the editor-mode dropdown on
 * ``code``, because changing it fires a cascade that rewrites four other
 * controls. That cascade is pure local state, so it belongs here rather than in
 * a browser: this file owns it, plus the port editor and the two checkboxes
 * that are deliberately canvas-local.
 */

jest.mock("reactflow", () => ({}));

const mockTryGetNodeDescriptor = jest.fn();
jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: (...args: unknown[]) => mockTryGetNodeDescriptor(...args),
}));

import { NodeTemplateConfigModal } from "../../components/packages/editing/NodeTemplateConfigModal";

const descriptor = (over: Record<string, any> = {}) =>
  ({
    id: "acme.demo/kind",
    label: "Demo Kind",
    description: "Descriptor description",
    category: "computation",
    editor: "code",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    hasProvenance: true,
    inputPorts: [{ types: ["DATAFRAME"], cardinality: "[1,n]" }],
    outputPorts: [{ types: ["JSON"], cardinality: "1" }],
    package: { source: "sources/demo.py" },
    ...over,
  }) as any;

function renderModal(over: Record<string, any> = {}) {
  const onSave = jest.fn();
  const onClose = jest.fn();
  render(
    <NodeTemplateConfigModal
      show
      nodeId="node-1"
      nodeType={"acme.demo/kind" as any}
      storedConfig={null}
      templateCode="return []"
      onClose={onClose}
      onSave={onSave}
      {...over}
    />,
  );
  return { onSave, onClose };
}

/** The ``TemplatePortEditor`` block for one section, keyed by its heading. */
const portSection = (title: string) =>
  screen.getByText(title).parentElement as HTMLElement;

const save = () =>
  fireEvent.click(screen.getByRole("button", { name: /^Save as package node/ }));

beforeEach(() => {
  mockTryGetNodeDescriptor.mockReset();
  mockTryGetNodeDescriptor.mockReturnValue(descriptor());
});

describe("NodeTemplateConfigModal - capability labels", () => {
  test("the checkboxes are named for what they do, not for their field", () => {
    // They rendered as `hasCode` / `hasWidgets` / `hasGrammar` (#219). The
    // input is wrapped in its label, so the visible text WAS the accessible
    // name: the internal identifier was what a screen reader read out too.
    renderModal();
    for (const label of ["Code", "Widgets", "Grammar"]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    for (const field of ["hasCode", "hasWidgets", "hasGrammar"]) {
      expect(screen.queryByLabelText(field)).toBeNull();
    }
  });
});

describe("NodeTemplateConfigModal - seeding", () => {
  test("seeds every field from the descriptor", () => {
    renderModal();
    expect(screen.getByLabelText("Node title")).toHaveValue("Demo Kind");
    expect(screen.getByLabelText("Description")).toHaveValue(
      "Descriptor description",
    );
    expect(screen.getByLabelText("Editor mode")).toHaveValue("code");
    expect(screen.getByLabelText("Engine")).toHaveValue("python");
    expect(screen.getByLabelText("Code")).toBeChecked();
    expect(screen.getByLabelText("Grammar")).not.toBeChecked();
  });

  test("a stored config wins over the descriptor", () => {
    // The round trip that matters on reopen: whatever the user configured last
    // time is what they should see, not the descriptor's defaults.
    renderModal({
      storedConfig: { description: "Edited earlier", label: "Edited Label" },
    });
    expect(screen.getByLabelText("Description")).toHaveValue("Edited earlier");
    expect(screen.getByLabelText("Node title")).toHaveValue("Edited Label");
  });

  test("a read-only package is badged", () => {
    mockTryGetNodeDescriptor.mockReturnValue(
      descriptor({ package: { source: "sources/demo.py", readOnly: true } }),
    );
    renderModal();
    expect(screen.getByText("Read-only")).toBeInTheDocument();
  });

  test("renders nothing when the node type has no descriptor", () => {
    mockTryGetNodeDescriptor.mockReturnValue(undefined);
    const { container } = render(
      <NodeTemplateConfigModal
        show
        nodeId="node-1"
        nodeType={"acme.missing/kind" as any}
        storedConfig={null}
        templateCode=""
        onClose={jest.fn()}
        onSave={jest.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Node settings")).toBeNull();
  });
});

describe("NodeTemplateConfigModal - editor mode cascade", () => {
  test("grammar forces javascript and clears code/widgets", () => {
    const { onSave } = renderModal();
    fireEvent.change(screen.getByLabelText("Editor mode"), {
      target: { value: "grammar" },
    });

    expect(screen.getByLabelText("Engine")).toHaveValue("javascript");
    expect(screen.getByLabelText("Grammar")).toBeChecked();
    expect(screen.getByLabelText("Code")).not.toBeChecked();
    expect(screen.getByLabelText("Widgets")).not.toBeChecked();

    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        editor: "grammar",
        engine: "javascript",
        hasGrammar: true,
        hasCode: false,
        hasWidgets: false,
      }),
    );
  });

  test("widgets keeps code on and turns widgets on", () => {
    const { onSave } = renderModal();
    fireEvent.change(screen.getByLabelText("Editor mode"), {
      target: { value: "widgets" },
    });
    expect(screen.getByLabelText("Code")).toBeChecked();
    expect(screen.getByLabelText("Widgets")).toBeChecked();
    expect(screen.getByLabelText("Grammar")).not.toBeChecked();

    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ editor: "widgets", hasWidgets: true, hasCode: true }),
    );
  });

  test("none clears every body flag", () => {
    // The Explanation-tab flag used to be asserted here too. That tab is gone -
    // agent.node-explainer does the same job with more context - so there is no
    // longer a body flag that depends on code-or-grammar being present.
    renderModal();
    fireEvent.change(screen.getByLabelText("Editor mode"), {
      target: { value: "none" },
    });

    expect(screen.getByLabelText("Code")).not.toBeChecked();
    expect(screen.getByLabelText("Widgets")).not.toBeChecked();
    expect(screen.getByLabelText("Grammar")).not.toBeChecked();
  });

  test("switching back to code restores python", () => {
    renderModal();
    fireEvent.change(screen.getByLabelText("Editor mode"), {
      target: { value: "grammar" },
    });
    fireEvent.change(screen.getByLabelText("Editor mode"), {
      target: { value: "code" },
    });
    expect(screen.getByLabelText("Engine")).toHaveValue("python");
    expect(screen.getByLabelText("Code")).toBeChecked();
    expect(screen.getByLabelText("Grammar")).not.toBeChecked();
  });
});

describe("NodeTemplateConfigModal - port editor", () => {
  // Ports are edited as one <select> per TYPE now, not one comma-separated text
  // field per port (#219). Queries go through the aria-labels rather than
  // positional getAllByRole, so a layout change does not silently retarget them.
  // Accessible names carry the section title, because "Port 1 type 1" on its
  // own names one control in the Input editor and another in the Output one.
  const typeSelect = (title: string, port: number, type: number) =>
    within(portSection(title)).getByLabelText(`${title} port ${port} type ${type}`);
  const cardinalitySelect = (title: string, port: number) =>
    within(portSection(title)).getByLabelText(`${title} port ${port} cardinality`);

  test("adds, edits and removes rows, and saves what is on screen", () => {
    const { onSave } = renderModal();
    const inputs = portSection("Input ports");

    fireEvent.change(typeSelect("Input ports", 1, 1), { target: { value: "DATAFRAME" } });
    fireEvent.change(cardinalitySelect("Input ports", 1), { target: { value: "1" } });

    fireEvent.click(within(inputs).getByLabelText("Add Input ports port"));
    fireEvent.change(typeSelect("Input ports", 2, 1), { target: { value: "JSON" } });
    fireEvent.change(cardinalitySelect("Input ports", 2), { target: { value: "[0,1]" } });

    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        inputPorts: [
          expect.objectContaining({ types: ["DATAFRAME"], cardinality: "1" }),
          expect.objectContaining({ types: ["JSON"], cardinality: "[0,1]" }),
        ],
      }),
    );
  });

  test("a port can carry several types, each on its own row", () => {
    // The half the free-text field made easy to get wrong: the separator was
    // stated only in a placeholder, and an unrecognised value was dropped in
    // silence on the way into the registry.
    const { onSave } = renderModal();
    const inputs = portSection("Input ports");

    fireEvent.change(typeSelect("Input ports", 1, 1), { target: { value: "DATAFRAME" } });
    fireEvent.click(within(inputs).getByLabelText("Add Input ports port 1 type"));
    fireEvent.change(typeSelect("Input ports", 1, 2), { target: { value: "GEODATAFRAME" } });

    save();
    expect(onSave.mock.calls[0][0].inputPorts[0].types).toEqual([
      "DATAFRAME",
      "GEODATAFRAME",
    ]);
  });

  test("only the declarable types are offered", () => {
    // The vocabulary is closed: ConnectionValidator compares these values
    // directly, so anything outside the enum could never match a port.
    renderModal();
    const options = within(portSection("Input ports"))
      .getByLabelText("Input ports port 1 type 1")
      .querySelectorAll("option");
    expect(Array.from(options).map((o) => o.getAttribute("value"))).toEqual([
      "DATAFRAME",
      "GEODATAFRAME",
      "VALUE",
      "LIST",
      "JSON",
      "RASTER",
    ]);
  });

  test("the last type of a port cannot be removed", () => {
    // A port with no types accepts nothing. Removing the PORT says that.
    renderModal();
    const inputs = portSection("Input ports");
    expect(
      within(inputs).getByLabelText("Remove Input ports port 1 type 1"),
    ).toBeDisabled();
  });

  test("the row remove button drops only that row", () => {
    const { onSave } = renderModal();
    const inputs = portSection("Input ports");

    fireEvent.click(within(inputs).getByLabelText("Add Input ports port"));
    fireEvent.change(typeSelect("Input ports", 2, 1), { target: { value: "RASTER" } });
    // Remove port 1; the appended one must survive with its edit intact.
    fireEvent.click(within(inputs).getByLabelText("Remove Input ports port 1"));

    save();
    const config = onSave.mock.calls[0][0];
    expect(config.inputPorts).toHaveLength(1);
    expect(config.inputPorts[0].types).toEqual(["RASTER"]);
  });

  test("input and output sections are independent", () => {
    const { onSave } = renderModal();
    fireEvent.click(
      within(portSection("Output ports")).getByLabelText("Add Output ports port"),
    );

    save();
    const config = onSave.mock.calls[0][0];
    expect(config.inputPorts).toHaveLength(1);
    expect(config.outputPorts).toHaveLength(2);
  });

  test("a descriptor with no output ports still seeds one row", () => {
    // canvasTemplateConfigFromDescriptor substitutes a JSON output rather than
    // leaving the list empty, because an empty list falls back to the
    // descriptor's own ports in applyCanvasTemplateConfigToTemplateDraft - so
    // an empty section would be silently un-saveable.
    mockTryGetNodeDescriptor.mockReturnValue(descriptor({ outputPorts: [] }));
    renderModal();
    expect(
      within(portSection("Output ports")).getByLabelText("Output ports port 1 type 1"),
    ).toHaveValue("JSON");
  });

  test("a legacy comma string opens as one row per type", () => {
    // A canvas node whose packageTemplateConfig was stored before this change
    // still carries "DATAFRAME,GEODATAFRAME" in a single field.
    mockTryGetNodeDescriptor.mockReturnValue(descriptor());
    renderModal({
      storedConfig: {
        inputPorts: [
          { id: "legacy", types: "DATAFRAME,GEODATAFRAME" as unknown as string[], cardinality: "1" },
        ],
      } as never,
    });
    const inputs = portSection("Input ports");
    expect(typeSelect("Input ports", 1, 1)).toHaveValue("DATAFRAME");
    expect(typeSelect("Input ports", 1, 2)).toHaveValue("GEODATAFRAME");
  });
});

describe("NodeTemplateConfigModal - footer", () => {
  test("Save as package node hands back the edited identity fields", () => {
    const { onSave } = renderModal();
    fireEvent.change(screen.getByLabelText("Node title"), {
      target: { value: "Configured Kind" },
    });
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Configured description" },
    });

    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        label: "Configured Kind",
        description: "Configured description",
        sourceCode: "return []",
      }),
    );
  });

  test("Cancel closes without saving", () => {
    const { onSave, onClose } = renderModal();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
