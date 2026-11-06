"""This Curio's own LLM endpoints: the file that holds them, and the
variables only the backend may hold.

Shared by the launcher (``cli/environment.py``, ``cli/services.py``), which
checks the file and keeps these variables out of every child but the backend,
and the backend (``backend/config.py``), which reads the file, and redacts the
endpoints out of provider errors (``agents/infrastructure/providers.py``).

The endpoint file (``--llm-endpoint-file``) holds one section per endpoint,
named by the label users see in API Settings ("Provided by <name>")::

    [Lab gateway]
    base_url=https://llm.example.test/v1
    api_key=<the key>
    models=model-a,model-b

    [Anthropic]
    provider=anthropic
    api_key=<another key>
    models=claude-haiku-4-5

``api_key`` and ``models`` are required. ``base_url`` is optional (empty or
absent is the provider's own endpoint), and so is ``provider``
(``openai_compatible``, ``anthropic`` or ``gemini``; ``openai_compatible`` when
absent). The first section's first model is Curio's default, and what guests
answer with. Signed-in users can pick any model of any section instead.

No URL or key is ever put in an error message, a log line or the environment:
only the file's path travels, in :data:`ENDPOINT_FILE_VARIABLE`, to the
backend alone.
"""

from __future__ import annotations

import configparser
import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlsplit

#: The path of the endpoint file, as the launcher hands it to the backend.
ENDPOINT_FILE_VARIABLE = "CURIO_DEFAULT_LLM_ENDPOINT_FILE"

#: The LLM settings the endpoint file replaced. Curio reads none of them: the
#: launcher refuses to start while one is set, and the backend warns of one
#: left in its ``.env`` (``app/upgrade_notices.py``).
RETIRED_VARIABLES = (
    "CURIO_DEFAULT_LLM_API_TYPE",
    "CURIO_DEFAULT_LLM_BASE_URL",
    "CURIO_DEFAULT_LLM_API_KEY",
    "CURIO_DEFAULT_LLM_MODEL",
    "CURIO_DEFAULT_LLM_MODELS",
    "GUEST_LLM_API_TYPE",
    "GUEST_LLM_BASE_URL",
    "GUEST_LLM_API_KEY",
    "GUEST_LLM_MODEL",
)

#: What only the backend may hold. The frontend's servers and build, the
#: sandbox, its zygote and every node it runs start without them, so node code
#: can neither print a key or URL that reached the launcher's environment nor
#: find the file.
BACKEND_ONLY_VARIABLES = (
    "CURIO_DEFAULT_LLM_API_KEY",
    "CURIO_DEFAULT_LLM_BASE_URL",
    "GUEST_LLM_API_KEY",
    "GUEST_LLM_BASE_URL",
    ENDPOINT_FILE_VARIABLE,
)

#: The provider kinds an endpoint may name, its default first.
PROVIDERS = ("openai_compatible", "anthropic", "gemini")
_KEYS = ("base_url", "api_key", "models", "provider")
_REDACTED = "«redacted:llm-endpoint»"


@dataclass(frozen=True)
class Endpoint:
    """One section of the endpoint file. The URL and key are left out of the
    repr, so a logged endpoint never shows them."""

    name: str
    api_type: str
    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    models: tuple[str, ...]


class EndpointFileError(ValueError):
    """The endpoint file cannot be used. The message names the file, the
    section and the line or key, never a value."""


def without_backend_only(environ: Mapping[str, str]) -> dict:
    """*environ* without :data:`BACKEND_ONLY_VARIABLES`, for a child that is
    not the backend."""
    return {name: value for name, value in environ.items() if name not in BACKEND_ONLY_VARIABLES}


def _parser() -> configparser.ConfigParser:
    # No interpolation: a key or a URL may hold "%". Only "=" separates a key
    # from its value, so a URL's ":" stays in it, and a section or key given
    # twice is refused.
    return configparser.ConfigParser(
        interpolation=None, delimiters=("=",), strict=True,
        comment_prefixes=("#", ";"), inline_comment_prefixes=None,
        empty_lines_in_values=False,
    )


def _models(text: str, section: str, where: str) -> tuple[str, ...]:
    names: list[str] = []
    for part in text.split(","):
        name = part.strip()
        if not name:
            continue
        if name in names:
            raise EndpointFileError(f"[{section}] in the LLM endpoint file {where} names the model {name!r} twice")
        names.append(name)
    if not names:
        raise EndpointFileError(f"[{section}] in the LLM endpoint file {where} names no model")
    return tuple(names)


