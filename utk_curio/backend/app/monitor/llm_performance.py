"""The performance of this Curio's own LLM models over the last 90 days, kept
across restarts.

``agents/infrastructure/providers.py`` records each request on this Curio's
own endpoint (``ProviderConfig.on_deployment``) here once, as it ends
(:func:`record`): its time, from before it was asked to its end; a stream's
time to its first word or call; the output tokens its provider reported; and
whether it failed (raised). A request on a key a user set for their own is not
recorded, so no model name a user typed reaches this public page.

The rows are the monitor history ``llm`` (``history.py``), one file every
backend process writes, ``llm.json`` in the monitor folder: a request adds to
the row its process holds for its 5 minutes and model, which the process's
writer adds to the file's within a minute. A row holds sums alone, so the rows
of any number of processes add up exactly: ``{at, span, model, requests,
failed, ms, buckets, firstTokenMs, firstTokens, outputTokens, outputMs}``, the
requests and those that failed, their total milliseconds and their count in
each of the 14 duration buckets (``durations.py``), the total milliseconds to
the first token of the streams that wrote one and how many did, and the output
tokens of the requests whose provider reported them with those requests' total
milliseconds. The route reads the file alone, so a request shows once its
process wrote it, and each process's requests count once.

``GET /api/monitor/llm`` publishes :func:`snapshot`: three views of the rows,
the last 24 hours (the current 5-minute slot and the 287 before it) in 5-minute
rows, the last 7 days (the current hour and the 167 before it) in hourly rows,
and the last 90 days (the current UTC day and the 89 before it) in daily rows.
Each view gives its first and last row's start, its rows' requests, failures
and milliseconds by model for its chart, and, over the whole view, each
model's and all models' requests, failed requests, average and 95th percentile
time, average time to the first token, and output tokens per second (the
output tokens over the time of the requests that reported them). A row dated
past the current 5 minutes (a clock set back) is kept, outside the views.

THE ONE FREE TEXT ON AN AGGREGATE ROUTE: the names of this Curio's models,
which the operator's endpoint file gives. A name that is not plainly a model's
(a URL, a host, an email address, an IP address, something shaped like a key,
spaces, more than :data:`MAX_MODEL_CHARS` characters) is recorded as
:data:`OTHER` all the same (:func:`public_model_name`). A day holds at most
:data:`MAX_MODELS_PER_DAY` names, counted as the file takes each
(:func:`_admitted`), and the route lists at most :data:`MAX_MODELS_SHOWN`, the
rest counted as :data:`OTHER`, so the file and the page stay bounded whatever
names arrive.

THE CACHE. As the storage walk's: the route's body is held for
:data:`TTL_SECONDS` and recomputed under the lock, and sooner once the file
changed (``History.stamp``), so the page sees a write at its next poll.

Never raises, as ``counters.py`` never does: a request must never fail over its
bookkeeping.
"""

from __future__ import annotations

import itertools
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from utk_curio.backend.app.monitor import durations
from utk_curio.backend.app.monitor import history as monitor_history

#: The page polls this route every 60 s, as it polls the storage walk.
TTL_SECONDS = 60
#: What a name that is not plainly a model's is recorded as.
OTHER = "other"
MAX_MODEL_CHARS = 100
#: The distinct models a day's rows hold; a new one past them is counted as
#: :data:`OTHER`.
MAX_MODELS_PER_DAY = 20
#: The models the route lists, by requests kept; the rest are summed as :data:`OTHER`.
MAX_MODELS_SHOWN = 40

#: What a row counts: its model.
_IDENTITY = ("model",)
#: A row's sums besides its duration buckets, each a whole number.
_SUMS = ("requests", "failed", "ms", "firstTokenMs", "firstTokens", "outputTokens", "outputMs")
#: The views the route gives: each one's name, the time a row of it covers,
#: and how many such times it spans, the current one among them.
_VIEWS = (
    ("24h", timedelta(minutes=5), 24 * 12),
    ("7d", timedelta(hours=1), 7 * 24),
    ("90d", timedelta(days=1), 90),
)

# -- what is plainly a model's name --------------------------------------------

