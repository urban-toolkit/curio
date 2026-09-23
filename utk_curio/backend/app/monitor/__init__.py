"""The monitor page's backend: counters, aggregate stats, and an error log.

Curio had no way to say how an instance was doing. `/version` reported three
fields and everything else lived in `.curio/messages.log`, which is truncated
on every launch. This package answers "what has this instance been doing, and
what went wrong" over four routes (see `routes.py`).

Two postures, deliberately different, and the split is the point:

- `/api/monitor` and `/api/monitor/storage` are **aggregates only**. They carry
  counts and distributions and never a username, an email, an IP or a per-user
  row. `tests/test_monitor/test_monitor_payload_is_anonymous.py` enforces that
  with a recursive leaf-type allowlist, so a field added later fails the test
  rather than quietly publishing a name.
- `/api/monitor/errors` is **raw**, by an explicit product decision, and is
  therefore exempt from that rule. See its docstring in `errors.py` for what
  that exposes and what an operator should do about it.

Everything here is in-process and bounded: counters are ints, history is a
fixed-length deque. Nothing is persisted, so every number resets when the
process restarts, which is why `uptimeSeconds` ships in the payload.
"""
