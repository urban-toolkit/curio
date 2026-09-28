"""What would leave the install, and the act of agreeing to send it (dev/122).

Two things live here, and the second is the reason the first exists.

**The statement** is everything a person needs in order to decide: how many
rows, how many bytes, which fixtures, which licences, and the destination
*host* — never the URL with its key, never the key. It also says the thing that
carries the licensing argument: a row carries dataset **identifiers** and never
dataset content, so the third-party licences of the datasets an example names
(*Open Data*, *Project Sidewalk API terms*, *Copernicus licence*, *Research
use*) are not implicated by what is sent. The prompts, the expected graphs and
the plan targets are repo-authored.

**The consent record** is the audit record dev/87 requires before an export is
served: *"Protected-content reveal and every export append an audit record
(who, what, when) before the content is served."* It is written and flushed
before the first byte moves, so a crash between the two leaves a record that
reads "consented, never sent" rather than a silent upload.

Pure: values in, values out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping
from urllib.parse import urlparse

#: The sentence the statement always carries, because it is the licensing
#: argument and it must not be paraphrased away.
IDENTIFIERS_ONLY_NOTE = (
    "Each row carries the prompt, the expected graph shape and the plan text — "
    "all authored in this repository — plus dataset and package IDENTIFIERS. "
    "No dataset row, column, geometry or file is included."
)


class ConsentRefused(Exception):
    """The upload was not consented to, or was consented to for something else."""


@dataclass(frozen=True)
class ConsentStatement:
    """What the panel shows, and what the record then pins."""

    destination_host: str
    rows: int
    bytes_len: int
    rows_digest: str
    fixture_ids: tuple = ()
    licences: tuple = ()          # (fixtureId, licence) pairs
    excluded: tuple = ()          # (fixtureId, reason) pairs
    note: str = IDENTIFIERS_ONLY_NOTE

    def as_dict(self) -> dict:
        return {
            "destinationHost": self.destination_host,
            "rows": self.rows,
            "bytes": self.bytes_len,
            "rowsDigest": self.rows_digest,
            "fixtureIds": list(self.fixture_ids),
            "licences": [
                {"fixtureId": fixture_id, "licence": licence}
                for fixture_id, licence in self.licences
            ],
            "excluded": [
                {"fixtureId": fixture_id, "reason": reason}
                for fixture_id, reason in self.excluded
            ],
            "note": self.note,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        """The one line above the consent control."""
        kilobytes = max(1, round(self.bytes_len / 1024))
        return (
            f"Sends {self.rows} row{'s' if self.rows != 1 else ''} "
            f"({kilobytes} KB) to {self.destination_host or 'the configured endpoint'}."
        )


def host_of(base_url: str, api_type: str = "") -> str:
    """The destination as a host, for showing a person.

    A base URL can carry a key in a query string on some deployments, and the
    panel has no business rendering one, so only the network location travels.
    An endpoint with no base URL is the provider's own default, named by kind.
    """
    text = (base_url or "").strip()
    if text:
        parsed = urlparse(text if "//" in text else f"//{text}")
        if parsed.netloc:
            return parsed.netloc
    kind = (api_type or "").strip()
    return f"the default {kind} endpoint" if kind else ""


def statement_for(
    training_set,
    *,
    base_url: str,
    api_type: str = "",
    licences: Mapping | None = None,
) -> ConsentStatement:
    """Describe *training_set* as the thing a person is being asked to send."""
    licence_map = dict(licences or {})
    return ConsentStatement(
        destination_host=host_of(base_url, api_type),
        rows=len(training_set.rows),
        bytes_len=training_set.bytes_len,
        rows_digest=training_set.sha256,
        fixture_ids=tuple(training_set.fixture_ids),
        licences=tuple(
            (fixture_id, str(licence_map.get(fixture_id) or "repository (MIT)"))
            for fixture_id in training_set.fixture_ids
        ),
        excluded=tuple(
            (excluded.fixture_id, excluded.reason) for excluded in training_set.excluded
        ),
    )


@dataclass(frozen=True)
class ConsentRecord:
    """The audit record, written before anything is sent."""

    granted_at: str
    granted_by: str
    rows_digest: str
    destination_host: str
    rows: int
    bytes_len: int
    statement: str

    def as_dict(self) -> dict:
        return {
            "grantedAt": self.granted_at,
            "grantedBy": self.granted_by,
            "rowsDigest": self.rows_digest,
            "destinationHost": self.destination_host,
            "rows": self.rows,
            "bytes": self.bytes_len,
            "statement": self.statement,
        }


def grant(
    statement: ConsentStatement,
    *,
    user_key: str,
    echoed_digest: str,
    confirmed: bool,
    now: str | None = None,
) -> ConsentRecord:
    """Turn a confirmation into the record, or refuse.

    The client must echo the digest it was shown. That is not ceremony: the set
    is rebuilt from the fixtures on every request, so a fixture approved,
    edited or re-split between the preview and the click changes what would be
    sent — and consent given for one set must not carry to another.
    """
    if not confirmed:
        raise ConsentRefused(
            "nothing is sent without an explicit confirmation of what is being sent"
        )
    if not (echoed_digest or "").strip():
        raise ConsentRefused(
            "the confirmation must echo the digest of the set that was shown"
        )
    if echoed_digest != statement.rows_digest:
        raise ConsentRefused(
            "the training set changed since it was shown (a fixture was approved, "
            "edited or re-split): review the new set and confirm that one"
        )
    return ConsentRecord(
        granted_at=now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        granted_by=str(user_key),
        rows_digest=statement.rows_digest,
        destination_host=statement.destination_host,
        rows=statement.rows,
        bytes_len=statement.bytes_len,
        statement=statement.sentence() + " " + statement.note,
    )
