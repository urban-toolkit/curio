"""Each model's LLM tokens, per UTC hour, kept on disk for 90 days.

``agents/infrastructure/providers.py`` records every request here once, right
after the request, with the usage its provider reported (:func:`record`): the
input and output tokens, and whether the model ran on this Curio's own endpoint
(``ProviderConfig.on_deployment``) or on a key a user set for their own.
``GET /api/monitor/llm`` publishes :func:`snapshot`: the hourly rows of the
last 7 days, and each model's totals over 24 hours, 7 days and every day kept.

UNLIKE THE REST OF THE MONITOR, THIS IS KEPT. One JSON file per UTC day,
``<state>/monitor/llm-tokens/<YYYY-MM-DD>.json``, in the ``.curio`` tree
``user_storage.curio_root`` resolves, so the counts outlive a restart. A write
deletes the day files older than :data:`KEEP_DAYS`, and a read skips them. A
write holds the two-layer lock (``common/file_locks``) from its read to its
replace, so two requests that end at once both count, and a reader sees the
old file or the new one, never part of one.

THE ONE FREE TEXT ON AN AGGREGATE ROUTE. The model names are the owner's call:
Curio's own and the ones users type for their own keys both appear on this
public page. A name that is not plainly a model's (a URL, a host, an email
address, an IP address, something shaped like a key, spaces, more than
:data:`MAX_MODEL_CHARS` characters) is recorded as :data:`OTHER`
(:func:`public_model_name`). A day holds at most :data:`MAX_MODELS_PER_DAY`
names and the route lists at most :data:`MAX_MODELS_SHOWN`, the rest counted
as :data:`OTHER`, so the files and the page stay bounded whatever names arrive.

THE CACHE. As the storage walk's: the route's body is held for
:data:`TTL_SECONDS` and recomputed under the lock. A record clears it, so the
page sees a request at its next poll.

Never raises, as ``counters.py`` never does: a request must never fail over its
bookkeeping.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

#: How many UTC days are kept: today and the 89 before it.
KEEP_DAYS = 90
#: The hourly rows the route returns: the current hour and the 167 before it.
HOURLY_HOURS = 7 * 24
#: The page polls this route every 60 s, as it polls the storage walk.
TTL_SECONDS = 60
#: What a name that is not plainly a model's is recorded as.
OTHER = "other"
MAX_MODEL_CHARS = 100
#: The distinct models, each on Curio's endpoint or an own key, a day file
#: holds; a new one past them is counted as :data:`OTHER`.
MAX_MODELS_PER_DAY = 40
#: The models the route lists, by tokens kept; the rest are summed as :data:`OTHER`.
MAX_MODELS_SHOWN = 40

_HOUR = "%Y-%m-%dT%H:00:00Z"
_STAMP = "%Y-%m-%dT%H:%M:%SZ"
_FIELDS = ("inputTokens", "outputTokens", "requests")
_DAY_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})\.json")
_LOCK_FILE = ".lock"

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
        from utk_curio.backend.app.common.file_locks import exclusive_lock

        name = public_model_name(model)
        curio = bool(curio)
        now = _now()
        hour = now.strftime(_HOUR)
        directory = _directory()
        directory.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(directory / _LOCK_FILE, namespace="monitor-llm-tokens", key=str(directory)):
            path = directory / f"{now.date().isoformat()}.json"
            rows = _read(path)
            names = {(row["model"], row["curio"]) for row in rows}
            if (name, curio) not in names and len(names) >= MAX_MODELS_PER_DAY:
                name = OTHER
            row = next((row for row in rows
                        if (row["hour"], row["model"], row["curio"]) == (hour, name, curio)), None)
            if row is None:
                row = {"hour": hour, "model": name, "curio": curio, **_zero()}
                rows.append(row)
            row["inputTokens"] += _count(input_tokens)
            row["outputTokens"] += _count(output_tokens)
            row["requests"] += 1
            _write(path, {"rows": rows})
            _prune(directory, now.date())
        with _LOCK:
            _cache["value"] = None
    except Exception:  # noqa: BLE001 - a request never fails over its bookkeeping
        pass


def snapshot() -> dict:
    """The route's body: the hourly rows of the last :data:`HOURLY_HOURS`
    hours and each model's totals, read at most once per :data:`TTL_SECONDS`."""
    now = time.monotonic()
    with _LOCK:
        cached = _cache.get("value")
        age = now - _cache.get("at", 0.0)
        if cached is not None and age < TTL_SECONDS:
            return _with_age(cached, age)
        value = _summarise()
        _cache["value"] = value
        _cache["at"] = time.monotonic()
        return _with_age(value, 0.0)


