"""One simulated user: sign up, create a dataflow, run every node, save it;
and, in a room of users, open a tab of the room's shared dataflow, type and
drag in it (``sockets.py``).

Everything here goes through the same backend endpoints the canvas calls, with
the same payload shapes, so a failure found under load is a failure a real user
could hit. Nothing talks to the sandbox directly.
"""

from __future__ import annotations

import hashlib
import json
import random
import textwrap
import threading
import time
import uuid
from dataclasses import dataclass, field

import requests

from ..test_frontend.workflow_spec import (
    PY_CODE_TYPES,
    propagate_node_input,
    resolve_node_input,
    seed_node_code,
)
from . import sockets

# Kept in step with the canvas: PythonInterpreter indents the node's source by
# four spaces (the sandbox wraps it in a function), JavaScriptInterpreter sends
# it verbatim.
PY_INDENT = "    "

AUTK_GRAMMAR = "AUTK_GRAMMAR"
JS_COMPUTATION = "JS_COMPUTATION"

# Each wait matches what the code under test itself allows, so a timeout here
# means the stack missed its own deadline rather than that the harness ran out
# of patience:
#   PY/JS   - the ceilings PythonInterpreter and JavaScriptInterpreter set on a
#             node run in the browser.
#   ARTIFACT- the backend's own deadline for a sandbox read (SANDBOX_GET_TIMEOUT
#             in backend/app/api/routes.py); a shorter one here would report
#             reads the backend was still willing to wait for.
#   API     - project create/read/save. Nothing server-side bounds these, so
#             this is a judgement: a dataflow save that takes over two minutes
#             is a failure worth seeing, not a slow success.
PY_TIMEOUT_S = 600
JS_TIMEOUT_S = 180
ARTIFACT_TIMEOUT_S = 300
API_TIMEOUT_S = 120

# How long a user waits for the rest of the tier to finish registering before
# starting anyway. Sign-up plus project creation is sub-second per user when
# it is not queued.
START_GATE_TIMEOUT_S = 300

# How long a user's tab may stay open once its dataflow work is over, a
# judgement: a tab whose dataflow work failed early still has its room's
# typing to finish, a few minutes at most in the session profile (arrivals
# spread over two, then about a minute of typing, then the settling), so one
# still open ten minutes on is stuck.
TAB_CLOSE_TIMEOUT_S = 600


@dataclass
class Pacing:
    """How a user paces itself: when it arrives and how long it pauses.

    ``burst`` (everyone at once, no pauses) is the worst case and the one the
    tiers gate on. ``session`` spreads arrivals over a ramp and pauses between
    node runs, which is what a room full of people using Curio actually looks
    like: they read a result before running the next node. The two answer
    different questions -- "can the stack survive a thundering herd" and "how
    many people can work at the same time" -- and the report says which one
    produced its numbers.

    The same goes for a user's tab: ``burst`` types at a steady pace with no
    pause, and ``session`` types at a person's pace and stops after each drag
    (``key_gap``, ``pause``).
    """

    arrival_delay: float = 0.0
    think_min: float = 0.0
    think_max: float = 0.0
    key_gap_min: float = sockets.BURST_KEY_GAP_S
    key_gap_max: float = sockets.BURST_KEY_GAP_S
    pause_min: float = 0.0
    pause_max: float = 0.0

    def think(self) -> float:
        if self.think_max <= 0:
            return 0.0
        return random.uniform(self.think_min, self.think_max)

    def key_gap(self) -> float:
        """Seconds between two keystrokes of the user's tab."""
        return random.uniform(self.key_gap_min, self.key_gap_max)

    def pause(self) -> float:
        """Seconds the tab stops typing after a drag."""
        if self.pause_max <= 0:
            return 0.0
        return random.uniform(self.pause_min, self.pause_max)


BURST = Pacing()


@dataclass
class Sample:
    """One HTTP call: what it was, how long it took, how it ended."""

    endpoint: str
    node_id: str | None
    status: int | None
    seconds: float
    ok: bool
    error: str | None = None
    kind: str | None = None  # failure taxonomy; see FAILURE_KINDS below


# http_error      - the endpoint answered non-2xx
# empty_output    - 200 with an empty output.path: the node itself failed
# timeout         - no answer inside the browser's own ceiling
# transport       - connection reset, refused, etc.
# mismatch        - ran fine, produced different bytes than the solo baseline
# socket          - a tab's socket did not connect; a join, a sync or an update
#                   was refused or not answered; or the socket closed under it
# unsynced        - an update a tab sent was not in every other tab of its room
#                   sockets.SETTLE_TIMEOUT_S after the room's last update
# diverged        - with every update in every tab, a tab's nodes' code and
#                   places differed from the room's first tab's
FAILURE_KINDS = ("http_error", "empty_output", "timeout", "transport", "mismatch",
                 "socket", "unsynced", "diverged")


