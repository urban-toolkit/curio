"""Path templates: how a storage manifest says where its files are.

A storage source's manifest names each resource with a template relative to
its root, and every capture in the template becomes a typed column of the
dataset the resource adds to the Data Catalog::

    orthos/{year:int}/{tile}.tif          year -> integer, tile -> string
    dashcam/{date:date}/{sequence}_{frame:int}.jpg
    noise/{sensor}/{recorded:%Y%m%d_%H%M%S}.wav
    survey/{year:int}/**/*                 any depth below each year folder

The grammar, segment by segment (``/`` separates segments, and a file's
relpath is always POSIX):

- ``{name}`` captures part of one segment, as a string;
- ``{name:int}``, ``{name:date}`` (``YYYY-MM-DD``) and ``{name:<strftime>}``
  (``%Y %m %d %H %M %S %j %y %b``) type the capture;
- ``*`` matches within one segment and captures nothing;
- ``**``, alone as a segment, spans zero or more folders;
- anything else is literal.

Nothing here touches the filesystem, so a manifest can be validated, and a
template tested, with no folder behind it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

#: Capture names become column names, so they share one grammar with them.
CAPTURE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,31}$")

#: Columns a collection's index already has. A capture with one of these names
#: would shadow it.
RESERVED_NAMES = frozenset(
    {
        "file_id", "relpath", "name", "ext", "kind", "bytes", "mtime", "path",
        "thumbnail", "image_url", "audio_url", "dataset_id", "source_file",
        "width", "height", "duration_s", "fps", "codec", "sample_rate",
        "channels", "taken_at", "recorded_at", "gps_lat", "gps_lon", "label",
        "probe_error", "geometry", "crs", "transform", "res", "bands", "dtype",
        "nodata", "sequence", "frame", "t_s",
    }
)

#: A combined table adds only this one.
TABLE_RESERVED_NAMES = frozenset({"source_file"})

#: ``sequence`` and ``frame`` are reserved as columns but are also the captures
#: a frames resource is expected to declare, so they are allowed as captures.
CAPTURES_THAT_FILL_A_COLUMN = frozenset({"sequence", "frame"})

_STRFTIME = {
    "%Y": r"\d{4}",
    "%y": r"\d{2}",
    "%m": r"\d{2}",
    "%d": r"\d{2}",
    "%H": r"\d{2}",
    "%M": r"\d{2}",
    "%S": r"\d{2}",
    "%j": r"\d{3}",
    "%b": r"[A-Za-z]{3}",
}

_TOKEN_RE = re.compile(r"\{([^{}:]*)(?::([^{}]*))?\}|\*|[^{}*]+")

MAX_TEMPLATE_CHARS = 512
MAX_SEGMENTS = 32


class TemplateError(ValueError):
    """A path template that cannot be compiled."""


@dataclass(frozen=True)
class Capture:
    name: str
    #: ``str``, ``int``, ``date`` or ``datetime`` (with :attr:`fmt`).
    type: str
    fmt: str | None = None

    def convert(self, raw: str) -> Any:
        if self.type == "int":
            return int(raw)
        if self.type == "date":
            return date.fromisoformat(raw)
        if self.type == "datetime":
            return datetime.strptime(raw, self.fmt or "")
        return raw


@dataclass(frozen=True)
class Template:
    source: str
    regex: re.Pattern
    captures: tuple[Capture, ...]
    #: The leading folders every match shares, e.g. ``orthos/`` for
    #: ``orthos/{year:int}/{tile}.tif``. A bucket lists under this prefix only.
    literal_prefix: str

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.captures)

    def match(self, relpath: str) -> dict[str, Any] | None:
        """The typed captures for *relpath*, or None when it does not match."""
        m = self.regex.match(relpath)
        if m is None:
            return None
        out: dict[str, Any] = {}
        for capture in self.captures:
            raw = m.group(capture.name)
            try:
                out[capture.name] = capture.convert(raw)
            except ValueError:
                # ``2024-13-40`` has the right shape and is not a date. A file
                # the template cannot read is not one of its files.
                return None
        return out


def _capture_type(spec: str | None) -> tuple[str, str | None, str]:
    """``(type, strftime format, regex)`` for a capture's ``:spec``."""
    if spec is None or spec == "" or spec == "str":
        return "str", None, r"[^/]+?"
    if spec == "int":
        return "int", None, r"\d+"
    if spec == "date":
        return "date", None, r"\d{4}-\d{2}-\d{2}"
    if "%" in spec:
        parts = []
        index = 0
        while index < len(spec):
            if spec[index] == "%":
                directive = spec[index:index + 2]
                if directive not in _STRFTIME:
                    raise TemplateError(f"unsupported date directive {directive!r} in {spec!r}")
                parts.append(_STRFTIME[directive])
                index += 2
            else:
                if spec[index] in "{}/":
                    raise TemplateError(f"{spec!r} is not a date format")
                parts.append(re.escape(spec[index]))
                index += 1
        return "datetime", spec, "".join(parts)
    raise TemplateError(f"unknown capture type {spec!r}; use str, int, date or a strftime format")


