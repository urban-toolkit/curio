import {
  resolveNodeDisplayLabel,
  resolveComputedInstallTitle,
} from "../../utils/palettePackageFactoryDraft";
import { NodeType } from "../../constants";
import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";

/** A package template as the registry holds one, with only what naming reads. */
function descriptor(id: string, label: string): NodeDescriptor {
  const [packageId] = id.split("/");
  return {
    id,
    source: "package",
    package: { packageId, major: 1, version: "1.0.0" },
    category: "computation",
    label,
    icon: {} as never,
    inputPorts: [],
    outputPorts: [],
    editor: "code",
    inPalette: true,
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
  } as unknown as NodeDescriptor;
}

describe("resolveNodeDisplayLabel (node-type → display name)", () => {
  test("derives a non-empty label from the node type", () => {
    // A real (non-numeric) node type always resolves to a non-empty name; in the
    // running app the populated registry maps it to a human label (e.g. "Data
    // Transformation"), here it falls back to the type slug.
    expect(resolveNodeDisplayLabel({ nodeType: NodeType.DATA_TRANSFORMATION })).toBeTruthy();
  });

  test("a custom node title (packageTemplateLabel) wins over the type label", () => {
    expect(
      resolveNodeDisplayLabel({
        nodeType: NodeType.DATA_TRANSFORMATION,
        packageTemplateLabel: "My Cleaner",
      }),
    ).toBe("My Cleaner");
  });

  test("a purely numeric nodeType uses the node title instead of the number", () => {
    expect(
      resolveNodeDisplayLabel({
        nodeType: "1782498496720" as unknown as NodeType,
        packageTemplateLabel: "Join Step",
      }),
    ).toBe("Join Step");
  });

  test("a numeric nodeType with no node title falls back to the raw value", () => {
    expect(
      resolveNodeDisplayLabel({ nodeType: "1782498496720" as unknown as NodeType }),
    ).toBe("1782498496720");
  });
});

describe("resolveNodeDisplayLabel names a node as a run on the server does (#775)", () => {
  afterEach(() => clearPackageNodes());

  test("a registered template's label names its node, versioned or not", () => {
    registerNode(descriptor("ai.test.names/zonal-mean@1", "Zonal Mean"));
    expect(resolveNodeDisplayLabel({ nodeType: "ai.test.names/zonal-mean@1" as any })).toBe("Zonal Mean");
    expect(resolveNodeDisplayLabel({ nodeType: "ai.test.names/zonal-mean" as any })).toBe("Zonal Mean");
  });

  test("a renamed header wins over a registered template's label", () => {
    registerNode(descriptor("ai.test.names/zonal-mean@1", "Zonal Mean"));
    expect(
      resolveNodeDisplayLabel({
        nodeType: "ai.test.names/zonal-mean@1" as any,
        packageTemplateLabel: "Mean by tract",
      }),
    ).toBe("Mean by tract");
  });

  test("with no template registered, the type in words, without its version", () => {
    // Not the raw "ai.test.names/heat-index-stats@2": a save before the
    // registry loads would title the computed dataset with it.
    expect(
      resolveNodeDisplayLabel({ nodeType: "ai.test.names/heat-index-stats@2" as any }),
    ).toBe("Heat Index Stats");
  });
});

describe("resolveComputedInstallTitle (node title sent on (re)install)", () => {
  test("resolves a computed dataset's producer node type to a non-empty title", () => {
    // In the running app the populated registry maps the type to a human label.
    expect(
      resolveComputedInstallTitle({
        origin: "computed",
        producerNodeType: NodeType.DATA_TRANSFORMATION,
      }),
    ).toBeTruthy();
  });

  test("returns undefined for non-computed datasets", () => {
    expect(
      resolveComputedInstallTitle({ origin: "imported", producerNodeType: NodeType.DATA_TRANSFORMATION }),
    ).toBeUndefined();
  });

  test("returns undefined when no producer node type is known", () => {
    expect(resolveComputedInstallTitle({ origin: "computed" })).toBeUndefined();
    expect(
      resolveComputedInstallTitle({ origin: "computed", producerNodeType: null }),
    ).toBeUndefined();
  });

  test("returns undefined for a purely numeric producer node type (no title on the item)", () => {
    // Nothing meaningful to send — let the backend fall back to manifest/dirName.
    expect(
      resolveComputedInstallTitle({ origin: "computed", producerNodeType: "1782498496720" }),
    ).toBeUndefined();
  });
});
