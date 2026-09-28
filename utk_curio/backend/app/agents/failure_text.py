"""What a failed round is called in front of the user.

Memo dev/127. Three places used to cut a raw traceback to a fixed number of
characters — the batch's per-node error line, the Solve card's round lines, the
per-node Solve card — and all three could land mid-token. The owner's report
carries the evidence verbatim: ``execution-error: das/core/generic.py`` (the
tail of ``pandas/core/generic.py``), ``round 1: execution-error — ic.py", line
1776`` and, best of all, ``round 2: execution-error — de``, where ``de`` was
all that survived of the line before the exception.

The two things a reader needs are the **exception line** (the type and its
message — the answer) and the **frame that raised it** (where to look). Both are
extractable; neither survives a character slice. This module is the one place
that reads a traceback, so the strip, the cards and the persisted attempt trail
can never disagree about what failed.

Pure text in, pure text out: no I/O, no knowledge of nodes, agents or specs.
"""

from __future__ import annotations

import re

#: ``File "…/pandas/core/generic.py", line 6206, in __getattr__`` — and the
#: sandbox's own shorter shapes.
_FRAME_RE = re.compile(
    r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?',
)

#: ``KeyError: 'community_area'`` / ``AttributeError: 'DataFrame' object has …``
#: A qualified name is allowed (``pandas.errors.MergeError``), a sentence is
#: not: the head must look like an exception type, not like prose.
_EXCEPTION_RE = re.compile(
    r"^(?P<type>(?:[A-Za-z_][\w.]*\.)?[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning|Interrupt|Exit))"
    r"(?::\s?(?P<message>.*))?$"
)

#: Lines a traceback prints that carry no information for the reader.
_NOISE_PREFIXES = ("Traceback (most recent call last)", "^^^", "~~~", "During handling")

#: The markers Python uses between chained exceptions.
_CHAIN_MARKERS = (
    "During handling of the above exception, another exception occurred",
    "The above exception was the direct cause of the following exception",
)


def _lines(raw: object) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    return [line.rstrip() for line in raw.replace("\r\n", "\n").split("\n")]


def exception_line(raw: object) -> str | None:
    """The LAST exception line in *raw* — type and message — or None.

    The last one is the one that actually stopped the code: a chained traceback
    prints the original first and the raise that surfaced last.
    """
    for line in reversed(_lines(raw)):
        text = line.strip()
        if not text:
            continue
        m = _EXCEPTION_RE.match(text)
        if m:
            return text
    return None


#: Long library paths carry no information past their last few segments.
_FRAME_PATH_SEGMENTS = 3


def raising_frame(raw: object) -> str | None:
    """The innermost frame as ``path:line in func``, or None.

    Rendered compactly rather than in Python's own multi-line shape: a
    truncated site's ``generic.py", line 6206`` (the owner's report) is what a
    character slice through a traceback looks like, and a reader needs the
    location, not the quoting.
    """
    frames = [m for line in _lines(raw) if (m := _FRAME_RE.match(line))]
    if not frames:
        return None
    m = frames[-1]
    path = m.group("path")
    if not path.startswith("<"):
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if len(parts) > _FRAME_PATH_SEGMENTS:
            path = ".../" + "/".join(parts[-_FRAME_PATH_SEGMENTS:])
    where = f"{path}:{m.group('line')}"
    func = m.group("func")
    return f"{where} in {func}" if func else where


def is_chained(raw: object) -> bool:
    """Whether *raw* prints more than one exception (Python's chaining)."""
    text = "\n".join(_lines(raw))
    return any(marker in text for marker in _CHAIN_MARKERS)


def is_self_raised(raw: object, code: object = None) -> bool:
    """Whether the exception came from the CANDIDATE's own ``raise``.

    The owner's round 2 raised ``KeyError('No common column found between
    boundaries and population datasets to perform a join.')`` — the model's own
    guard — and the trail attributed it to pandas, because the only visible
    thing was a traceback whose frames are full of library paths. Two signals,
    both cheap: the innermost frame is the executed candidate (the sandbox
    names it ``<string>`` / ``<stdin>`` / the wrapper), or the candidate's text
    contains a ``raise`` of that same exception type.
    """
    frames = [m for line in _lines(raw) if (m := _FRAME_RE.match(line))]
    if frames:
        path = frames[-1].group("path")
        if path.startswith("<") or path.endswith("python_wrapper.txt"):
            return True
    line = exception_line(raw)
    if not line or not isinstance(code, str) or not code.strip():
        return False
    exc_type = _EXCEPTION_RE.match(line).group("type").rsplit(".", 1)[-1]
    return bool(re.search(rf"\braise\s+{re.escape(exc_type)}\b", code))


def excerpt(raw: object, *, limit: int, head: bool = False) -> str:
    """*raw* trimmed to at most *limit* chars **on line boundaries**.

    Never returns a partial line: whole lines are dropped from the far end
    (the head when reading the tail, the tail when ``head=True``) and the drop
    is marked with ``…``. Noise-only lines go first. A single line longer than
    *limit* is the one case a line is cut — and it is cut at a word boundary
    where one exists within the last 20% of the budget.
    """
    lines = [line for line in _lines(raw) if line.strip()]
    lines = [
        line for line in lines
        if not line.strip().startswith(_NOISE_PREFIXES)
    ] or lines
    if not lines:
        return ""
    if head:
        kept: list[str] = []
        for line in lines:
            if _joined_len(kept + [line]) > limit and kept:
                kept.append("…")
                break
            kept.append(line)
    else:
        kept = []
        for line in reversed(lines):
            if _joined_len([line] + kept) > limit and kept:
                kept.insert(0, "…")
                break
            kept.insert(0, line)
    text = "\n".join(kept)
    if len(text) <= limit:
        return text
    return _clip(text, limit)


def _joined_len(lines: list[str]) -> int:
    return sum(len(line) for line in lines) + max(len(lines) - 1, 0)


def _clip(text: str, limit: int) -> str:
    """The last resort: one line longer than the whole budget."""
    if limit <= 1:
        return text[:limit]
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space >= int(limit * 0.8):
        cut = cut[:space]
    return cut + "…"


def summary(raw: object, *, code: object = None, limit: int = 300) -> str:
    """The ONE sentence-shaped account of a failure (memo dev/127).

    The exception line first, because it is the answer; then the raising frame;
    then, when the candidate raised it itself, a note saying so — round 2 of the
    owner's trail read as a pandas error and was the model's own check. Falls
    back to a whole-line excerpt when there is no exception line to find, and
    never invents structure it cannot see.
    """
    line = exception_line(raw)
    if line is None:
        return excerpt(raw, limit=limit)
    parts = [line]
    frame = raising_frame(raw)
    if frame:
        parts.append(f"at {frame}")
    if is_self_raised(raw, code):
        parts.append("raised by the code's own check, not by the library")
    if is_chained(raw):
        parts.append("(one of several chained exceptions — the trail has the rest)")
    text = " · ".join(parts)
    return text if len(text) <= limit else excerpt(text, limit=limit, head=True)