@dataclass
class UserResult:
    user: str
    example: str
    started_at: float
    seconds: float = 0.0
    completed: bool = False
    samples: list[Sample] = field(default_factory=list)
    outputs: dict[str, dict] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)
    #: What the user's tab did (``sockets.Tab.summary``), when it had one.
    tab: dict = field(default_factory=dict)

    @property
    def failures(self) -> list[Sample]:
        return [s for s in self.samples if not s.ok]


class UserFailed(Exception):
    """A user's session ended early. The Sample already records the reason."""


# The Accept header the sandbox answers with an Arrow IPC stream instead of
# JSON. The canvas does not send it yet; this is how the harness measures what
# it would cost if it did.
ARROW_IPC_MIME = "application/vnd.apache.arrow.stream"

# Geometry rides as WKB on the Arrow path, so the sandbox refuses a
# geodataframe unless the client says it can take it. The harness digests the
# response bytes rather than decoding them, so accepting WKB is honest: what
# it measures is the cost of producing and shipping the artifact. Without
# this, every spatial example in the mix comes back 415 -- which is how the
# first Arrow tier failed, on example 01 of all things.
ARROW_GEOMETRY_HEADERS = {"X-Curio-Accept-Geometry": "wkb"}


def arrow_artifact_hash(content: bytes, headers) -> str:
    """Digest of an Arrow response: the bytes, plus the metadata headers.

    The headers carry what the JSON body used to carry inline (kind, row
    counts, which columns are JSON-encoded), so leaving them out would let a
    change in them pass unnoticed. ``X-Curio-Filename`` is dropped because it
    is minted per execution: hashing it would report every user as a mismatch.

    The baseline and the tiers are digested the same way in the same run,
    which is what makes them comparable.
    """
    metadata = sorted(
        (k.lower(), v) for k, v in headers.items()
        if k.lower().startswith("x-curio-") and k.lower() != "x-curio-filename"
    )
    digest = hashlib.sha256(content)
    digest.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


