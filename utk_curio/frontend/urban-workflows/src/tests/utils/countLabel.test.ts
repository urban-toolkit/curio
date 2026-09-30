import { countLabel } from "../../utils/countLabel";

// Labels read "1 edges" and "1 templates" when the count was one (#508).
describe("countLabel", () => {
  test("one takes the singular", () => {
    expect(countLabel(1, "node")).toBe("1 node");
  });

  test("none and many take the plural", () => {
    expect(countLabel(0, "connection")).toBe("0 connections");
    expect(countLabel(3, "template")).toBe("3 templates");
  });

  test("an irregular plural can be given", () => {
    expect(countLabel(2, "entry", "entries")).toBe("2 entries");
  });
});
