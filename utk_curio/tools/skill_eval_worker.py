#!/usr/bin/env python3
"""One worker of ``agent_eval.py skills``: Curio's backend in this process, and its agents' chats on an evaluation account.

``agent_eval.py skills`` starts its workers and hands each its runs, one JSON
line on stdin each; the worker writes each run's files under the run's folder
and answers with one line, ``{"done": <path>, ...}``, on its own copy of
stdout (everything else this process prints goes to stderr). It needs no
web stack: the app answers through Flask's test client, on an in-memory
database and a state folder of its own (``CURIO_STATE_DIR``), and no node
runs, so no sandbox either.

- **The model:** the endpoint of ``CURIO_EVAL_BASE_URL``, ``CURIO_EVAL_API_KEY``
  and ``CURIO_EVAL_MODEL`` becomes the account's Deployment default, set in
  this process's settings (``config.DEFAULT_LLM_*``), as an operator sets it.
  So every call goes through the provider code API Settings uses, and the key
  is written nowhere: not in an LLM configuration, not in the state folder.
- **A run:** a fresh dataflow (the test case's, or an empty one) under a
  name that says nothing of the skill, its agent installed and attached, the
  message sent to the chat route a browser sends it to, with the context a
  browser's chat composes beside it (``evaluation/run_context.py``: the node
  the agent is attached to, or the whole dataflow, as the agent's reads
  say), and the session read back.
- **Without the skill:** the run's skills leave it out wherever a run gets
  one (``skill_runs._pool``: its catalog, what it is handed, its
  instruction's and its capabilities' skills, the dataflow's packages'), and
  the preamble leaves out its text (``prompts._resolve_prompt_text``), for a
  delegated run too.
- **Checked on every run:** a run with the skill held it (listed, handed or
  in its preamble, or handed to a run it delegated to); a run without it held
  it nowhere, and the skill's text is in no system turn its model calls were
  sent; a trigger run's chat listed it and was not handed it, judged by the
  chat's own system turn (a run the chat delegates to may be handed it, as
  Curio hands it). A run that breaks this is an error, and counts nowhere.
- **A trigger run** stops once its chat loads the skill, as agentskills.io's
  guide suggests, or once it delegates its work, before loading it, to a run
  Curio hands the skill (a node's content writer, say): the chat handed the
  work to the skill without consulting it, which counts as not loading it,
  and that run never starts. Any other delegation runs on, and the chat may
  still load the skill after it. ``--full-trigger-runs`` lets every run
  finish; a delegated run handed the skill before the chat loaded it then
  makes the run an error.
- **Retried:** a run whose model call the server failed (a 5xx, a lost
  connection) runs again on a fresh dataflow, after :data:`RETRY_WAITS_S`;
  the grader waits the same. Its record counts the attempts.
- **Not run:** the title call a conversation's first turn makes, which
  nothing here reads, and the kept outputs' sweep, which needs a sandbox.
- **Graded:** a test case's answer goes to the grader, the same model through
  the same code, with the words of the base entry's ``skill-evals.md``. A
  grader reply its output cap cut is not read, however much of it parses: the
  grader is asked again, and a grade that never came whole says it was cut.

Every file is scrubbed of the key, the base URL and its host before it is
written (``report.scrub``), and so is every log line.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend import config as backend_config  # noqa: E402
from utk_curio.backend.app import create_app  # noqa: E402
from utk_curio.backend.app.agents.application import attachments, skill_runs  # noqa: E402
from utk_curio.backend.app.agents.application.turns import prompts, titles  # noqa: E402
from utk_curio.backend.app.agents.domain import agent_text  # noqa: E402
from utk_curio.backend.app.agents.domain import skills as skill_format  # noqa: E402
from utk_curio.backend.app.agents.evaluation import run_context, skill_evals  # noqa: E402
from utk_curio.backend.app.agents.evaluation.report import scrub  # noqa: E402
from utk_curio.backend.app.agents.infrastructure import provider_config, providers  # noqa: E402
from utk_curio.backend.extensions import db  # noqa: E402

#: The base entry's page that holds the grader's words, and its two sections.
GRADER_PAGE = "skill-evals.md"
GRADER_SECTION = "grader"
GRADER_TASK_SECTION = "grader-task"
#: What the grader may write, and how many times it is asked for JSON.
GRADER_MAX_TOKENS = 2048
GRADER_ATTEMPTS = 3
#: How long a run, or the grader, waits before each new try after the model's
#: server failed it (a 5xx or a lost connection): two more tries at most.
RETRY_WAITS_S = (15, 45)
#: The most characters of one text of a change the grader is shown.
PREVIEW_MAX_CHARS = 16000
#: The name every run's dataflow has, which says nothing of what it tests.
PROJECT_NAME = "My dataflow"
#: The settings a Deployment default is read from (``provider_config``).
OPENAI_COMPATIBLE = "openai_compatible"
#: Loggers that print each request's URL at their INFO level.
_URL_LOGGERS = ("httpx", "httpcore", "openai", "urllib3")


class _Config:
    """The app's settings: an in-memory database, as the unit tests' app has."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = uuid.uuid4().hex
    WTF_CSRF_ENABLED = False


