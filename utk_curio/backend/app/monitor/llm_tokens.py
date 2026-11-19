"""Each model's LLM tokens, per UTC hour, for the running process.

``agents/infrastructure/providers.py`` records every request here once, right
after the request, with the usage its provider reported (:func:`record`): the
input and output tokens, and whether the model ran on this Curio's own endpoint
(``ProviderConfig.on_deployment``) or on a key a user set for their own.
``GET /api/monitor/llm`` publishes :func:`snapshot`: the hourly rows of the
last 7 days, and each model's totals over 24 hours, 7 days and every hour kept.

The rows are the monitor history ``llm-tokens`` (``history.py``): written to
``.curio/monitor/llm-tokens.json`` as they change, started over when the
backend starts, and at most 90 days of hours, the oldest going first.

THE ONE FREE TEXT ON AN AGGREGATE ROUTE. The model names are the owner's call:
Curio's own and the ones users type for their own keys both appear on this
public page. A name that is not plainly a model's (a URL, a host, an email
address, an IP address, something shaped like a key, spaces, more than
:data:`MAX_MODEL_CHARS` characters) is recorded as :data:`OTHER`
(:func:`public_model_name`). A day holds at most :data:`MAX_MODELS_PER_DAY`
names and the route lists at most :data:`MAX_MODELS_SHOWN`, the rest counted
as :data:`OTHER`, so the file and the page stay bounded whatever names arrive.

THE CACHE. As the storage walk's: the route's body is held for
:data:`TTL_SECONDS` and recomputed under the lock, and sooner once the history
changed (``History.version``), so the page sees a request at its next poll.

SEVERAL BACKEND PROCESSES. Each process records the requests of the turns it
runs, in its own rows and file. The home process's route asks every other
process for its :func:`part`, counted against the home process's clock
(:func:`asked_at`), and :func:`merged` shows them as one process holding every
row would: rows of the same hour and model summed, then the models past
:data:`MAX_MODELS_SHOWN` counted as :data:`OTHER`. That body is computed at
each call, since another process's rows change without this one's version.

Never raises, as ``counters.py`` never does: a request must never fail over its
bookkeeping.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone

from utk_curio.backend.app.monitor import history as monitor_history

#: The hourly rows the route returns: the current hour and the 167 before it.
HOURLY_HOURS = 7 * 24
#: The page polls this route every 60 s, as it polls the storage walk.
TTL_SECONDS = 60
#: What a name that is not plainly a model's is recorded as.
OTHER = "other"
MAX_MODEL_CHARS = 100
#: The distinct models, each on Curio's endpoint or an own key, a day's rows
#: hold; a new one past them is counted as :data:`OTHER`.
MAX_MODELS_PER_DAY = 20
#: The models the route lists, by tokens kept; the rest are summed as :data:`OTHER`.
MAX_MODELS_SHOWN = 40

#: Each row: ``{hour, model, curio, inputTokens, outputTokens, requests}``.
HISTORY = monitor_history.History("llm-tokens")

_FIELDS = ("inputTokens", "outputTokens", "requests")
#: The windows each model's totals cover.
_WINDOWS = ("last24h", "last7d", "kept")

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


def record(model, *, curio: bool, input_tokens, output_tokens) -> None:
    """Count one request that *model* answered, in this UTC hour. Never raises."""
    try:
        name = public_model_name(model)
        curio = bool(curio)
        hour = _now().strftime(monitor_history.HOUR)
        added = {"inputTokens": _count(input_tokens), "outputTokens": _count(output_tokens), "requests": 1}

        def add(rows: list[dict]) -> None:
            day = _rows_of_day(rows, hour[:10])
            names = {(row["model"], row["curio"]) for row in day}
            key = (name, curio)
            if key not in names and len(names) >= MAX_MODELS_PER_DAY:
                key = (OTHER, curio)
            row = next((row for row in day if (row["hour"], row["model"], row["curio"]) == (hour, *key)), None)
            if row is None:
                row = {"hour": hour, "model": key[0], "curio": key[1], **_zero()}
                rows.append(row)
            for field, value in added.items():
                row[field] += value

        HISTORY.update(add)
    except Exception:  # noqa: BLE001 - a request never fails over its bookkeeping
        pass


def snapshot() -> dict:
    """The route's body: the hourly rows of the last :data:`HOURLY_HOURS`
    hours and each model's totals, computed again once the history changed,
    else at most once per :data:`TTL_SECONDS`."""
    now = time.monotonic()
    with _LOCK:
        version = HISTORY.version
        cached = _cache.get("value")
        age = now - _cache.get("at", 0.0)
        if cached is not None and _cache.get("version") == version and age < TTL_SECONDS:
            return _with_age(cached, age)
        value = _summarise()
        _cache.update(value=value, at=time.monotonic(), version=version)
        return _with_age(value, 0.0)


def asked_at() -> dict:
    """What the home process asks every other process for its :func:`part`
    with: its clock, which each counts its tokens against, so every process's
    hours and windows are the home process's."""
    return {"now": _now().strftime(monitor_history.STAMP)}


