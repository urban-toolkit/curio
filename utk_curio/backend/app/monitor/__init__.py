"""The monitor page's backend: counters, aggregate stats, LLM tokens, open files, and an error log.

Curio had no way to say how an instance was doing. `/version` reported three
fields and everything else lived in `.curio/messages.log`, which is truncated
on every launch. This package answers "what has this instance been doing, and
what went wrong" over six routes (see `routes.py`).

Two postures, deliberately different, and the split is the point:

- `/api/monitor`, `/api/monitor/storage`, `/api/monitor/llm` and
  `/api/monitor/open-files` are **aggregates only**. They carry counts and
  distributions and never a username, an email, an IP or a per-user row.
  `tests/test_monitor/test_monitor_payload_is_anonymous.py` enforces that with
  a recursive leaf-type allowlist, so a field added later fails the test rather
  than quietly publishing a name. The LLM route's model names are the one free
  text allowed, by the owner's call, and still scanned (`llm_tokens.py`).
- `/api/monitor/errors` is **raw**, by an explicit product decision, and is
  therefore exempt from that rule. See its docstring in `errors.py` for what
  that exposes and what an operator should do about it.

The counters and the error log cover the running process and are bounded:
counters are ints, the duration window is a fixed-length deque, and every
number resets when the process restarts, which is why `uptimeSeconds` ships in
the payload. The histories (`history.py`: the LLM tokens of `llm_tokens.py`,
and the servers' open files that `open_files.py` samples every hour) are kept
across restarts instead: one file each in the monitor folder (`--monitor-dir`,
`.curio/monitor` by default), which every backend process writes, the last 90
days.

In a start of several backend processes each process holds its own counters
and error log, and the home process, which nginx sends every monitor route to,
asks the others for their parts and merges them (`processes.py`); with one
process nothing is asked.
"""