class _Loaded(BaseException):
    """A trigger run loaded the skill it watches for: its outcome is known.

    A ``BaseException``, so no ``except Exception`` of the turn takes it for
    a failure of the model or of a tool."""


class _HandedOff(BaseException):
    """A trigger run's chat delegated its work, before it loaded the skill, to
    a run Curio hands the skill: it handed the work to the skill without
    consulting it, so its outcome is known too. The delegated run never
    starts."""


#: What only a chat's system turn holds: the list of skills it may load.
_CATALOG_MARK = "<available_skills>"


class _Seams:
    """What one run changes of the backend, and what it saw of it."""

    def __init__(self):
        self.reset()

    def reset(self, *, left_out: str | None = None, left_out_text: str | None = None,
              watch: str | None = None, stop_at_hand_off: bool = False) -> None:
        self.left_out = left_out
        self.left_out_text = left_out_text
        self.watch = watch
        self.stop_at_hand_off = stop_at_hand_off
        self.handed_off: str | None = None
        self.capturing = True
        self.loaded: list[str] = []
        self.runs: list[dict] = []
        #: Each system turn a model call was sent, as (whether a chat's, its text).
        self.systems: list[tuple[bool, str]] = []
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def texts(self, *, chat: bool | None = None) -> list[str]:
        """The system turns sent: the chat's, the others', or all of them."""
        return [text for is_chat, text in self.systems if chat is None or is_chat == chat]

    def install(self) -> None:
        """Wrap the functions a run's skills and model calls go through, once."""
        seams = self
        pool, resolve, read = skill_runs._pool, prompts._resolve_prompt_text, skill_runs.read
        for_chat, for_delegated, chat_turn = skill_runs.for_chat, skill_runs.for_delegated, providers.run_chat_turn

        def _pool(user_key, manifest, preamble, spec=None, **kwargs):
            usable, placed, found, packages = pool(user_key, manifest, preamble, spec, **kwargs)
            name = seams.left_out
            if name:
                usable = {key: skill for key, skill in usable.items() if key != name}
                placed = frozenset(placed - {name})
                found = tuple(skill for skill in found if skill.name != name)
                packages = {key: value for key, value in packages.items() if key != name}
            return usable, placed, found, packages

        def _resolve(user_key, coord, name):
            text = resolve(user_key, coord, name)
            if seams.left_out_text and isinstance(text, str):
                text = text.replace(seams.left_out_text, "")
            return text

        def _record(run, kind, **more):
            seams.runs.append({"kind": kind, **more, **run.pins(), "placed": sorted(run.placed)})
            return run

        def _for_chat(*args, **kwargs):
            return _record(for_chat(*args, **kwargs), "chat")

        def _for_delegated(*args, **kwargs):
            capability = args[3] if len(args) > 3 else kwargs.get("capability")
            run = for_delegated(*args, **kwargs)
            holds = bool(seams.watch) and (seams.watch in run.placed
                                           or any(skill.name == seams.watch for skill in run.handed))
            stop = holds and seams.stop_at_hand_off
            _record(run, "delegated", capability=capability, loadedBefore=list(seams.loaded), started=not stop)
            if stop:
                seams.handed_off = str(capability)
                raise _HandedOff()
            return run

        def _read(run, params):
            before = list(run.loaded)
            status, text = read(run, params)
            for name in run.loaded[len(before):]:
                seams.loaded.append(name)
                if name == seams.watch:
                    raise _Loaded()
            return status, text

        def _chat_turn(config, messages, max_output_tokens=None, usage_out=None, **kwargs):
            usage: dict = {}
            turn = chat_turn(config, messages, max_output_tokens, usage, **kwargs)
            if usage_out is not None:
                usage_out.update(usage)
            if seams.capturing:
                seams.calls += 1
                seams.input_tokens += int(usage.get("inputTokens") or 0)
                seams.output_tokens += int(usage.get("outputTokens") or 0)
                for message in messages:
                    if message.get("role") == "system":
                        text = str(message.get("content") or "")
                        seams.systems.append((_CATALOG_MARK in text, text))
            return turn

        skill_runs._pool = _pool
        prompts._resolve_prompt_text = _resolve
        skill_runs.for_chat = _for_chat
        skill_runs.for_delegated = _for_delegated
        skill_runs.read = _read
        providers.run_chat_turn = _chat_turn
        # Nothing here reads a conversation's title, and it is one more call.
        titles._generate_conversation_title = lambda *args, **kwargs: None


