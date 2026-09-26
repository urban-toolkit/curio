"""The ``lake.<publisher>.<portal>@<major>`` coordinate.

Mirrors ``datasets/infrastructure/storage.py::DatasetId`` deliberately: the
two catalogs' ids should be read the same way, and a reader who knows one
knows the other.

Two differences, both on purpose:

- the ``lake.`` prefix is MANDATORY, the way ``agent.`` is for agent ids. It
  makes a source directory self-describing, and it makes a lake directory
  impossible to mistake for a dataset directory if the two roots are ever
  misconfigured onto each other;
- the provider type is NOT in the id. ``lake.socrata.cityofchicago`` bakes a
  fact that lives in ``provider.type`` into an immutable coordinate, and it is
  wrong the day a portal migrates from Socrata to CKAN - which happens. Ids
  name WHO publishes the portal, not what software it runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEG = r"[a-z][a-z0-9-]{0,62}"
# lake. + 2..5 further segments, i.e. 3..6 in total.
_SOURCE_ID_PATTERN = rf"lake\.{_SEG}(?:\.{_SEG}){{1,4}}"

SOURCE_ID_RE = re.compile(rf"^{_SOURCE_ID_PATTERN}$")
SOURCE_DIR_RE = re.compile(rf"^{_SOURCE_ID_PATTERN}@(?:0|[1-9][0-9]{{0,3}})$")


class SourceIdError(ValueError):
    """The string is not a valid data lake source id or directory name."""


@dataclass(frozen=True)
class SourceId:
    source_id: str
    major: int

    @classmethod
    def parse_dir(cls, dir_name: str) -> "SourceId":
        if not isinstance(dir_name, str) or not SOURCE_DIR_RE.match(dir_name):
            raise SourceIdError(
                f"{dir_name!r} is not a valid source directory name "
                "(expected '<lake.publisher.portal>@<major>')"
            )
        source_id, _, major = dir_name.rpartition("@")
        return cls(source_id=source_id, major=int(major))

    @property
    def dir_name(self) -> str:
        return f"{self.source_id}@{self.major}"