#: The characters model ids are written in: Ollama's ``llama3.1:8b``,
#: Bedrock's ``us.anthropic.claude-3-5-sonnet-20241022-v2:0``, Vertex AI's
#: ``claude-3-5-sonnet@20240620``, Hugging Face's ``meta-llama/Llama-3.1-8B``.
_MODEL_CHARS = re.compile(r"[\w.:/@+-]+")
#: Addresses and keys anywhere in a name. The email and IPv4 shapes are the
#: ones ``test_monitor_payload_is_anonymous.py`` scans payloads for.
_ANYWHERE = (
    re.compile(r"[a-z][a-z0-9+.-]*://", re.I),
    re.compile(r"(?:^|/)www\.", re.I),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
    re.compile(r"(?<![0-9a-z])[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![0-9a-z])", re.I),
    re.compile(r"^(?:sk[-_]|gsk_|xai-|hf_|ghp_|github_pat_|AIza)|[A-Za-z0-9]{32,}"),
)
#: Hosts, as a whole part of a name between slashes: a name with a top-level
#: domain (``llm.example.com``, ``hf.co``), or one with a port, or localhost.
_WHOLE_PART = (
    re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}\.?(?::\d{1,5})?", re.I),
    re.compile(r"[a-z0-9-]+:\d{2,5}", re.I),
    re.compile(r"localhost(?::\d{1,5})?", re.I),
)

_LOCK = threading.Lock()
_cache: dict = {"value": None, "at": 0.0}


def public_model_name(model) -> str:
    """*model* as the monitor shows it: the name itself when it is plainly a
    model's, else :data:`OTHER`."""
    name = model.strip() if isinstance(model, str) else ""
    if not name or len(name) > MAX_MODEL_CHARS or not _MODEL_CHARS.fullmatch(name):
        return OTHER
    if any(pattern.search(name) for pattern in _ANYWHERE):
        return OTHER
    if any(pattern.fullmatch(part) for part in name.split("/") for pattern in _WHOLE_PART):
        return OTHER
    return name


def _admitted(rows: list[dict], held: list[dict]) -> list[dict]:
    """The rows a write *held*, oldest first, as the file takes them beside
    its *rows*: each under its own model while its UTC day holds fewer than
    :data:`MAX_MODELS_PER_DAY` other models, else as :data:`OTHER`."""
    days: dict = {}
    for row in rows:
        days.setdefault(str(row.get("at"))[:10], set()).add(row.get("model"))
    admitted = []
    for row in held:
        names = days.setdefault(str(row.get("at"))[:10], set())
        model = row.get("model")
        if model not in names and len(names) >= MAX_MODELS_PER_DAY:
            row = {**row, "model": OTHER}
            model = OTHER
        names.add(model)
        admitted.append(row)
    return admitted


def _history_now() -> datetime:
    """Now, read through :func:`_now` at each call, so a test's clock reaches the history."""
    return _now()


#: Each row: ``{at, span, model, requests, failed, ms, buckets, firstTokenMs,
#: firstTokens, outputTokens, outputMs}``.
HISTORY = monitor_history.History("llm", identity=_IDENTITY, admit=_admitted, clock=_history_now)


def record(model, *, ms, first_token_ms=None, output_tokens=None, failed: bool = False) -> None:
    """Count one request on this Curio's own endpoint that *model* answered,
    now: its time in milliseconds (*ms*), a stream's time to its first word or
    call (*first_token_ms*, None for a request that is not streamed or that
    wrote none), the output tokens its provider reported (None when it
    reported none), and whether it *failed*. Never raises."""
    try:
        duration = durations.whole_ms(ms)
        first = None if first_token_ms is None else durations.whole_ms(first_token_ms)
        tokens = _count(output_tokens)
        HISTORY.add({
            "model": public_model_name(model),
            "requests": 1,
            "failed": 1 if failed else 0,
            "ms": duration,
            "buckets": durations.counts(duration),
            "firstTokenMs": 0 if first is None else first,
            "firstTokens": 0 if first is None else 1,
            "outputTokens": 0 if tokens is None else tokens,
            "outputMs": 0 if tokens is None else duration,
        }, at=_now())
    except Exception:  # noqa: BLE001
        # A request never fails over its bookkeeping.
        return


def snapshot() -> dict:
    """The route's body: the three views of the rows (see the module
    docstring), computed again once the file changed, else at most once per
    :data:`TTL_SECONDS`."""
    now = time.monotonic()
    with _LOCK:
        stamp = HISTORY.stamp()
        cached = _cache.get("value")
        age = now - _cache.get("at", 0.0)
        if cached is not None and _cache.get("stamp") == stamp and age < TTL_SECONDS:
            return _with_age(cached, age)
        value = _summarise()
        _cache.update(value=value, at=time.monotonic(), stamp=stamp)
        return _with_age(value, 0.0)


