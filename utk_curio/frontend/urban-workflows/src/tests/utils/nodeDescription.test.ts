/**
 * Which node kinds can offer help, and what the short form of it is (#225).
 *
 * The issue asks for an info button on Spatial Join. The help text it wants
 * already existed: ``packages/curio.builtin@1/manifest.json`` documents the two
 * input handles, the join direction and the output columns, and
 * ``buildDescriptor`` copies it onto the descriptor. Nothing rendered it,
 * because nothing on the node opened ``DescriptionModal``.
 */
import {
  hasNodeDescription,
  nodeDescriptionSummary,
} from "../../utils/nodeDescription";

const withDescription = (description: unknown) =>
  ({ description }) as unknown as Parameters<typeof hasNodeDescription>[0];

describe("hasNodeDescription", () => {
  test("true when the kind documents itself", () => {
    expect(hasNodeDescription(withDescription("Tag each point with its polygon."))).toBe(true);
  });

  test("false when there is nothing to show", () => {
    // An info button that opens an empty panel is worse than no button, so
    // blank-but-present counts as absent.
    for (const empty of [undefined, null, "", "   "]) {
      expect(hasNodeDescription(withDescription(empty))).toBe(false);
    }
    expect(hasNodeDescription(undefined)).toBe(false);
    expect(hasNodeDescription(null)).toBe(false);
  });
});

describe("nodeDescriptionSummary", () => {
  test("takes the first sentence", () => {
    expect(
      nodeDescriptionSummary(
        withDescription("Tag each point with the polygon it falls in. Two input handles."),
      ),
    ).toBe("Tag each point with the polygon it falls in.");
  });

  test("falls back to the whole text when there is no sentence break", () => {
    expect(nodeDescriptionSummary(withDescription("Joins points to polygons"))).toBe(
      "Joins points to polygons",
    );
  });

  test("is empty when there is no description", () => {
    expect(nodeDescriptionSummary(withDescription(""))).toBe("");
  });
});