def compile_template(text: str, *, reserved: frozenset[str] = RESERVED_NAMES) -> Template:
    """Compile *text*, refusing anything that could reach outside the root.

    *reserved* names the columns the resource's dataset already has, which a
    capture may not reuse: a collection's index columns by default.
    """
    if not isinstance(text, str) or not text.strip():
        raise TemplateError("a path template must be a non-empty string")
    text = text.strip()
    if len(text) > MAX_TEMPLATE_CHARS:
        raise TemplateError("a path template is limited to 512 characters")
    if "\\" in text or "\x00" in text:
        raise TemplateError("a path template uses / between folders, never a backslash")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise TemplateError("a path template is relative to the source's root")
    segments = text.split("/")
    if len(segments) > MAX_SEGMENTS:
        raise TemplateError("a path template is limited to 32 folders")

    captures: list[Capture] = []
    seen: set[str] = set()
    pattern_parts: list[str] = []
    literal_prefix: list[str] = []
    prefix_open = True

    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment in ("", ".", ".."):
            raise TemplateError(f"{text!r} has an empty, '.' or '..' folder")
        if segment == "**":
            if last:
                raise TemplateError("'**' spans folders; the last part must name the files")
            pattern_parts.append(r"(?:[^/]+/)*")
            prefix_open = False
            continue
        if "**" in segment:
            raise TemplateError("'**' must be a folder of its own")

        regex = []
        literal = True
        position = 0
        for token in _TOKEN_RE.finditer(segment):
            if token.start() != position:
                raise TemplateError(f"{segment!r} has an unbalanced brace")
            position = token.end()
            piece = token.group(0)
            if piece == "*":
                regex.append(r"[^/]*?")
                literal = False
            elif piece.startswith("{"):
                name, spec = token.group(1), token.group(2)
                if not CAPTURE_NAME_RE.match(name or ""):
                    raise TemplateError(
                        f"capture name {name!r} must be lowercase letters, digits and _"
                    )
                if name in reserved and name not in CAPTURES_THAT_FILL_A_COLUMN:
                    raise TemplateError(f"{name!r} is a column Curio already adds; name it differently")
                if name in seen:
                    raise TemplateError(f"{name!r} is captured twice")
                seen.add(name)
                kind, fmt, capture_regex = _capture_type(spec)
                captures.append(Capture(name=name, type=kind, fmt=fmt))
                regex.append(f"(?P<{name}>{capture_regex})")
                literal = False
            else:
                if "{" in piece or "}" in piece:
                    raise TemplateError(f"{segment!r} has an unbalanced brace")
                regex.append(re.escape(piece))
        if position != len(segment):
            raise TemplateError(f"{segment!r} has an unbalanced brace")
        joined = "".join(regex)
        pattern_parts.append(joined + ("" if last else "/"))
        if prefix_open and literal and not last:
            literal_prefix.append(segment + "/")
        else:
            prefix_open = False

    return Template(
        source=text,
        regex=re.compile("^" + "".join(pattern_parts) + "$"),
        captures=tuple(captures),
        literal_prefix="".join(literal_prefix),
    )
