"""Typed agent content parts + the structured-tail protocol (memo ``dev/39``).

An agent reply may end with exactly one fenced block::

    ```curio.v1
    {"suggestedPrompts": {"primary": "...", "alternatives": ["..."]}}
    ```

The runtime strips a **terminal** block from the reply, validates it against
the bounded v1 part contracts below, and persists the resulting parts on the
agent turn (`DEC-043`). Fail-open for model content: a malformed, oversized,
or unknown block is *not* stripped — it stays visible exactly as the model
wrote it and no parts attach; nothing the model says is ever silently lost.
Bounds are enforced here, server-side, never trusted from the model.

Part types (v1) and their bounds — the single place limits are named:

- ``suggestedPrompts``: ``{primary, alternatives[]}`` — primary and each
  alternative ≤ 200 chars, ≤ 3 alternatives (de-duplicated), ≤ 1 such part.
- ``card``: ``{kind, title, lines[]}`` — kind ≤ 64, title ≤ 120, ≤ 10 lines
  of ≤ 300 chars, ≤ 4 cards. Cards are informational plain data: no actions,
  no interpreted markup (docs/08 — actions are suggested prompts, not
  buttons). Producers arrive with the P5 composites; the contract and the
  renderer exist now so they have something to land on.
"""

from __future__ import annotations

import json

TAIL_FENCE = "```curio.v1"
TAIL_MAX_BYTES = 4096
MAX_PARTS = 8

_PROMPT_MAX_CHARS = 200
_MAX_ALTERNATIVES = 3
_CARD_KIND_MAX_CHARS = 64
_CARD_TITLE_MAX_CHARS = 120
_CARD_LINE_MAX_CHARS = 300
_CARD_MAX_LINES = 10
_MAX_CARDS = 4

# The runtime-owned instruction appended to every attachment run's system turn
# (after the preamble + intent composition, dev/38 — so an edited intent can
# neither strip nor spoof it). Deliberately optional in tone, and it invites
# only suggestedPrompts: the card contract exists (above) but nothing should
# prompt the model to fabricate result cards before a real producer exists.
TAIL_INSTRUCTION = (
    "When one or more follow-up prompts would help the user continue, you may "
    "end your reply with exactly one fenced block of this form:\n"
    "```curio.v1\n"
    '{"suggestedPrompts": {"primary": "<the single most useful next prompt>", '
    '"alternatives": ["<up to 3 short alternative prompts>"]}}\n'
    "```\n"
    "The block must be the very last thing in the reply, the JSON must be "
    "valid, and each prompt must stay under 200 characters. Omit the block "
    "entirely when no follow-up is useful."
)


def split_tail(reply: str) -> tuple[str, str | None]:
    """Split *reply* into ``(visible_text, tail_body_or_None)``.

    Only a **terminal** block counts: the last `````curio.v1`` fence whose
    closing ``````` is followed by nothing but whitespace. Fenced blocks
    mid-reply (e.g. the model quoting the syntax) are body text.
    """
    if not isinstance(reply, str):
        return reply, None
    idx = reply.rfind(TAIL_FENCE)
    if idx == -1:
        return reply, None
    # The fence must start the reply or its own line.
    if idx > 0 and reply[idx - 1] != "\n":
        return reply, None
    after = reply[idx + len(TAIL_FENCE) :]
    if not after.startswith("\n"):
        return reply, None
    close = after.find("\n```")
    if close == -1:
        return reply, None
    if after[close + 4 :].strip():
        return reply, None  # content after the closing fence — not terminal
    body = after[1:close]
    visible = reply[:idx].rstrip()
    return visible, body


def _valid_prompt(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _PROMPT_MAX_CHARS:
        return None
    return text


def _parse_suggested_prompts(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    primary = _valid_prompt(raw.get("primary"))
    if primary is None:
        return None
    alts_raw = raw.get("alternatives", [])
    if not isinstance(alts_raw, list) or len(alts_raw) > _MAX_ALTERNATIVES:
        return None
    alternatives: list[str] = []
    for alt in alts_raw:
        text = _valid_prompt(alt)
        if text is None:
            return None
        if text != primary and text not in alternatives:
            alternatives.append(text)
    return {"type": "suggestedPrompts", "primary": primary, "alternatives": alternatives}


def _parse_card(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    title = raw.get("title")
    if not (isinstance(kind, str) and kind.strip() and len(kind) <= _CARD_KIND_MAX_CHARS):
        return None
    if not (isinstance(title, str) and title.strip() and len(title) <= _CARD_TITLE_MAX_CHARS):
        return None
    lines_raw = raw.get("lines", [])
    if not isinstance(lines_raw, list) or len(lines_raw) > _CARD_MAX_LINES:
        return None
    lines: list[str] = []
    for line in lines_raw:
        if not isinstance(line, str) or len(line) > _CARD_LINE_MAX_CHARS:
            return None
        lines.append(line)
    return {"type": "card", "kind": kind.strip(), "title": title.strip(), "lines": lines}


def parse_parts(body: str) -> list[dict] | None:
    """Validate a tail body into typed parts, or ``None`` when the whole block
    is invalid (bad JSON, over bounds, a malformed known part, or nothing
    usable). Unknown top-level keys are ignored — forward tolerance — but a
    *known* key that fails its contract invalidates the block (fail-open to
    text beats attaching half-validated content)."""
    if not isinstance(body, str) or len(body.encode("utf-8")) > TAIL_MAX_BYTES:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    parts: list[dict] = []
    if "cards" in payload:
        cards_raw = payload["cards"]
        if not isinstance(cards_raw, list) or len(cards_raw) > _MAX_CARDS:
            return None
        for raw in cards_raw:
            card = _parse_card(raw)
            if card is None:
                return None
            parts.append(card)
    if "suggestedPrompts" in payload:
        prompts = _parse_suggested_prompts(payload["suggestedPrompts"])
        if prompts is None:
            return None
        parts.append(prompts)
    if not parts or len(parts) > MAX_PARTS:
        return None
    return parts


def extract_content(reply: str) -> tuple[str, list[dict]]:
    """The runtime entry point: ``(visible_text, parts)`` for one reply.

    A valid terminal tail is stripped and returned as parts; anything else —
    no tail, malformed tail, unknown-only payload — returns the reply
    untouched with no parts (fail-open, §4.2 of memo dev/39).
    """
    visible, body = split_tail(reply)
    if body is None:
        return reply, []
    parts = parse_parts(body)
    if parts is None:
        return reply, []
    return visible, parts