def part(arguments: dict) -> dict:
    """This process's tokens as another backend process of its start sends
    them to the home process (``processes.py``), counted against the clock
    *arguments* names (:func:`asked_at`): each model's rows of the last
    :data:`HOURLY_HOURS` hours and its totals, none counted as :data:`OTHER`
    yet, and when this process's history began."""
    tally = _tally(HISTORY.rows(), _moment(arguments))
    return {
        "startedAt": HISTORY.started_at.strftime(monitor_history.STAMP),
        "hourly": [{"hour": hour, "model": model, "curio": curio, **counts}
                   for (hour, model, curio), counts in tally["hourly"].items()],
        "totals": [{"model": model, "curio": curio, **windows}
                   for (model, curio), windows in tally["totals"].items()],
    }


def merged(arguments: dict, others: list) -> dict:
    """The route's body in a start of several backend processes: this
    process's tokens and every other process's :func:`part`, counted against
    the clock *arguments* names, as one process holding every row would show
    them. Computed at each call."""
    now = _moment(arguments)
    tally = _tally(HISTORY.rows(), now)
    started = HISTORY.started_at.strftime(monitor_history.STAMP)
    for each in others:
        if not isinstance(each, dict):
            continue
        _add_tally(tally, _tally_of_part(each))
        begun = each.get("startedAt")
        if isinstance(begun, str) and begun < started:
            started = begun
    return _with_age(_present(tally, now, started), 0.0)


def reset() -> None:
    """Drop every row, as a backend start does, and the cache. For tests only."""
    HISTORY.start()
    with _LOCK:
        _cache.update(value=None, at=0.0, version=None)


