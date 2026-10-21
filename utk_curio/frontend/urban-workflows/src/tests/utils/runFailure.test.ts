/**
 * What a failed run says in a node body's own line (`utils/runFailure`): a
 * traceback's last line without its exception's name, a plain message as it
 * is.
 */
import { failureLine } from "../../utils/runFailure";

describe("failureLine", () => {
  test("a traceback says its last line, without the exception's name", () => {
    expect(
      failureLine(
        "Traceback (most recent call last):\n  File \"<string>\", line 4, in userCode\n" +
          "ValueError: The dataset \"inputs\" stacks inputs of one kind, and these differ: input_0 (Baseline) is a table, input_1 (Twice as tall) is a value. Connect outcomes of the same kind.",
      ),
    ).toBe(
      "The dataset \"inputs\" stacks inputs of one kind, and these differ: input_0 (Baseline) is a table, input_1 (Twice as tall) is a value. Connect outcomes of the same kind.",
    );
  });

  test("a message that is no traceback is shown as it is", () => {
    expect(failureLine("input_1 (from Scale) has no value yet. Run the node that feeds it.")).toBe(
      "input_1 (from Scale) has no value yet. Run the node that feeds it.",
    );
  });
});
