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

describe("NodeTemplateConfigModal - seeding", () => {
  test("seeds every field from the descriptor", () => {
    renderModal();
    expect(screen.getByLabelText("Node title")).toHaveValue("Demo Kind");
    expect(screen.getByLabelText("Description")).toHaveValue(
      "Descriptor description",
    );
    expect(screen.getByLabelText("Editor mode")).toHaveValue("code");
    expect(screen.getByLabelText("Engine")).toHaveValue("python");
    expect(screen.getByLabelText("hasCode")).toBeChecked();
    expect(screen.getByLabelText("hasGrammar")).not.toBeChecked();
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
    expect(screen.getByLabelText("hasGrammar")).toBeChecked();
    expect(screen.getByLabelText("hasCode")).not.toBeChecked();
    expect(screen.getByLabelText("hasWidgets")).not.toBeChecked();
    // Still an editor with a body, so an explanation still makes sense.
    expect(screen.getByLabelText("Explanation tab")).toBeEnabled();

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
    expect(screen.getByLabelText("hasCode")).toBeChecked();
    expect(screen.getByLabelText("hasWidgets")).toBeChecked();
    expect(screen.getByLabelText("hasGrammar")).not.toBeChecked();

    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ editor: "widgets", hasWidgets: true, hasCode: true }),
    );
  });

  test("none clears every body flag and disables the Explanation tab", () => {
    renderModal();
    fireEvent.click(screen.getByLabelText("Explanation tab"));
    fireEvent.change(screen.getByLabelText("Editor mode"), {
      target: { value: "none" },
    });

    expect(screen.getByLabelText("hasCode")).not.toBeChecked();
    expect(screen.getByLabelText("hasWidgets")).not.toBeChecked();
    expect(screen.getByLabelText("hasGrammar")).not.toBeChecked();
    // With no code and no grammar there is nothing to explain, so the flag is
    // forced off as well as disabled - a disabled-but-checked box would save a
    // value the user can no longer see or change.
    expect(screen.getByLabelText("Explanation tab")).toBeDisabled();
    expect(screen.getByLabelText("Explanation tab")).not.toBeChecked();
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
    expect(screen.getByLabelText("hasCode")).toBeChecked();
    expect(screen.getByLabelText("hasGrammar")).not.toBeChecked();
  });
});

describe("NodeTemplateConfigModal - port editor", () => {
  test("adds, edits and removes rows, and saves what is on screen", () => {
    const { onSave } = renderModal();
    const inputs = portSection("Input ports");

    expect(within(inputs).getAllByRole("combobox")).toHaveLength(1);
    fireEvent.change(within(inputs).getAllByRole("textbox")[0], {
      target: { value: "DATAFRAME" },
    });
    fireEvent.change(within(inputs).getAllByRole("combobox")[0], {
      target: { value: "1" },
    });

    fireEvent.click(within(inputs).getByRole("button", { name: "+ Add port" }));
    expect(within(inputs).getAllByRole("combobox")).toHaveLength(2);
    fireEvent.change(within(inputs).getAllByRole("textbox")[1], {
      target: { value: "JSON" },
    });
    fireEvent.change(within(inputs).getAllByRole("combobox")[1], {
      target: { value: "[0,1]" },
    });

    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        inputPorts: [
          expect.objectContaining({ types: "DATAFRAME", cardinality: "1" }),
          expect.objectContaining({ types: "JSON", cardinality: "[0,1]" }),
        ],
      }),
    );
  });

  test("the row remove button drops only that row", () => {
    const { onSave } = renderModal();
    const inputs = portSection("Input ports");

    fireEvent.click(within(inputs).getByRole("button", { name: "+ Add port" }));
    fireEvent.change(within(inputs).getAllByRole("textbox")[1], {
      target: { value: "KEEP_ME" },
    });
    // Remove row 0; the appended row must survive with its edit intact.
    fireEvent.click(within(inputs).getAllByRole("button", { name: "✕" })[0]);

    save();
    const config = onSave.mock.calls[0][0];
    expect(config.inputPorts).toHaveLength(1);
    expect(config.inputPorts[0].types).toBe("KEEP_ME");
  });

  test("input and output sections are independent", () => {
    const { onSave } = renderModal();
    fireEvent.click(
      within(portSection("Output ports")).getByRole("button", {
        name: "+ Add port",
      }),
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
      within(portSection("Output ports")).getAllByRole("combobox"),
    ).toHaveLength(1);
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