class _ScrubbingFilter(logging.Filter):
    def __init__(self, secrets: dict):
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage(), values=self.secrets)
        record.args = ()
        return True


def _quiet_logs(secrets: dict) -> None:
    """Log warnings and worse to stderr, scrubbed, and no request's URL."""
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_ScrubbingFilter(secrets))
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.WARNING)
    for name in _URL_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _write(path: Path, data) -> None:
    """Write *data* (text, or JSON for anything else) at *path*, whole or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


#: What a kept proposal holds for its review's bookkeeping, which the grader is not shown.
_BOOKKEEPING = ("proposalId", "mintSequenceId", "contentSha256", "pins", "status")
#: What a node holds of where the canvas draws it, which no change the grader reads is about.
_LAYOUT = frozenset({"x", "y", "position", "positionAbsolute", "width", "height", "measured", "selected",
                     "dragging", "zIndex", "style"})


def _node_view(node: dict) -> dict:
    return {key: _clip(value) for key, value in node.items() if key not in _LAYOUT}


def _by_id(items) -> dict:
    return {str(item.get("id")): item for item in items or [] if isinstance(item, dict) and item.get("id") is not None}


def _differences(before: dict, after: dict) -> dict:
    """What differs between two views of one node, key by key, and inside its
    ``metadata``, each as its value before and after."""
    found = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if key == "metadata" and isinstance(old, dict) and isinstance(new, dict):
            for inner in sorted(set(old) | set(new)):
                if old.get(inner) != new.get(inner):
                    found[f"metadata.{inner}"] = {"before": _clip(old.get(inner)), "after": _clip(new.get(inner))}
        else:
            found[key] = {"before": _clip(old), "after": _clip(new)}
    return found


def _dataflow_changes(before: dict, after: dict) -> dict:
    """The nodes, connections and scenarios *after* added, changed or removed
    against *before*, two specs of one dataflow; only the kinds that hold one."""
    flows = [(spec.get("dataflow") if isinstance(spec.get("dataflow"), dict) else {}) for spec in (before, after)]
    out: dict = {}
    for key in ("nodes", "edges", "scenarios"):
        old, new = _by_id(flows[0].get(key)), _by_id(flows[1].get(key))
        added = [_node_view(new[i]) for i in new if i not in old]
        removed = [{k: old[i].get(k) for k in ("id", "type", "title", "name", "source", "target") if k in old[i]}
                   for i in old if i not in new]
        changed = []
        for i in new:
            if i in old:
                differs = _differences(_node_view(old[i]), _node_view(new[i]))
                if differs:
                    changed.append({"id": i, **{k: new[i].get(k) for k in ("type", "title", "name") if k in new[i]},
                                    "changes": differs})
        for name, found in (("added", added), ("changed", changed), ("removed", removed)):
            if found:
                out.setdefault(key, {})[name] = found
    return out


def _clip(value):
    """*value*, its texts cut to :data:`PREVIEW_MAX_CHARS`."""
    if isinstance(value, str):
        return value[:PREVIEW_MAX_CHARS]
    if isinstance(value, dict):
        return {key: _clip(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip(item) for item in value]
    return value


#: The status a model's server answered, as the provider's error names it.
_PROVIDER_STATUS_RE = re.compile(r"Error code: (\d{3})")
#: A model server's answers that say "try again later".
_TRY_AGAIN = (408, 429)
#: What the run route answers when the turn's model call failed (``run_attachment``),
#: or a proxy before it did; a 500 is Curio's own failure, which a new try repeats.
_PROVIDER_FAILED = (502, 503, 504)


def _transient(status: int | None, error: str | None) -> bool:
    """Whether a run that answered *status* failed for a reason a later try
    may not meet: a lost connection, a timeout or the model's server failing
    (a 5xx, 408 or 429 from it). The route answers 502 for every turn whose
    model call failed, so a 4xx the provider names, such as a request too
    long, is not one."""
    if status not in _PROVIDER_FAILED:
        return False
    found = _PROVIDER_STATUS_RE.search(error or "")
    return not (found and 400 <= int(found.group(1)) < 500 and int(found.group(1)) not in _TRY_AGAIN)


def _json_object(text: str):
    """The JSON object *text* holds, alone or inside other text, or None."""
    text = (text or "").strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


class Worker:
    """Curio's backend, an evaluation account and the seams of its runs."""

    def __init__(self, endpoint: skill_evals.Endpoint, results: Path, *, stop_early: bool):
        from utk_curio.backend.app.collaboration import dataflow_docs
        from utk_curio.backend.app.projects.services import _user_dir_key
        from utk_curio.backend.app.users.models import User, UserSession

        self.endpoint = endpoint
        self.secrets = endpoint.secrets()
        self.results = results
        self.stop_early = stop_early
        self.folders = {folder.name: folder for folder in skill_evals.skill_folders()}
        # Writes in this thread, at once, as the unit tests' app makes them.
        dataflow_docs.BACKGROUND = False
        self.app = create_app(_Config)
        # No run here keeps outputs and no sandbox runs, so the kept outputs'
        # sweep the backend schedules a minute after it starts is called off.
        from utk_curio.backend.app.runs import kept

        if kept._prune_timer is not None:
            kept._prune_timer.cancel()
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        user = User(username="evaluation", name="Skill evaluation", email="evaluation@localhost")
        db.session.add(user)
        db.session.flush()
        token = uuid.uuid4().hex
        db.session.add(UserSession(user_id=user.id, token=token))
        db.session.commit()
        self.user_key = _user_dir_key(user)
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = self.app.test_client()
        # The endpoint, as an operator's Deployment default: read at each call.
        backend_config.DEFAULT_LLM_API_TYPE = OPENAI_COMPATIBLE
        backend_config.DEFAULT_LLM_BASE_URL = endpoint.base_url
        backend_config.DEFAULT_LLM_API_KEY = endpoint.api_key
        backend_config.DEFAULT_LLM_MODEL = endpoint.model
        self.seams = _Seams()
        self.seams.install()

    # --- one run ----------------------------------------------------------------------

    def _json(self, method: str, path: str, payload=None) -> tuple[int, dict]:
        resp = self.client.open(path, method=method, json=payload, headers=self.headers)
        body = resp.get_json(silent=True)
        return resp.status_code, body if isinstance(body, dict) else {}

    def _project(self, context: skill_evals.Context) -> str:
        spec = {"dataflow": {"nodes": [], "edges": [], "packages": []}}
        if context.dataflow is not None:
            spec = json.loads(context.dataflow.read_text(encoding="utf-8"))
        status, body = self._json("POST", "/api/projects", {"name": PROJECT_NAME, "spec": spec, "outputs": []})
        if status >= 400 or "id" not in body:
            raise RuntimeError(f"the dataflow could not be created ({status}): {body.get('error')}")
        project_id = body["id"]
        for package in (spec.get("dataflow") or {}).get("packages") or []:
            dir_name = package.get("id") if isinstance(package, dict) else package
            if isinstance(dir_name, str) and dir_name:
                self._json("POST", f"/api/packages/projects/{project_id}/install", {"dirName": dir_name})
        return project_id

    def _attach(self, project_id: str, context: skill_evals.Context) -> dict:
        """The attachment of *context*'s agent to its target, as the attach
        route answers it: its id, its target and the reads its agent declares."""
        base = f"/api/agents/projects/{project_id}"
        status, body = self._json("POST", f"{base}/install", {"coord": context.agent})
        if status >= 400:
            raise RuntimeError(f"{context.agent} could not be installed ({status}): {body.get('error')}")
        target = {"kind": "canvas"} if context.target == skill_evals.CANVAS else {
            "kind": "node", "targetId": context.node}
        status, body = self._json("POST", f"{base}/attachments", {"coord": context.agent, "target": target})
        if status >= 400 or "attachmentId" not in body:
            raise RuntimeError(f"{context.agent} could not be attached ({status}): {body.get('error')}")
        return body

    @staticmethod
    def _request(message: str, attachment: dict, spec: dict) -> dict:
        """What a browser sends to run *message* on *attachment*: the message,
        and beside it the context its chat composes of the canvas, when the
        agent's reads compose any (``agentsApi.runAttachment``)."""
        flow = spec.get("dataflow") if isinstance(spec.get("dataflow"), dict) else {}
        context = run_context.compose(attachment.get("reads") or [], attachment.get("target"), spec,
                                      name=str(flow.get("name") or ""), goal=str(flow.get("task") or ""))
        return {"message": message, "context": context} if context else {"message": message}

    def _text_of(self, name: str) -> str | None:
        """The skill *name* as a run holds it, to look for in what it was sent."""
        folder = self.folders.get(name)
        if folder is None:
            return None
        if skill_format.is_shipped(skill_format.parse(folder)):
            return agent_text.skill_text(name)
        return skill_format.parse(folder).body.rstrip("\n")

    def _delegates_held(self, name: str, text: str | None) -> list[dict]:
        """The delegated runs that were handed the skill *name*, by their records."""
        started = [run for run in self.seams.runs if run["kind"] == "delegated" and run.get("started")]
        held = [run for run in started if any(name in run.get(key, []) for key in ("handed", "placed"))]
        if not held and text and any(text in system for system in self.seams.texts(chat=False)):
            held = started[:1]
        return held

    def _held(self, task: skill_evals.Task, text: str | None) -> tuple[str | None, str | None]:
        """How the run's chat held the skill (``listed``, ``handed`` or
        ``placed``, or None), and why that breaks the run's condition, or None.
        The chat is judged by its own system turn alone: a run it delegated
        to may be handed the skill, as Curio hands it, without the chat
        holding it."""
        name = task.skill
        chat = next((run for run in self.seams.runs if run["kind"] == "chat"), None)
        if chat is None:
            return None, "the run built no chat"
        in_text = bool(text) and any(text in system for system in self.seams.texts(chat=True))
        placed = name in chat["placed"] or in_text
        handed = any(name in chat.get(key, []) for key in ("handed", "kept", "named"))
        how = "handed" if handed else "placed" if placed else "listed" if name in chat.get("catalog", []) else None
        if task.kind == skill_evals.TRIGGER:
            if how != "listed":
                return how, (f"the chat does not list {name}" if how is None
                             else f"the chat is {how} {name}, so loading it measures nothing")
            early = [run for run in self._delegates_held(name, text) if name not in run.get("loadedBefore", [])]
            if early:
                return how, f"a delegated run ({early[0].get('capability')}) held {name} before the chat loaded it"
            return how, None
        if task.condition == skill_evals.WITH_SKILL:
            return how, None if how or self._delegates_held(name, text) else f"the run did not hold {name}"
        for run in self.seams.runs:
            if any(name in run.get(key, []) for key in ("catalog", "handed", "kept", "named", "placed")):
                return how, f"a {run['kind']} run still held {name}"
        if text and any(text in system for system in self.seams.texts()):
            return how, f"a system turn still held the text of {name}"
        if name in self.seams.loaded:
            return how, f"the run loaded {name}"
        return None, None

    def _attempt(self, task: skill_evals.Task, message: str, folder: Path, record: dict):
        """One attempt at *task*'s run, on a dataflow and an attachment of its
        own; returns ``(the run's status or None, its reply, project id, the
        dataflow before the message)``, and notes on *record* how it ended."""
        body: dict = {}
        before: dict = {}
        status = project_id = attachment_id = None
        for key in ("error", "stoppedEarly", "handedOff"):
            record.pop(key, None)
        try:
            project_id = self._project(task.context)
            attachment = self._attach(project_id, task.context)
            attachment_id = attachment["attachmentId"]
            before = self._spec(project_id)
            url = f"/api/agents/projects/{project_id}/attachments/{attachment_id}/run"
            request = self._request(message, attachment, before)
            record["contextChars"] = len(request.get("context") or "")
            try:
                status, body = self._json("POST", url, request)
                record["stoppedEarly"] = False
                if status >= 400:
                    record["error"] = f"the run answered {status}: {body.get('error') or body}"
            except _Loaded:
                record["stoppedEarly"] = True
            except _HandedOff:
                record["stoppedEarly"] = True
                record["handedOff"] = self.seams.handed_off
            _, session = self._json("GET", f"/api/agents/projects/{project_id}/attachments/{attachment_id}/session")
            _write(folder / "transcript.json", scrub(session.get("turns") or [], values=self.secrets))
        except Exception as exc:  # noqa: BLE001 - a run that cannot start is an error, not a crash
            record["error"] = f"{type(exc).__name__}: {exc}"
        return status, body, project_id, before

    def run(self, task: skill_evals.Task, *, hand: bool = False) -> dict:
        """Run *task* and write its files; returns its record. A run the model's
        server failed (a 5xx, a lost connection) is run again, on a fresh
        dataflow, after each wait of :data:`RETRY_WAITS_S`."""
        folder = self.results / task.path
        record: dict = {key: value for key, value in task.as_dict().items()
                        if key in ("kind", "skill", "key", "condition", "run", "query", "should_trigger", "case")}
        started = time.monotonic()
        text = self._text_of(task.skill)
        without = task.condition == skill_evals.WITHOUT_SKILL
        trigger = task.kind == skill_evals.TRIGGER
        message = f"/{task.skill} {task.message}" if hand and not trigger and not without else task.message
        failed: list[str] = []
        while True:
            self.seams.reset(left_out=task.skill if without else None, left_out_text=text if without else None,
                             watch=task.skill if trigger and self.stop_early else None,
                             stop_at_hand_off=trigger and self.stop_early)
            attempt_started = time.monotonic()
            status, body, project_id, before = self._attempt(task, message, folder, record)
            if not _transient(status, record.get("error")) or len(failed) >= len(RETRY_WAITS_S):
                break
            failed.append(record["error"])
            time.sleep(RETRY_WAITS_S[len(failed) - 1])
        record["attempts"] = len(failed) + 1
        if failed:
            record["failedAttempts"] = failed
        self.seams.capturing = False
        record["loadedSkills"] = list(self.seams.loaded)
        record["loaded"] = task.skill in self.seams.loaded
        record["skills"] = self.seams.runs
        how, problem = self._held(task, text)
        record["held"] = how
        # What reached a model of the skill: loaded, handed or placed, or handed to a delegate.
        record["used"] = record["loaded"] or how in ("handed", "placed") or bool(self._delegates_held(task.skill, text))
        if problem and "error" not in record:
            record["error"] = f"the condition was not met: {problem}"
        record["calls"] = self.seams.calls
        record["seconds"] = round(time.monotonic() - started, 3)
        timing = {"total_tokens": self.seams.input_tokens + self.seams.output_tokens,
                  "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                  "input_tokens": self.seams.input_tokens, "output_tokens": self.seams.output_tokens}
        record["timing"] = timing
        if task.kind == skill_evals.TRIGGER:
            record["triggered"] = record["loaded"]
        else:
            changes = self._changes(before, project_id, body)
            self._outputs(folder, body, changes)
            _write(folder / "timing.json", timing)
            if "error" not in record:
                grading = self._grade(task, body, changes)
                record["grading"] = grading
                if grading.get("error"):
                    record["error"] = f"the grader failed: {grading['error']}"
                _write(folder / "grading.json", scrub(grading, values=self.secrets))
        record = scrub(record, values=self.secrets)
        _write(folder / "run.json", record)
        return record

    # --- the answer, and its grade ----------------------------------------------------

    def _spec(self, project_id: str | None) -> dict:
        """The run's dataflow as the server keeps it now."""
        if not project_id:
            return {}
        _, project = self._json("GET", f"/api/projects/{project_id}")
        return project.get("spec") if isinstance(project.get("spec"), dict) else {}

    def _changes(self, before: dict, project_id: str | None, body: dict) -> dict:
        """What the run did to its dataflow, which landed when the agent made it
        (``changed``: the nodes, connections and scenarios it added, changed or
        removed, with what it gave them; ``cards``: what its turn's change cards
        say), and the installs it asked for, which wait for the user's review
        (``awaiting_review``). The dataflow is the run's own, so all of it is the
        run's: a node's code a delegate wrote lands on that node too."""
        after = self._spec(project_id)
        pending = []
        for record in attachments.list_attachments(after):
            for proposal in (record.get("planProposal"), record.get("activeProposal"),
                             *(record.get("queuedProposals") or [])):
                if isinstance(proposal, dict) and proposal.get("status") == "pending":
                    pending.append({key: _clip(value) for key, value in proposal.items() if key not in _BOOKKEEPING})
        cards = skill_evals.change_cards(body.get("content") or [])
        return {"changed": _dataflow_changes(before, after), "cards": cards, "awaiting_review": pending}

    def _outputs(self, folder: Path, body: dict, changes: dict) -> None:
        _write(folder / "outputs" / "reply.md", scrub(str(body.get("reply") or ""), values=self.secrets) + "\n")
        _write(folder / "outputs" / "changes.json", scrub(changes, values=self.secrets))

    def _calls(self, folder: Path) -> list[dict]:
        """The tools the run called, from its turn's record in the transcript,
        but skill.read: a run without the skill seldom calls it, so the grader
        is not shown it, and judges the answer blind to its condition."""
        try:
            turns = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        execution = next((turn.get("execution") for turn in reversed(turns)
                          if isinstance(turn, dict) and isinstance(turn.get("execution"), dict)), {})
        return [{"tool": call.get("tool"), "status": call.get("status")}
                for call in execution.get("toolCalls") or []
                if isinstance(call, dict) and call.get("tool") != skill_runs.TOOL]

    def _grade(self, task: skill_evals.Task, body: dict, changes: dict) -> dict:
        folder = self.results / task.path
        values = {
            "prompt": task.message,
            "expected_output": task.expected_output or "",
            "assertions": "\n".join(f"{at}. {text}" for at, text in enumerate(task.assertions, start=1)),
            "reply": str(body.get("reply") or "").strip(),
            "changes": json.dumps(changes, indent=2, ensure_ascii=False),
            "tools": json.dumps(self._calls(folder), ensure_ascii=False),
        }
        where = f"{agent_text.PAGE_PREFIX}{GRADER_PAGE}"
        system = agent_text.section(GRADER_PAGE, GRADER_SECTION)
        message = agent_text.fill(agent_text.section(GRADER_PAGE, GRADER_TASK_SECTION), values, where)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": message}]
        config = provider_config.resolve_llm(self.user_key)
        problem = "no reply"
        usage: dict = {}
        waits = list(RETRY_WAITS_S)
        for attempt in range(1, GRADER_ATTEMPTS + 1):
            try:
                turn = providers.ChatTurn.of(providers.run_chat_turn(config, messages, GRADER_MAX_TOKENS, usage))
            except Exception as exc:  # noqa: BLE001 - a grader that fails is an error of the run
                problem = provider_config.redact_error(exc, config)
                if attempt < GRADER_ATTEMPTS and waits:
                    time.sleep(waits.pop(0))
                continue
            if turn.cut_at_output_cap:
                problem = f"its reply was cut off at the grader's output limit of {GRADER_MAX_TOKENS:,} tokens"
                continue
            parsed = _json_object(turn.text)
            results = parsed.get("assertion_results") if parsed else None
            if isinstance(results, list) and len(results) == len(task.assertions):
                graded = [{"text": text, "passed": item.get("passed") is True,
                           "evidence": str(item.get("evidence") or "")}
                          for text, item in zip(task.assertions, results) if isinstance(item, dict)]
                if len(graded) == len(task.assertions):
                    return {"assertion_results": graded, "summary": skill_evals.grading_summary(graded),
                            "grader": {"model": self.endpoint.model, "attempts": attempt}}
            problem = "its reply was no list of one result per assertion"
        return {"error": problem, "grader": {"model": self.endpoint.model, "attempts": GRADER_ATTEMPTS}}


def _protocol() -> "object":
    """This process's stdout for the protocol alone: anything else printed
    goes to stderr."""
    stream = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1, encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return stream


def main(argv: list | None = None) -> int:
    protocol = _protocol()
    try:
        endpoint = skill_evals.Endpoint.from_env()
    except LookupError as exc:
        print(f"the worker cannot start: {exc}", file=sys.stderr)
        return 2
    _quiet_logs(endpoint.secrets())
    results = Path(os.environ["CURIO_EVAL_RESULTS"])
    stop_early = os.environ.get("CURIO_EVAL_FULL_TRIGGER_RUNS") != "1"
    hand = os.environ.get("CURIO_EVAL_HAND") == "1"
    worker = Worker(endpoint, results, stop_early=stop_early)
    protocol.write(json.dumps({"ready": True}) + "\n")
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get("stop"):
            break
        task = skill_evals.Task.from_dict(message["task"])
        try:
            record = worker.run(task, hand=hand)
        except Exception as exc:  # noqa: BLE001 - the worker goes on to the next run
            record = {"error": f"{type(exc).__name__}: {exc}"}
        protocol.write(json.dumps({"done": task.path, "error": bool(record.get("error")),
                                   "seconds": record.get("seconds")}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
