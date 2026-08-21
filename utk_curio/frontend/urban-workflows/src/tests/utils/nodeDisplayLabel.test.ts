import {
  resolveNodeDisplayLabel,
  resolveComputedInstallTitle,
} from "../../utils/palettePackageFactoryDraft";
import { NodeType } from "../../constants";

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
