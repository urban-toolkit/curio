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
  message sent to the chat route a browser sends it to, and the session read
  back.
- **Without the skill:** the run's skills leave it out wherever a run gets
  one (``skill_runs._pool``: its catalog, what it is handed, its
  instruction's and its capabilities' skills, the dataflow's packages'), and
  the preamble leaves out its text (``prompts._resolve_prompt_text``), for a
  delegated run too.
- **Checked on every run:** a run with the skill held it (listed, handed or
  in its preamble); a run without it held it nowhere, and the skill's text is
  in no system turn its model calls were sent; a trigger run listed it and
  was not handed it. A run that breaks this is an error, and counts nowhere.
- **A trigger run** stops once it loads the skill, as agentskills.io's guide
  suggests: the outcome is known. ``--full-trigger-runs`` lets it finish.
- **Not run:** the title call a conversation's first turn makes, which
  nothing here reads.
- **Graded:** a test case's answer goes to the grader, the same model through
  the same code, with the words of the base entry's ``skill-evals.md``.

Every file is scrubbed of the key, the base URL and its host before it is
written (``report.scrub``), and so is every log line.
"""

from __future__ import annotations

import json
import logging
import os
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
from utk_curio.backend.app.agents.evaluation import skill_evals  # noqa: E402
from utk_curio.backend.app.agents.evaluation.report import scrub  # noqa: E402
from utk_curio.backend.app.agents.infrastructure import provider_config, providers  # noqa: E402
from utk_curio.backend.extensions import db  # noqa: E402

#: The base entry's page that holds the grader's words, and its two sections.
GRADER_PAGE = "skill-evals.md"
GRADER_SECTION = "grader"
GRADER_TASK_SECTION = "grader-task"
#: What the grader may write, and how many times it is asked for JSON.
GRADER_MAX_TOKENS = 2048
GRADER_ATTEMPTS = 2
#: The most characters of one proposed change the grader is shown.
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


class _Seams:
    """What one run changes of the backend, and what it saw of it."""

    def __init__(self):
        self.reset()

    def reset(self, *, left_out: str | None = None, left_out_text: str | None = None,
              watch: str | None = None) -> None:
        self.left_out = left_out
        self.left_out_text = left_out_text
        self.watch = watch
        self.capturing = True
        self.loaded: list[str] = []
        self.runs: list[dict] = []
        self.systems: list[str] = []
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def install(self) -> None:
        """Wrap the functions a run's skills and model calls go through, once."""
        seams = self
        pool, resolve, read = skill_runs._pool, prompts._resolve_prompt_text, skill_runs.read
        for_chat, for_delegated, chat_turn = skill_runs.for_chat, skill_runs.for_delegated, providers.run_chat_turn

        def _pool(user_key, manifest, preamble, spec=None):
            usable, placed, found, packages = pool(user_key, manifest, preamble, spec)
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

        def _record(run, kind):
            seams.runs.append({"kind": kind, **run.pins(), "placed": sorted(run.placed)})
            return run

        def _for_chat(*args, **kwargs):
            return _record(for_chat(*args, **kwargs), "chat")

        def _for_delegated(*args, **kwargs):
            return _record(for_delegated(*args, **kwargs), "delegated")

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
                seams.systems += [str(m.get("content") or "") for m in messages if m.get("role") == "system"]
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