def _moment(arguments) -> datetime:
    """The clock *arguments* names (:func:`asked_at`), else this process's."""
    text = arguments.get("now") if isinstance(arguments, dict) else None
    try:
        return datetime.strptime(text, monitor_history.STAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return _now()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _zero() -> dict:
    return {field: 0 for field in _FIELDS}


def _count(value) -> int:
    """A token count as a provider reported it; anything else counts nothing."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _add(total: dict, row: dict) -> None:
    for field in _FIELDS:
        total[field] += row[field]


def _rows_of_day(rows: list[dict], day: str) -> list[dict]:
    """The rows of *day* (``YYYY-MM-DD``) at the end of *rows*, where the
    newest are."""
    found = []
    for row in reversed(rows):
        if not row["hour"].startswith(day):
            break
        found.append(row)
    return found


def _counted(row: dict) -> bool:
    return isinstance(row.get("model"), str) and isinstance(row.get("curio"), bool) and all(
        isinstance(row.get(field), int) and not isinstance(row.get(field), bool) for field in _FIELDS)


def _windows() -> dict:
    return {window: _zero() for window in _WINDOWS}


def _shown(totals: dict) -> set:
    """The models listed: the :data:`MAX_MODELS_SHOWN` with the most tokens kept."""
    tokens = {key: windows["kept"]["inputTokens"] + windows["kept"]["outputTokens"]
              for key, windows in totals.items()}
    ranked = sorted(tokens, key=lambda key: (-tokens[key], key[0], not key[1]))
    return set(ranked[:MAX_MODELS_SHOWN])


def _summarise() -> dict:
    now = _now()
    return _present(_tally(HISTORY.rows(), now), now, HISTORY.started_at.strftime(monitor_history.STAMP))


def _tally(rows: list, now: datetime) -> dict:
    """*rows* counted against *now*: each model's tokens per hour of the last
    :data:`HOURLY_HOURS` hours (``hourly``, by hour, model and endpoint) and
    each model's totals over the 24 hours, the 7 days and every hour kept
    (``totals``, by model and endpoint), no model counted as :data:`OTHER`."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    first = hour - timedelta(hours=HOURLY_HOURS - 1)
    day_ago = hour - timedelta(hours=23)
    hourly: dict = {}
    totals: dict = {}
    for row in rows:
        at = monitor_history.hour_of(row.get("hour")) if isinstance(row, dict) else None
        if at is None or not _counted(row):
            continue
        key = (row["model"], row["curio"])
        windows = totals.setdefault(key, _windows())
        _add(windows["kept"], row)
        # A row dated past this hour (a clock set back) is kept, outside the windows.
        if first <= at <= hour:
            _add(windows["last7d"], row)
            _add(hourly.setdefault((row["hour"], *key), _zero()), row)
            if at >= day_ago:
                _add(windows["last24h"], row)
    return {"hourly": hourly, "totals": totals}


def _tally_of_part(each: dict) -> dict:
    """Another process's :func:`part` as a tally; what is not counts is left out."""
    tally: dict = {"hourly": {}, "totals": {}}
    for row in each.get("hourly") or ():
        if isinstance(row, dict) and monitor_history.hour_of(row.get("hour")) is not None and _counted(row):
            _add(tally["hourly"].setdefault((row["hour"], row["model"], row["curio"]), _zero()), row)
    for entry in each.get("totals") or ():
        if not isinstance(entry, dict) or not isinstance(entry.get("model"), str) or not isinstance(
                entry.get("curio"), bool):
            continue
        if not all(isinstance(entry.get(window), dict) and _counted_counts(entry[window]) for window in _WINDOWS):
            continue
        windows = tally["totals"].setdefault((entry["model"], entry["curio"]), _windows())
        for window in _WINDOWS:
            _add(windows[window], entry[window])
    return tally


def _add_tally(tally: dict, more: dict) -> None:
    """Add the tally *more* into *tally*."""
    for key, counts in more["hourly"].items():
        _add(tally["hourly"].setdefault(key, _zero()), counts)
    for key, windows in more["totals"].items():
        into = tally["totals"].setdefault(key, _windows())
        for window in _WINDOWS:
            _add(into[window], windows[window])


def _counted_counts(counts: dict) -> bool:
    return all(isinstance(counts.get(field), int) and not isinstance(counts.get(field), bool) for field in _FIELDS)


def _present(tally: dict, now: datetime, started: str) -> dict:
    """The route's body from *tally*, counted against *now*, of a history
    begun at *started*: the models past :data:`MAX_MODELS_SHOWN` counted as
    :data:`OTHER`, most tokens kept first, and the hourly rows in order."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    first = hour - timedelta(hours=HOURLY_HOURS - 1)
    shown = _shown(tally["totals"])

    def folded(key: tuple) -> tuple:
        return key if key in shown else (OTHER, key[1])

    totals: dict = {}
    for key, windows in tally["totals"].items():
        into = totals.setdefault(folded(key), _windows())
        for window in _WINDOWS:
            _add(into[window], windows[window])
    hourly: dict = {}
    for (at, model, curio), counts in tally["hourly"].items():
        _add(hourly.setdefault((at, *folded((model, curio))), _zero()), counts)

    models = [{"model": model, "curio": curio, **windows} for (model, curio), windows in totals.items()]
    models.sort(key=lambda entry: (-(entry["kept"]["inputTokens"] + entry["kept"]["outputTokens"]),
                                   entry["model"], not entry["curio"]))
    return {
        "computedAt": now.strftime(monitor_history.STAMP),
        "startedAt": started,
        "maxDays": HISTORY.max_days,
        "hourlyFrom": first.strftime(monitor_history.HOUR),
        "hourlyTo": hour.strftime(monitor_history.HOUR),
        "hourly": [
            {"hour": at, "model": model, "curio": curio, **counts}
            for (at, model, curio), counts in sorted(
                hourly.items(), key=lambda item: (item[0][0], item[0][1], not item[0][2]))
        ],
        "models": models,
    }


def _with_age(value: dict, age: float) -> dict:
    out = dict(value)
    out["ageSeconds"] = int(age)
    out["ttlSeconds"] = TTL_SECONDS
    return out
