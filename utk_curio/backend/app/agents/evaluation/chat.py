"""The run's own account of itself, in the agent's transcript (dev/123).

The panel holds the report, and keeps it. But the conversation is where a
person looks to understand what an agent did, and after a run the attached
Dataflow Builder's chat told only half the story: the prompt, the plan, the
apply card and the Solve card are production's own turns, and then it stopped —
nothing said what the run was, how the dataflow compared with the example, or
why the score is what it is. The panel and the transcript are now the same
story told in two places, which is the point: the transcript is the one that
survives with the project.

Two rules shape what may be written here, and both are load-bearing:

- **Nothing is appended before the model answers.** ``run_attachment`` sends a
  bounded window of the session's prior turns as context, so a turn written
  ahead of the prompt would change the very conditions being measured. Every
  function here runs after the model's turn.
- **The reference graph never appears.** A later conversation in this kept
  project would carry these turns as context, so they hold aggregate scores,
  category names and counts of what the run itself built — never the example's
  nodes, edges, templates or content. The comparison stays server-side
  (``DEC-079``); what lands here is its verdict, not its input.

A failure to write a turn is never a failure of the run: the record is the
machine account, and this is the human one.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from utk_curio.backend.app.agents import attachments, sessions

#: Dimension order in the report card — the weighted order of the scorer, so a
#: reader sees the heaviest categories first.
_DIMENSION_ORDER = ("templates", "topology", "dependencies", "intents", "execution")


def session_id_for(spec: Mapping, attachment_id: str) -> str | None:
    """The attachment's transcript id, or ``None`` if it has no session yet."""
    record = attachments.get_attachment(dict(spec or {}), attachment_id)
    session_id = (record or {}).get("sessionId")
    return session_id if isinstance(session_id, str) and session_id else None


def _percent(value) -> str:
    return f"{round(float(value) * 100)}%"


def _append(user_key: str, project_id: str, attachment_id: str, spec: Mapping,
            text: str, title: str, lines: Sequence[str]) -> bool:
    """Append one result-card turn. Answers whether it was written."""
    session_id = session_id_for(spec, attachment_id)
    if session_id is None:
        return False
    sessions.append_turns(
        user_key,
        project_id,
        session_id,
        attachment_id,
        [
            sessions.make_turn(
                "agent",
                text,
                content=[{
                    "type": "card",
                    "kind": "result",
                    "title": title,
                    "lines": [str(line) for line in lines if str(line).strip()],
                }],
            )
        ],
    )
    return True


def report_lines(record, fixture, *, solved: int = 0, solvable: int = 0) -> list[str]:
    """The lines of the report card, from the run's own record.

    Kept separate from the writing so a test can read what a person would.
    """
    score = record.score or {}
    dimensions = score.get("dimensions") or {}
    lines: list[str] = []
    if score:
        lines.append(f"Overall accuracy {_percent(score.get('total') or 0)}.")
    for name in _DIMENSION_ORDER:
        if name not in dimensions:
            continue
        value = dimensions.get(name)
        lines.append(
            f"{name.capitalize()}: "
            + ("not measured" if value is None else _percent(value))
        )
    categories = [str(c) for c in (score.get("categories") or [])]
    if categories:
        lines.append("Differences found: " + ", ".join(categories) + ".")
    elif score:
        lines.append("No differences from the example were found.")
    for note in (score.get("notes") or [])[:4]:
        lines.append(str(note))
    if solvable:
        lines.append(f"Solve verified {solved} of {solvable} nodes.")
    for entry in record.pending or []:
        lines.append(
            f"Left for a person: {entry.get('tool')} — {entry.get('reason')}"
        )
    for failure in record.failures or []:
        lines.append(f"Stopped in {failure.get('phase')}: {failure.get('detail')}")
    provider = record.provider or {}
    usage = record.usage or {}
    tokens = int(usage.get("inputTokens") or 0) + int(usage.get("outputTokens") or 0)
    detail = f"Model {provider.get('model') or 'unknown'}"
    if provider.get("baseUrlHost"):
        detail += f" at {provider['baseUrlHost']}"
    if tokens:
        detail += (
            f" · {usage.get('inputTokens', 0)} in / "
            f"{usage.get('outputTokens', 0)} out tokens"
        )
    if record.latency_ms:
        detail += f" · {round(record.latency_ms / 1000)}s"
    lines.append(detail + ".")
    lines.append(
        "Compared with Curio's saved example by deterministic code — no model "
        "graded this, and the example stayed on the server."
    )
    return lines


def post_report(
    user_key: str,
    project_id: str,
    attachment_id: str,
    spec: Mapping,
    *,
    record,
    fixture,
    solved: int = 0,
    solvable: int = 0,
) -> bool:
    """Append the evaluation's verdict to the transcript, after the run."""
    total = (record.score or {}).get("total")
    text = (
        f"Evaluation of the {fixture.fixture_id} prompt finished"
        + (f" at {_percent(total)} overall accuracy." if total is not None else ".")
    )
    return _append(
        user_key, project_id, attachment_id, spec, text,
        "Evaluation report",
        report_lines(record, fixture, solved=solved, solvable=solvable),
    )


def post_stopped(
    user_key: str,
    project_id: str,
    attachment_id: str,
    spec: Mapping,
    *,
    record,
    fixture,
    reason: str,
) -> bool:
    """Append why a run ended without a score, so the transcript is not silent."""
    lines = [reason]
    for failure in record.failures or []:
        lines.append(f"Stopped in {failure.get('phase')}: {failure.get('detail')}")
    lines.append(
        "This dataflow is whatever the run had built when it stopped. The "
        "project is yours to keep or delete."
    )
    return _append(
        user_key, project_id, attachment_id, spec, text=(
            f"Evaluation of the {fixture.fixture_id} prompt stopped in "
            f"{record.phase}."
        ),
        title="Evaluation stopped", lines=lines,
    )
