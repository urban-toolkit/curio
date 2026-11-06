"""A run whose input is rows handed on as they are says so (#1333).

A node that hands on its rows as they are, ``{data, dataType}``, reaches a
chart, which reads them in the browser, but no run: a run reads only a stored
output. A Python or JavaScript node behind it used to fail with "nothing
arrived on input circle 0 ... Check the nodes feeding this one", though the
node feeding it had run. The run now names the cause and asks nothing of the
sandbox. A bundle of several inputs is read either way, and a reference or
code that reads no input is not this case.
"""

from unittest import mock

from utk_curio.backend.app.execution import node_exec

ROWS = {"data": {"name": ["Alpha", "Bravo"], "height": [30, 24]}, "dataType": "dataframe"}


def _run(code: str, input_) -> node_exec.NodeRun:
    return node_exec.NodeRun.from_request_json({
        "code": code, "nodeType": "curio.builtin/computation-analysis", "nodeId": "reader", "input": input_,
    })


def test_python_code_that_reads_rows_handed_on_as_they_are_is_told_why():
    message = node_exec.inline_rows_problem(_run("    print(input_0)\n    return input_0\n", ROWS), language="python")

    assert message == (
        "This node's code reads `input_0`, but the node feeding it handed on its rows "
        "without storing them, so this node cannot read them. That node must store its "
        "output first, with window.curio.storeOutput, and hand on the reference it answers."
    )


def test_javascript_code_is_told_the_same():
    message = node_exec.inline_rows_problem(_run("return input_0.length;", ROWS), language="javascript")

    assert message is not None and message.startswith("This node's code reads `input_0`")


def test_a_reference_a_bundle_and_code_that_reads_no_input_are_not_this_case():
    code = "    return input_0\n"
    for input_ in (
        {"path": "1792169042468_bd44c99d", "dataType": "dataframe"},
        {"filename": "1792169042468_bd44c99d", "dataType": "dataframe", "data": ROWS["data"]},
        {"dataType": "outputs", "data": [{"path": "a"}, ROWS]},
        "",
        None,
    ):
        assert node_exec.inline_rows_problem(_run(code, input_), language="python") is None, input_
    assert node_exec.inline_rows_problem(_run("    return 1\n", ROWS), language="python") is None


def test_the_run_answers_with_the_message_and_never_asks_the_sandbox():
    with mock.patch.object(node_exec, "sandbox_request") as sandbox:
        reply, status = node_exec._execute(None, "a-token", _run("    return input_0\n", ROWS), language="python")

    sandbox.assert_not_called()
    assert status == 200
    assert reply["stderr"].startswith("This node's code reads `input_0`, but the node feeding it handed on its rows")
    assert reply["output"] == {"path": "", "dataType": "str"}