def reset() -> None:
    """Drop what this process holds unwritten, and the cache. For tests only."""
    HISTORY.drop_pending()
    with _LOCK:
        _cache.update(value=None, at=0.0, stamp=None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _count(value):
    """A token count as a provider reported it; None for anything else."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, value)


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _readable(row) -> bool:
    """Whether *row* is one this version counts: a model, whole sums, and
    whole bucket counts."""
    return (isinstance(row, dict) and isinstance(row.get("model"), str)
            and all(_whole(row.get(field)) for field in _SUMS)
            and isinstance(row.get("buckets"), list) and all(_whole(count) for count in row["buckets"]))


def _sum(rows) -> dict:
    """The sums of *rows*, added up."""
    total: dict = {field: 0 for field in _SUMS}
    buckets = [0] * durations.BUCKETS
    for row in rows:
        for field in _SUMS:
            total[field] += row[field]
        buckets = [a + b for a, b in itertools.zip_longest(buckets, row["buckets"], fillvalue=0)]
    total["buckets"] = buckets
    return total


def _rounded(value):
    return None if value is None else int(round(value))


def _stats(total: dict) -> dict:
    """What the page shows of *total*, the sums of some rows: its requests and
    failed requests, the average and 95th percentile time, the average time
    to the first token, and the output tokens per second, each None when no
    request gave it."""
    output_ms = total["outputMs"]
    return {
        "requests": total["requests"],
        "failed": total["failed"],
        "averageMs": _rounded(durations.average(total["ms"], total["requests"])),
        "p95Ms": _rounded(durations.percentile(total["buckets"])),
        "firstTokenMs": _rounded(durations.average(total["firstTokenMs"], total["firstTokens"])),
        "tokensPerSecond": round(total["outputTokens"] * 1000 / output_ms, 1) if output_ms > 0 else None,
    }


def _folded(rows: list[dict]) -> list[dict]:
    """*rows* with the models past the :data:`MAX_MODELS_SHOWN` with the most
    requests kept counted as :data:`OTHER`, rows of one time and model summed."""
    requests: dict = {}
    for row in rows:
        requests[row["model"]] = requests.get(row["model"], 0) + row["requests"]
    shown = set(sorted(requests, key=lambda model: (-requests[model], model))[:MAX_MODELS_SHOWN])
    out: dict = {}
    for row in rows:
        each = row if row["model"] in shown else {**row, "model": OTHER}
        key = (each["at"], each["span"], each["model"])
        out[key] = each if key not in out else monitor_history.summed(out[key], each)
    return list(out.values())


def _last_start(now: datetime, step: timedelta) -> datetime:
    """The start of the 5 minutes, the hour or the UTC day *now* is in."""
    now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    if step == timedelta(minutes=5):
        return now.replace(minute=now.minute - now.minute % 5)
    if step == timedelta(hours=1):
        return now.replace(minute=0)
    return now.replace(hour=0, minute=0)


def _view(name: str, step: timedelta, steps: int, rows: list[dict], now: datetime) -> dict:
    """One view of *rows*: its 5-minute, hourly or daily rows from the start
    of the first of its *steps* to the start of the current one, by model,
    and their stats by model and for every model together."""
    last = _last_start(now, step)
    first = last - step * (steps - 1)
    if name == "24h":
        series = [row for row in rows if row["span"] == monitor_history.FIVE_MINUTES]
    else:
        series = monitor_history.sums_by(rows, "hour" if name == "7d" else "day", _IDENTITY)
    start, end = first.strftime(monitor_history.SLOT), last.strftime(monitor_history.SLOT)
    # Times are compared as the text they are written in, which sorts as they do.
    within = sorted((row for row in series if start <= row["at"] <= end), key=lambda row: (row["at"], row["model"]))
    by_model: dict = {}
    for row in within:
        by_model.setdefault(row["model"], []).append(row)
    totals = {model: _sum(each) for model, each in by_model.items()}
    return {
        "from": start,
        "to": end,
        "stepSeconds": int(step.total_seconds()),
        "rows": [{"at": row["at"], "model": row["model"], "requests": row["requests"], "failed": row["failed"],
                  "ms": row["ms"]} for row in within],
        "models": [{"model": model, **_stats(total)}
                   for model, total in sorted(totals.items(), key=lambda item: (-item[1]["requests"], item[0]))],
        "all": _stats(_sum(within)),
    }


def _summarise() -> dict:
    """The body, from the file's rows: the 5-minute rows of the last 24 hours
    and the hour rows before them."""
    now = _now()
    # A row dated past the current 5 minutes (a clock set back) is in no view.
    current = _last_start(now, timedelta(minutes=5)).strftime(monitor_history.SLOT)
    rows = _folded([row for row in HISTORY.rows(now=now) if _readable(row) and row["at"] <= current])
    return {
        "computedAt": now.strftime(monitor_history.STAMP),
        "maxDays": HISTORY.max_days,
        "views": {name: _view(name, step, steps, rows, now) for name, step, steps in _VIEWS},
    }


def _with_age(value: dict, age: float) -> dict:
    out = dict(value)
    out["ageSeconds"] = int(age)
    out["ttlSeconds"] = TTL_SECONDS
    return out