def _clip(value):
    """*value*, its texts cut to :data:`PREVIEW_MAX_CHARS`."""
    if isinstance(value, str):
        return value[:PREVIEW_MAX_CHARS]
    if isinstance(value, dict):
        return {key: _clip(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip(item) for item in value]
    return value


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

    def _attach(self, project_id: str, context: skill_evals.Context) -> str:
        base = f"/api/agents/projects/{project_id}"
        status, body = self._json("POST", f"{base}/install", {"coord": context.agent})
        if status >= 400:
            raise RuntimeError(f"{context.agent} could not be installed ({status}): {body.get('error')}")
        target = {"kind": "canvas"} if context.target == skill_evals.CANVAS else {
            "kind": "node", "targetId": context.node}
        status, body = self._json("POST", f"{base}/attachments", {"coord": context.agent, "target": target})
        if status >= 400 or "attachmentId" not in body:
            raise RuntimeError(f"{context.agent} could not be attached ({status}): {body.get('error')}")
        return body["attachmentId"]

    def _text_of(self, name: str) -> str | None:
        """The skill *name* as a run holds it, to look for in what it was sent."""
        folder = self.folders.get(name)
        if folder is None:
            return None
        if skill_format.is_shipped(skill_format.parse(folder)):
            return agent_text.skill_text(name)
        return skill_format.parse(folder).body.rstrip("\n")

    def _held(self, task: skill_evals.Task, text: str | None) -> tuple[str | None, str | None]:
        """How the run's chat held the skill (``listed``, ``handed`` or
        ``placed``, or None), and why that breaks the run's condition, or None."""
        name = task.skill
        chat = next((run for run in self.seams.runs if run["kind"] == "chat"), None)
        if chat is None:
            return None, "the run built no chat"
        placed = name in chat["placed"] or (bool(text) and any(text in system for system in self.seams.systems))
        handed = any(name in chat.get(key, []) for key in ("handed", "kept", "named"))
        how = "handed" if handed else "placed" if placed else "listed" if name in chat.get("catalog", []) else None
        if task.kind == skill_evals.TRIGGER:
            if how != "listed":
                return how, (f"the chat does not list {name}" if how is None
                             else f"the chat is {how} {name}, so loading it measures nothing")
            return how, None
        if task.condition == skill_evals.WITH_SKILL:
            return how, None if how else f"the run did not hold {name}"
        for run in self.seams.runs:
            if any(name in run.get(key, []) for key in ("catalog", "handed", "kept", "named", "placed")):
                return how, f"a {run['kind']} run still held {name}"
        if text and any(text in system for system in self.seams.systems):
            return how, f"a system turn still held the text of {name}"
        if name in self.seams.loaded:
            return how, f"the run loaded {name}"
        return None, None

    def run(self, task: skill_evals.Task, *, hand: bool = False) -> dict:
        """Run *task* and write its files; returns its record."""
        folder = self.results / task.path
        record: dict = {key: value for key, value in task.as_dict().items()
                        if key in ("kind", "skill", "key", "condition", "run", "query", "should_trigger", "case")}
        started = time.monotonic()
        text = self._text_of(task.skill)
        without = task.condition == skill_evals.WITHOUT_SKILL
        self.seams.reset(left_out=task.skill if without else None, left_out_text=text if without else None,
                         watch=task.skill if task.kind == skill_evals.TRIGGER and self.stop_early else None)
        body: dict = {}
        project_id = attachment_id = None
        try:
            project_id = self._project(task.context)
            attachment_id = self._attach(project_id, task.context)
            message = f"/{task.skill} {task.message}" if hand and task.kind == skill_evals.TASK and not without \
                else task.message
            url = f"/api/agents/projects/{project_id}/attachments/{attachment_id}/run"
            try:
                status, body = self._json("POST", url, {"message": message})
                record["stoppedEarly"] = False
                if status >= 400:
                    record["error"] = f"the run answered {status}: {body.get('error') or body}"
            except _Loaded:
                record["stoppedEarly"] = True
            _, session = self._json("GET", f"/api/agents/projects/{project_id}/attachments/{attachment_id}/session")
            _write(folder / "transcript.json", scrub(session.get("turns") or [], values=self.secrets))
        except Exception as exc:  # noqa: BLE001 - a run that cannot start is an error, not a crash
            record["error"] = f"{type(exc).__name__}: {exc}"
        self.seams.capturing = False
        record["loadedSkills"] = list(self.seams.loaded)
        record["loaded"] = task.skill in self.seams.loaded
        record["skills"] = self.seams.runs
        how, problem = self._held(task, text)
        record["held"] = how
        # What reached the model of the skill: its text, handed or placed, or loaded.
        record["used"] = record["loaded"] or how in ("handed", "placed")
        if problem and "error" not in record:
            record["error"] = f"the condition was not met: {problem}"
        record["calls"] = self.seams.calls
        record["seconds"] = round(time.monotonic() - started, 3)
        timing = {"total_tokens": self.seams.input_tokens + self.seams.output_tokens,
                  "duration_ms": int(record["seconds"] * 1000),
                  "input_tokens": self.seams.input_tokens, "output_tokens": self.seams.output_tokens}
        record["timing"] = timing
        if task.kind == skill_evals.TRIGGER:
            record["triggered"] = record["loaded"]
        else:
            proposals = self._proposals(project_id, attachment_id, body)
            self._outputs(folder, body, proposals)
            _write(folder / "timing.json", timing)
            if "error" not in record:
                grading = self._grade(task, body, proposals)
                record["grading"] = grading
                if grading.get("error"):
                    record["error"] = f"the grader failed: {grading['error']}"
                _write(folder / "grading.json", scrub(grading, values=self.secrets))
        record = scrub(record, values=self.secrets)
        _write(folder / "run.json", record)
        return record

    # --- the answer, and its grade ----------------------------------------------------

    def _proposals(self, project_id: str | None, attachment_id: str | None, body: dict) -> list[dict]:
        """What the run proposed, as its dataflow keeps each proposal for
        review (its code or spec, its widgets, its plan), else as its reply's
        cards show them. The dataflow is the run's own, so every attachment's
        proposals are the run's: a node's content written by a delegate waits
        for review on that node's agent, not on the chat's."""
        found: list = []
        if project_id and attachment_id:
            _, project = self._json("GET", f"/api/projects/{project_id}")
            spec = project.get("spec") if isinstance(project.get("spec"), dict) else {}
            for record in attachments.list_attachments(spec):
                found += [record.get("planProposal"), record.get("activeProposal"),
                          *(record.get("queuedProposals") or [])]
        seen: set = set()
        kept = []
        for proposal in found:
            if not isinstance(proposal, dict) or proposal.get("status") == "superseded":
                continue
            if proposal.get("proposalId") in seen:
                continue
            seen.add(proposal.get("proposalId"))
            kept.append({key: _clip(value) for key, value in proposal.items() if key not in _BOOKKEEPING})
        if kept:
            return kept
        return [{"tool": part.get("tool"), "summary": part.get("summary"), "content": _clip(part.get("preview"))}
                for part in body.get("content") or [] if isinstance(part, dict) and part.get("type") == "proposal"]

    def _outputs(self, folder: Path, body: dict, proposals: list[dict]) -> None:
        _write(folder / "outputs" / "reply.md", scrub(str(body.get("reply") or ""), values=self.secrets) + "\n")
        _write(folder / "outputs" / "proposals.json", scrub(proposals, values=self.secrets))

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

    def _grade(self, task: skill_evals.Task, body: dict, proposals: list[dict]) -> dict:
        folder = self.results / task.path
        values = {
            "prompt": task.message,
            "expected_output": task.expected_output or "",
            "assertions": "\n".join(f"{at}. {text}" for at, text in enumerate(task.assertions, start=1)),
            "reply": str(body.get("reply") or "").strip(),
            "proposals": json.dumps(proposals, indent=2, ensure_ascii=False),
            "tools": json.dumps(self._calls(folder), ensure_ascii=False),
        }
        where = f"{agent_text.PAGE_PREFIX}{GRADER_PAGE}"
        system = agent_text.section(GRADER_PAGE, GRADER_SECTION)
        message = agent_text.fill(agent_text.section(GRADER_PAGE, GRADER_TASK_SECTION), values, where)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": message}]
        config = provider_config.resolve_llm(self.user_key)
        problem = "no reply"
        usage: dict = {}
        for attempt in range(1, GRADER_ATTEMPTS + 1):
            try:
                reply = providers.run_chat_completion(config, messages, GRADER_MAX_TOKENS, usage)
            except Exception as exc:  # noqa: BLE001 - a grader that fails is an error of the run
                problem = provider_config.redact_error(exc, config)
                continue
            parsed = _json_object(reply)
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