def _endpoint(parser: configparser.ConfigParser, section: str, where: str) -> Endpoint:
    if not section.strip():
        raise EndpointFileError(f"a section of the LLM endpoint file {where} has no name")
    values = dict(parser.items(section, raw=True))
    unknown = sorted(set(values) - set(_KEYS))
    if unknown:
        raise EndpointFileError(
            f"[{section}] in the LLM endpoint file {where} has {unknown[0]!r}, which is not "
            f"one of {', '.join(_KEYS)}"
        )
    api_key = (values.get("api_key") or "").strip()
    if not api_key:
        raise EndpointFileError(f"[{section}] in the LLM endpoint file {where} has no api_key")
    if "models" not in values:
        raise EndpointFileError(f"[{section}] in the LLM endpoint file {where} has no models")
    models = _models(values["models"], section, where)
    provider = (values.get("provider") or "").strip() or PROVIDERS[0]
    if provider not in PROVIDERS:
        raise EndpointFileError(
            f"[{section}] in the LLM endpoint file {where} names the provider {provider!r}, "
            f"which is not one of {', '.join(PROVIDERS)}"
        )
    base_url = (values.get("base_url") or "").strip()
    if base_url:
        url = urlsplit(base_url)
        if url.scheme not in ("http", "https") or not url.hostname:
            raise EndpointFileError(
                f"the base_url of [{section}] in the LLM endpoint file {where} is not an "
                "http(s) URL with a host"
            )
    return Endpoint(name=section, api_type=provider, base_url=base_url.rstrip("/"),
                    api_key=api_key, models=models)


def read_endpoint_file(path: str | Path) -> tuple[Endpoint, ...]:
    """The endpoints of the file at *path*, in its order.

    Anything the file does not allow is an :class:`EndpointFileError` whose
    message names the section, or the line when the line is the problem."""
    where = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise EndpointFileError(f"the LLM endpoint file {where} does not exist") from None
    except (OSError, UnicodeDecodeError):
        raise EndpointFileError(f"the LLM endpoint file {where} cannot be read") from None
    return parse_endpoints(text, where)


def parse_endpoints(text: str, where: str) -> tuple[Endpoint, ...]:
    """The endpoints an endpoint file's *text* holds; *where* names the file
    in a refusal."""
    parser = _parser()
    try:
        parser.read_string(text, source=where)
    except configparser.MissingSectionHeaderError as exc:
        raise EndpointFileError(
            f"line {exc.lineno} of the LLM endpoint file {where} comes before any [section]"
        ) from None
    except configparser.DuplicateSectionError as exc:
        raise EndpointFileError(
            f"the LLM endpoint file {where} has the section [{exc.section}] twice"
        ) from None
    except configparser.DuplicateOptionError as exc:
        raise EndpointFileError(
            f"[{exc.section}] in the LLM endpoint file {where} gives {exc.option} twice"
        ) from None
    except configparser.ParsingError as exc:
        # Its own message quotes the line, which may be a key.
        line = exc.errors[0][0] if exc.errors else "?"
        raise EndpointFileError(
            f"line {line} of the LLM endpoint file {where} is not name=value or a [section]"
        ) from None
    except configparser.Error:
        raise EndpointFileError(f"the LLM endpoint file {where} cannot be parsed") from None
    if parser.defaults():
        raise EndpointFileError(
            f"the LLM endpoint file {where} has a [{parser.default_section}] section, which is "
            "not an endpoint"
        )
    sections = parser.sections()
    if not sections:
        raise EndpointFileError(f"the LLM endpoint file {where} names no endpoint")
    return tuple(_endpoint(parser, section, where) for section in sections)


def offered_models(endpoints: Iterable[Endpoint]) -> str:
    """The endpoints and their models, as a refusal names them."""
    return "; ".join(f"{endpoint.name}: {', '.join(endpoint.models)}" for endpoint in endpoints) or "none"


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _endpoint_values(base_url: str) -> list[str]:
    """The ways an error can spell *base_url*: the URL itself, with and
    without its trailing slash, its host and port, and its host. A loopback
    host alone names no machine, and other local servers share it, so it
    stays."""
    text = (base_url or "").strip()
    if not text:
        return []
    parsed = urlsplit(text if "//" in text else f"//{text}")
    host = parsed.hostname or ""
    found = {text, text.rstrip("/"), parsed.netloc, "" if _is_loopback(host) else host}
    return sorted((value for value in found if value), key=len, reverse=True)


def redact_endpoints(text: str, base_urls: Iterable[str]) -> str:
    """*text* with each of *base_urls* taken out, whole or as its host.

    A host is matched only where it stands alone (not inside a longer host
    name or word), so a short one does not mangle ordinary text."""
    out = text
    for base_url in base_urls:
        for value in _endpoint_values(base_url):
            pattern = r"(?<![\w.-])" + re.escape(value) + r"(?![\w-])"
            out = re.sub(pattern, lambda _match: _REDACTED, out, flags=re.IGNORECASE)
    return out
