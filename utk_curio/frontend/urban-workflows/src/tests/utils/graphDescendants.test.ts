import { descendantsOf } from "../../utils/graphDescendants";

test("every node after a node along data edges, not along interaction edges", () => {
  const edges = [
    { source: "a", target: "b", sourceHandle: "out", targetHandle: "in" },
    { source: "b", target: "c", sourceHandle: "out", targetHandle: "in_1" },
    { source: "a", target: "c", sourceHandle: "out", targetHandle: "in" },
    { source: "c", target: "a", sourceHandle: "in/out", targetHandle: "in/out" },
    { source: "x", target: "a", sourceHandle: "out", targetHandle: "in" },
    { source: "a", target: "pool", sourceHandle: "in/out", targetHandle: "in/out" },
  ];
  expect(descendantsOf("a", edges).sort()).toEqual(["b", "c"]);
  expect(descendantsOf("c", edges)).toEqual([]);
});