def reset() -> None:
    """Drop the cache. For tests only."""
    with _LOCK:
        _cache["value"] = None
        _cache["at"] = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _directory() -> Path:
    """Where the day files are, resolved at each call as the rest of the
    ``.curio`` tree is, so ``CURIO_STATE_DIR`` moves them too."""
    from utk_curio.backend.app.common import user_storage

    return user_storage.curio_root() / "monitor" / "llm-tokens"


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


def _hour_of(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, _HOUR).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _day_of(path: Path) -> date | None:
    match = _DAY_FILE.fullmatch(path.name)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _read(path: Path) -> list[dict]:
    """The rows of one day file, each read afresh: none for a missing or an
    unreadable file, and a row that is not one is left out."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = doc.get("rows") if isinstance(doc, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or _hour_of(row.get("hour")) is None:
            continue
        if not isinstance(row.get("model"), str) or not isinstance(row.get("curio"), bool):
            continue
        if not all(isinstance(row.get(field), int) and not isinstance(row.get(field), bool)
                   and row[field] >= 0 for field in _FIELDS):
            continue
        out.append({"hour": row["hour"], "model": public_model_name(row["model"]),
                    "curio": row["curio"], **{field: row[field] for field in _FIELDS}})
    return out


def _write(path: Path, doc: dict) -> None:
    """*doc* to *path* through a temp file beside it and ``os.replace``, so a
    reader sees the old file or the new one. Not fsynced: a crash may lose the
    latest counts, and every request writes."""
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _prune(directory: Path, today: date) -> None:
    """Delete the day files older than :data:`KEEP_DAYS`."""
    oldest = today - timedelta(days=KEEP_DAYS - 1)
    for path in directory.iterdir():
        day = _day_of(path)
        if day is not None and day < oldest:
            try:
                path.unlink()
            except OSError:
                pass


def _kept_rows(today: date) -> list[dict]:
    """Every row of the day files kept, oldest day first; none when the
    folder cannot be read."""
    oldest = today - timedelta(days=KEEP_DAYS - 1)
    try:
        paths = sorted(_directory().iterdir())
    except Exception:  # noqa: BLE001 - no folder yet, or none to read: nothing kept
        return []
    rows: list[dict] = []
    for path in paths:
        day = _day_of(path)
        if day is not None and day >= oldest:
            rows.extend(_read(path))
    return rows


def _shown(rows: list[tuple]) -> set:
    """The models listed: the :data:`MAX_MODELS_SHOWN` with the most tokens kept."""
    tokens: dict = {}
    for _at, row in rows:
        key = (row["model"], row["curio"])
        tokens[key] = tokens.get(key, 0) + row["inputTokens"] + row["outputTokens"]
    ranked = sorted(tokens, key=lambda key: (-tokens[key], key[0], not key[1]))
    return set(ranked[:MAX_MODELS_SHOWN])


def _summarise() -> dict:
    now = _now()
    hour = now.replace(minute=0, second=0, microsecond=0)
    first = hour - timedelta(hours=HOURLY_HOURS - 1)
    day_ago = hour - timedelta(hours=23)
    rows = [(_hour_of(row["hour"]), row) for row in _kept_rows(now.date())]
    shown = _shown(rows)

    hourly: dict = {}
    totals: dict = {}
    for at, row in rows:
        key = (row["model"], row["curio"])
        if key not in shown:
            key = (OTHER, row["curio"])
        windows = totals.setdefault(key, {"last24h": _zero(), "last7d": _zero(), "kept": _zero()})
        _add(windows["kept"], row)
        # A row dated past this hour (a clock set back) is kept, outside the windows.
        if first <= at <= hour:
            _add(windows["last7d"], row)
            _add(hourly.setdefault((at, *key), _zero()), row)
            if at >= day_ago:
                _add(windows["last24h"], row)

    models = [{"model": model, "curio": curio, **windows} for (model, curio), windows in totals.items()]
    models.sort(key=lambda entry: (-(entry["kept"]["inputTokens"] + entry["kept"]["outputTokens"]),
                                   entry["model"], not entry["curio"]))
    return {
        "computedAt": now.strftime(_STAMP),
        "keptDays": KEEP_DAYS,
        "hourlyFrom": first.strftime(_HOUR),
        "hourlyTo": hour.strftime(_HOUR),
        "hourly": [
            {"hour": at.strftime(_HOUR), "model": model, "curio": curio, **counts}
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
