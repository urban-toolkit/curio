"""A wheel of a few hundred bytes, built in memory, for tests that install a library offline.

pip installs it from a local wheelhouse (``PIP_FIND_LINKS`` with
``PIP_NO_INDEX``), so a test that uses it never reaches an index. The wheel
carries one module holding one string, ``MESSAGE``: a node that prints it shows
that the library was installed and imported.

The e2e suite hands the bytes to the backend (``/api/testing/wheelhouse``),
which owns the pip that installs them; a backend test can write them to a
directory of its own.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass


@dataclass(frozen=True)
class WheelLibrary:
    """A library that exists only as the wheel :func:`build_wheel` makes."""

    #: The distribution name a manifest's ``dependencies.python`` declares.
    dist: str
    version: str
    #: The import name; the node imports it.
    module: str
    #: The string the module holds as ``MESSAGE``.
    message: str


def _wheel_name(dist: str) -> str:
    """The name as a wheel's file name and its dist-info folder spell it."""
    return re.sub(r"[-_.]+", "_", dist)


def wheel_file_name(library: WheelLibrary) -> str:
    return f"{_wheel_name(library.dist)}-{library.version}-py3-none-any.whl"


def _record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return f"{path},sha256={digest},{len(data)}"


def build_wheel(library: WheelLibrary) -> bytes:
    """The wheel's bytes: the module, and the dist-info pip reads and records."""
    info = f"{_wheel_name(library.dist)}-{library.version}.dist-info"
    files = {
        f"{library.module}.py": f"MESSAGE = {library.message!r}\n".encode("utf-8"),
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {library.dist}\nVersion: {library.version}\n"
        ).encode("utf-8"),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: curio-tests\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n"
        ).encode("utf-8"),
        f"{info}/top_level.txt": f"{library.module}\n".encode("utf-8"),
    }
    record = "\n".join(
        [_record_line(path, data) for path, data in files.items()] + [f"{info}/RECORD,,"]
    ) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as wheel:
        for path, data in files.items():
            wheel.writestr(path, data)
        wheel.writestr(f"{info}/RECORD", record)
    return buffer.getvalue()
