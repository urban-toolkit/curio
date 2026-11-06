"""The monitor page's backend: counters, aggregate stats, LLM tokens, and an error log.

Curio had no way to say how an instance was doing. `/version` reported three
fields and everything else lived in `.curio/messages.log`, which is truncated
on every launch. This package answers "what has this instance been doing, and
what went wrong" over five routes (see `routes.py`).

Two postures, deliberately different, and the split is the point:

- `/api/monitor`, `/api/monitor/storage` and `/api/monitor/llm` are
  **aggregates only**. They carry counts and distributions and never a
  username, an email, an IP or a per-user row.
  `tests/test_monitor/test_monitor_payload_is_anonymous.py` enforces that with
  a recursive leaf-type allowlist, so a field added later fails the test rather
  than quietly publishing a name. The LLM route's model names are the one free
  text allowed, by the owner's call, and still scanned (`llm_tokens.py`).
- `/api/monitor/errors` is **raw**, by an explicit product decision, and is
  therefore exempt from that rule. See its docstring in `errors.py` for what
  that exposes and what an operator should do about it.

Everything here covers the running process and is bounded: counters are ints,
the duration window is a fixed-length deque, and every number resets when the
process restarts, which is why `uptimeSeconds` ships in the payload. The
hourly histories (`history.py`: the LLM tokens of `llm_tokens.py`) are also
written to `.curio/monitor/<name>.json` as they change, hold at most 90 days,
and start over, file included, when the backend starts.
"""