class VirtualUser:
    """A single user's session against one Curio backend."""

    def __init__(
        self,
        backend_url: str,
        name: str,
        example: str,
        spec_json: dict,
        workflow,
        autk_code: dict[str, str],
        *,
        seed: int = 42,
        compare_to: dict[str, str] | None = None,
        password: str = "stress-pass-1234",
        register_gate=None,
        start_gate=None,
        pacing: "Pacing" = BURST,
        room: "sockets.Room | None" = None,
        namespace: str | None = None,
    ):
        self.backend_url = backend_url.rstrip("/")
        self.name = name
        self.example = example
        self.spec_json = spec_json
        self.workflow = workflow
        self.autk_code = autk_code
        self.seed = seed
        self.compare_to = compare_to or {}
        self.password = password
        # Registration is throttled and the dataflow work is not: see
        # ``run`` for why.
        self.register_gate = register_gate
        self.start_gate = start_gate
        self.pacing = pacing
        # The room whose shared dataflow the user opens a tab of, and the
        # collaboration namespace the page reads from /api/config/public.
        self.room = room
        self.namespace = namespace
        self.session = requests.Session()
        self.token: str | None = None
        self.project_id: str | None = None
        #: Set once the user's own dataflow work is over, however it ended:
        #: its tab stays open until then.
        self.dataflow_done = threading.Event()
        self.result = UserResult(user=name, example=example, started_at=time.time())

    # -- plumbing ---------------------------------------------------------

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        path_url: str | None = None,
        node_id: str | None = None,
        timeout: float = API_TIMEOUT_S,
        expect: int | tuple[int, ...] = 200,
        accept: str | None = None,
        raw: bool = False,
        extra_headers: dict | None = None,
    ) -> dict:
        """Make one call, record a Sample, and raise UserFailed on anything bad.

        ``path`` is also the label the report groups by, so per-call values
        (artifact ids, project ids) belong in ``params``, not in it.
        """
        expected = (expect,) if isinstance(expect, int) else expect
        url = f"{self.backend_url}{path_url or path}"
        started = time.time()
        try:
            headers = self._headers()
            if accept:
                headers["Accept"] = accept
            if extra_headers:
                headers.update(extra_headers)
            resp = self.session.request(
                method, url, json=json_body, params=params,
                headers=headers, timeout=timeout,
            )
        except requests.Timeout:
            self._record(path, node_id, None, started, False,
                         f"no response in {timeout:.0f}s", "timeout")
            raise UserFailed(f"{path} timed out")
        except requests.RequestException as exc:
            self._record(path, node_id, None, started, False, str(exc)[:500], "transport")
            raise UserFailed(f"{path} transport error")

        if resp.status_code not in expected:
            self._record(path, node_id, resp.status_code, started, False,
                         resp.text[:500], "http_error")
            raise UserFailed(f"{path} returned {resp.status_code}")

        self._record(path, node_id, resp.status_code, started, True)
        if raw:
            # The Arrow path: bytes plus the headers that carry the metadata
            # the JSON body would have carried inline.
            return {"content": resp.content, "headers": dict(resp.headers)}
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}

    def _record(self, endpoint, node_id, status, started, ok, error=None, kind=None):
        self.result.samples.append(Sample(
            endpoint=endpoint, node_id=node_id, status=status,
            seconds=time.time() - started, ok=ok, error=error, kind=kind,
        ))

    def _fail(self, endpoint: str, node_id: str, message: str, kind: str) -> None:
        self.result.samples.append(Sample(
            endpoint=endpoint, node_id=node_id, status=200, seconds=0.0,
            ok=False, error=message[:2000], kind=kind,
        ))

    def socket_sample(self, label: str, seconds: float, ok: bool,
                      error: str | None = None, kind: str | None = None) -> None:
        """One step of the user's tab (``sockets.Tab``), labelled as the report
        groups it. Called from the tab's thread and its socket's."""
        self.result.samples.append(Sample(
            endpoint=label, node_id=None, status=None, seconds=seconds, ok=ok,
            error=error[:2000] if error else None, kind=kind,
        ))

    # -- session steps ----------------------------------------------------

    # -- the room -----------------------------------------------------------

    def typing_targets(self) -> list[tuple[str, str]]:
        """The nodes of this user's dataflow whose code a tab types comment
        lines into, with each language's line comment: Python first, then
        JavaScript, in the order the dataflow runs."""
        python = [(n.id, "# ") for n in self.workflow.topo_sorted_nodes() if n.type in PY_CODE_TYPES]
        javascript = [(n.id, "// ") for n in self.workflow.topo_sorted_nodes() if n.type == JS_COMPUTATION]
        return python + javascript

    def _enter_room(self) -> None:
        """Tell the room this user's account exists. The room's owner, whose
        dataflow it is, then invites the others to edit it, as the Share
        menu's Invite editors does (``projects/access.py``)."""
        room = self.room
        if room is None:
            return
        room.arrive("registered", self.name)
        if self.name != room.owner:
            return
        room.project_id = self.project_id
        room.targets = self.typing_targets()
        try:
            if self.project_id is None:
                return  # no dataflow to share: create_project says why
            if not room.wait_all("registered", sockets.ROOM_WAIT_S):
                self._fail("/api/projects/:id/editors", "",
                           f"the room's editors had not signed up after {sockets.ROOM_WAIT_S:.0f}s",
                           "timeout")
            for editor in room.registered_editors():
                try:
                    self._call("POST", "/api/projects/:id/editors",
                               path_url=f"/api/projects/{self.project_id}/editors",
                               json_body={"username": editor}, expect=201)
                except UserFailed:
                    # It would join as a watcher, whose changes the server drops.
                    room.leave(editor)
        finally:
            room.invited.set()

    def _leave_room(self) -> None:
        """This user will open no tab: the room goes on without it."""
        room = self.room
        if room is None:
            return
        room.leave(self.name)
        if self.name == room.owner:
            room.invited.set()

    def _open_tab(self) -> threading.Thread | None:
        """Open the user's tab of its room's dataflow, on a thread of its own,
        beside the user's own dataflow run."""
        if self.room is None:
            return None
        thread = threading.Thread(
            target=sockets.run_tab, args=(self, self.room),
            kwargs={"backend_url": self.backend_url, "namespace": self.namespace,
                    "pacing": self.pacing},
            name=f"tab-{self.name}", daemon=True,
        )
        thread.start()
        return thread

    def sign_up(self) -> None:
        body = self._call(
            "POST", "/api/auth/signup", expect=201,
            json_body={
                "name": self.name,
                "username": self.name,
                "password": self.password,
                "email": f"{self.name}@stress.invalid",
            },
        )
        self.token = body.get("token")
        if not self.token:
            self._fail("/api/auth/signup", "", "signup returned no token", "http_error")
            raise UserFailed("signup returned no token")

    def create_project(self) -> None:
        spec = json.loads(json.dumps(self.spec_json))
        title = f"{spec.get('name', self.example)} ({self.name})"
        spec["name"] = title
        spec.setdefault("dataflow", {})["name"] = title
        body = self._call(
            "POST", "/api/projects", expect=201,
            json_body={"name": title, "spec": spec},
        )
        self.project_id = body.get("id")

    def run_nodes(self) -> None:
        outputs = self.result.outputs
        for node in self.workflow.topo_sorted_nodes():
            if node.type in PY_CODE_TYPES:
                self._run_python(node, outputs)
            elif node.type == JS_COMPUTATION:
                self._run_js(node, outputs)
            elif node.type == AUTK_GRAMMAR and node.id in self.autk_code:
                self._run_autk(node, outputs)
            else:
                # Browser-only or passive: forward what is above it, exactly as
                # the programmatic E2E runner does.
                propagated = propagate_node_input(self.workflow, node.id, outputs)
                if propagated is not None:
                    outputs[node.id] = propagated
                continue

            # A person looks at what a node produced before running the next
            # one. Zero under the burst profile.
            pause = self.pacing.think()
            if pause:
                time.sleep(pause)

    def save_and_reload(self) -> None:
        """Save the run's outputs onto the project, then read it back."""
        if not self.project_id:
            return
        outputs = [
            {"node_id": nid, "filename": ref["path"], "data_type": ref.get("dataType")}
            for nid, ref in self.result.outputs.items()
            if isinstance(ref.get("path"), str) and ref["path"]
        ]
        self._call("PUT", "/api/projects/:id", json_body={"outputs": outputs},
                   path_url=f"/api/projects/{self.project_id}")
        self._call("GET", "/api/projects/:id",
                   path_url=f"/api/projects/{self.project_id}")

    def run(self) -> UserResult:
        """Register, then run the dataflow alongside everybody else.

        Registration is concurrent like everything else. ``register_gate``
        exists to cap it (``--register-concurrency``) for a run that wants to
        isolate the dataflow work from the sign-up burst; it is off by default.

        ``start_gate`` then lines the registered users up so their dataflow
        work starts together rather than as each one finishes signing up.

        In a room, the user's tab of the room's dataflow opens as its own
        dataflow work starts, on a thread of its own, and closes once that
        work is over; the user completed if both ended with no failure.
        """
        started = time.time()
        tab = None
        dataflow_ok = False
        try:
            if self.register_gate is not None:
                with self.register_gate:
                    self.sign_up()
                    self.create_project()
            else:
                self.sign_up()
                self.create_project()
            self._enter_room()
            self._wait_at_start_gate()
            if self.pacing.arrival_delay:
                # Arrivals are spread from the same starting line rather than
                # staggered thread by thread, so the offsets stay meaningful.
                time.sleep(self.pacing.arrival_delay)
            tab = self._open_tab()
            self.run_nodes()
            self.save_and_reload()
            dataflow_ok = True
        except UserFailed:
            self._release_start_gate()
        except Exception as exc:  # noqa: BLE001 - a crashed driver is a finding too
            self._release_start_gate()
            self._fail("driver", "", f"{type(exc).__name__}: {exc}", "transport")
        finally:
            self.dataflow_done.set()
            if tab is not None:
                tab.join(timeout=TAB_CLOSE_TIMEOUT_S)
                if tab.is_alive():
                    self._fail("socket tab", "",
                               f"the tab was still open {TAB_CLOSE_TIMEOUT_S:.0f}s "
                               "after the user's dataflow work ended", "socket")
            else:
                self._leave_room()
        self.result.completed = dataflow_ok and not self.result.failures
        self.result.seconds = time.time() - started
        return self.result

    def _wait_at_start_gate(self) -> None:
        """Block until the other registered users are ready.

        A broken or timed-out barrier means somebody never made it this far;
        the remaining users go ahead rather than deadlock behind them.
        """
        if self.start_gate is None:
            return
        try:
            self.start_gate.wait(timeout=START_GATE_TIMEOUT_S)
        except (threading.BrokenBarrierError, RuntimeError):
            pass

    def _release_start_gate(self) -> None:
        """Let the others through after failing before the gate."""
        if self.start_gate is None:
            return
        try:
            self.start_gate.abort()
        except RuntimeError:
            pass

    # -- node execution ---------------------------------------------------

    def _run_python(self, node, outputs: dict) -> None:
        code = seed_node_code(self.workflow.node_code(node, "python"), self.seed)
        body = self._exec(
            "/processPythonCode", node,
            code=textwrap.indent(code, PY_INDENT),
            input_ref=resolve_node_input(self.workflow, node.id, outputs),
            timeout=PY_TIMEOUT_S,
        )
        if body is None:
            return
        outputs[node.id] = body
        self._compare_to_baseline(node)

    def _run_js(self, node, outputs: dict) -> None:
        body = self._exec(
            "/processJavaScriptCode", node,
            code=self.workflow.node_code(node, "javascript"),
            input_ref=resolve_node_input(self.workflow, node.id, outputs),
            timeout=JS_TIMEOUT_S,
        )
        if body is not None:
            outputs[node.id] = body

    def _run_autk(self, node, outputs: dict) -> None:
        """The half of an Autark node that does not need a browser.

        The compiled autk-db loader carries its sources inline, so it takes no
        input; the browser would render from the DuckDB artifact it returns.
        """
        body = self._exec(
            "/processJavaScriptCode", node,
            code=self.autk_code[node.id],
            input_ref={"path": "", "dataType": ""},
            timeout=JS_TIMEOUT_S,
        )
        if body is not None:
            outputs[node.id] = body

    def _exec(self, endpoint: str, node, *, code: str, input_ref: dict, timeout: float):
        """POST one node run; return its ``{path, dataType}`` or None on failure."""
        if input_ref.get("dataType") == "outputs":
            payload_input = {"dataType": "outputs", "data": input_ref["path"]}
        else:
            payload_input = {"path": input_ref["path"], "dataType": input_ref["dataType"]}
        # The wired circles, as the canvas sends them: each circle k is the
        # code's input_k.
        slots = self.workflow.input_slots(node.id) if input_ref.get("path") else []

        body = self._call(
            "POST", endpoint, node_id=node.id, timeout=timeout,
            json_body={
                "code": code,
                "input": payload_input,
                "inputTypes": [],
                "nodeType": node.raw_type,
                "nodeId": node.id,
                **({"dataflowId": self.project_id} if self.project_id else {}),
                **({"inputSlots": slots} if slots else {}),
                "saveOutputDataset": False,
            },
        )
        output = body.get("output") or {}
        if not output.get("path"):
            # The canonical failure contract: an empty path, not a non-empty
            # stderr (warnings land there on successful runs too).
            self._fail(endpoint, node.id,
                       body.get("stderr") or "node produced no output",
                       "empty_output")
            raise UserFailed(f"node {node.id} produced no output")
        return {"path": output["path"], "dataType": output.get("dataType", "")}

    # -- correctness under concurrency ------------------------------------

    def _compare_to_baseline(self, node) -> None:
        """Does this user's output match the same node run alone?

        Every user runs identical, seeded code, so the bytes must match. A
        difference means concurrency changed a result -- one user reading
        another's artifact, or an output overwritten mid-run -- which no
        latency number would reveal.

        In ``arrow`` mode this is also the measurement: the fetch is the
        expensive half of a dataflow (42% of blocked time at 100 users), and
        the Arrow path skips the pandas materialisation and the JSON encode
        that make it expensive.
        """
        ref = self.result.outputs[node.id]
        # Read as the canvas reads: on the dataflow's route, where an output
        # its owner's run kept is served (runs/kept.py), from any sign-in.
        path, path_url = "/get", None
        if self.project_id:
            path = "/api/projects/:id/outputs/get"
            path_url = f"/api/projects/{self.project_id}/outputs/get"
        response = self._call(
            "GET", path, params={"fileName": ref["path"]}, path_url=path_url,
            node_id=node.id, timeout=ARTIFACT_TIMEOUT_S,
            accept=ARROW_IPC_MIME, raw=True,
            extra_headers=ARROW_GEOMETRY_HEADERS,
        )
        digest = arrow_artifact_hash(
            response.get("content") or b"", response.get("headers") or {}
        )
        self.result.hashes[node.id] = digest
        expected = self.compare_to.get(node.id)
        if expected is not None and expected != digest:
            self._fail(path, node.id,
                       f"output differs from the single-user baseline "
                       f"(baseline {expected[:12]}, got {digest[:12]})",
                       "mismatch")
            raise UserFailed(f"node {node.id} output differs from baseline")


def new_user_name(tier: str | int, index: int, run_id: str | None = None) -> str:
    """A username unique per run, so reruns never collide in the database.

    ``tier`` is a label rather than a number so that the same size can be run
    twice in one command (``--tiers 10,10``) without the second pass trying to
    register the first pass's accounts and getting a 409.
    """
    run = run_id or uuid.uuid4().hex[:6]
    return f"stress_{run}_t{tier}_u{index}"
