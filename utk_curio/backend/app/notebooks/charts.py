"""The Vega-Lite spec of each notebook cell that draws an Altair chart, made in
the sandbox, where node code runs.

The import's analysis (``analyzer.py``) reads the cells and runs none of them.
The cells ``analyzer.chart_cells`` names go to the sandbox's ``/exec`` as one
node's code (:func:`run_code`), under the sign-in of the person who imports,
so the run gets what a Play of theirs gets: under isolation a forked child
with seccomp, no network, the execution account, its memory budget and its
time limit, in the work directory of their account. A Play has no budget of an
account's in the backend, and neither has this run; the sandbox bounds both
alike. The backend holds the run's code as the text it sends, and runs none of
it.

In the run each chart cell runs in a namespace of its own: ``alt``, ``pd`` and
``np``, and each name it reads bound to a copy of one stand-in frame, whose
columns are the field names its strings mention and whose two rows are
numbers, so Altair can tell a shorthand field's type. Its spec is its last
variable's ``to_dict()``, without ``data`` and ``datasets``: the Vega-Lite
node reads its data from the node wired into it. A cell that raises, or whose
last variable is no chart, has no spec, and the others keep theirs.

The run's output is ``{"specs": [...]}``, a spec or None for each chart cell,
read back with ``/get``. A run that fails, outlasts its time or cannot be
asked gives no chart cell a spec, and the import goes on with each of them as
a Python node. So does a run the sandbox refuses before it starts, such as
one whose cells hold an input chip spelled the old way (``[!! input 0 !!]``).
"""

from __future__ import annotations

import json
import textwrap

from utk_curio.backend.app.execution import sandbox_client

#: The node type the run goes by in the sandbox's logs and its records.
RUN_LABEL = "notebook-import"

#: The log label of the run's requests.
_LABEL = "/api/analyzeNotebook"

#: What the run defines, before the line that calls it with the cells. Its
#: imports are inside the function, so the sandbox keeps none of them for the
#: later nodes of the session (#158).
_CONVERT = '''\
def notebook_charts(charts):
    import builtins

    import altair as alt
    import numpy as np
    import pandas as pd

    specs = []
    for chart_cell in charts:
        try:
            fields = chart_cell["fields"]
            if fields:
                frame = pd.DataFrame({name: [1, 2] for name in fields})
            else:
                frame = pd.DataFrame({"_x": [1]})
            namespace = {"alt": alt, "pd": pd, "np": np, "__builtins__": builtins}
            for name in chart_cell["names"]:
                if name not in namespace:
                    namespace[name] = frame.copy()
            exec(compile(chart_cell["code"], "<notebook_cell>", "exec"), namespace)
            chart = namespace.get(chart_cell["last_var"])
            if chart is None or not hasattr(chart, "to_dict"):
                specs.append(None)
                continue
            spec = chart.to_dict(validate=False)
            spec.pop("data", None)
            spec.pop("datasets", None)
            specs.append(spec)
        except (Exception, SystemExit):
            specs.append(None)
    return specs
'''


def run_code(charts: list[dict]) -> str:
    """The code of the sandbox's run for *charts* (``analyzer.chart_cells``):
    a node's code, the body of its ``userCode``, which returns
    ``{"specs": [...]}``. The cells are in it as a Python literal."""
    cells = [
        {key: chart[key] for key in ("code", "last_var", "names", "fields")}
        for chart in charts
    ]
    source = f"{_CONVERT}\nreturn {{'specs': notebook_charts({cells!r})}}\n"
    return textwrap.indent(source, "    ")


def altair_specs(charts: list[dict], *, user, session_token: str | None) -> dict[int, dict]:
    """The Vega-Lite spec of each of *charts* (``analyzer.chart_cells``) that
    draws one, by its cell's index: made in one run of the sandbox's
    ``/exec`` under *session_token*, the sign-in of *user*, who imports, with
    a Play's time limit. Empty when there are no charts, or when the run
    gives none."""
    if not charts:
        return {}
    from utk_curio.backend.app.api.routes import SANDBOX_GET_TIMEOUT
    from utk_curio.backend.app.execution.node_exec import SANDBOX_EXEC_TIMEOUT, exec_user_key

    body = {
        "code": run_code(charts),
        "file_path": "",
        "nodeType": RUN_LABEL,
        "dataType": "",
        "session_id": session_token,
        "save_dataset": False,
        # Under isolation, the work directory a Play of the account runs in.
        "user_key": exec_user_key(user),
    }
    try:
        reply = sandbox_client.sandbox_request(
            "post", "/exec", label=_LABEL, timeout=SANDBOX_EXEC_TIMEOUT,
            data=json.dumps(body), headers={"Content-Type": "application/json"},
        ).json()
    except (sandbox_client.SandboxTransportError, ValueError) as e:
        _note(f"the sandbox could not be asked: {e}")
        return {}
    output = reply.get("output") if isinstance(reply, dict) else None
    if not isinstance(output, dict) or not output.get("path") or reply.get("error"):
        _note(f"the run made no output: {_last_line(reply)}")
        return {}
    try:
        stored = sandbox_client.sandbox_request(
            "get", "/get", label=_LABEL, timeout=SANDBOX_GET_TIMEOUT,
            params={"fileName": output["path"], "sessionId": session_token},
        ).json()
    except (sandbox_client.SandboxTransportError, ValueError) as e:
        _note(f"the run's output could not be read: {e}")
        return {}
    data = stored.get("data") if isinstance(stored, dict) else None
    specs = data.get("specs") if isinstance(data, dict) else None
    if not isinstance(specs, list) or len(specs) != len(charts):
        _note("the run's output holds no spec for each chart cell")
        return {}
    return {chart["cell"]: spec for chart, spec in zip(charts, specs) if isinstance(spec, dict)}


def _last_line(reply) -> str:
    """The last line of what the run wrote to stderr, or of why it failed."""
    if not isinstance(reply, dict):
        return "no reply"
    text = reply.get("message") or reply.get("error") or reply.get("stderr") or ""
    lines = [line for line in str(text).splitlines() if line.strip()]
    return lines[-1][:200] if lines else "no output"


def _note(why: str) -> None:
    print(f"[notebook import] no chart cell gets a Vega-Lite spec: {why}", flush=True)
