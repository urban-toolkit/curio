#!/usr/bin/env python3
"""Vendor the Autark grammar's JSON Schema from its npm release.

``@urban-toolkit/autk-grammar`` ships the schema it generates from its own
TypeScript types as ``build/autk-grammar-schema.json``. Curio validates Autark
documents against a byte-for-byte copy of that file, kept beside a record of
where it came from, so the grammar is defined once, upstream.

    python scripts/sync_autk_schema.py --version 0.3.0   # vendor a release
    python scripts/sync_autk_schema.py --from PATH --version 0.3.0
                                                         # vendor a local build
                                                         # of that version
    python scripts/sync_autk_schema.py --check           # re-fetch the recorded
                                                         # release; exit 1 on a
                                                         # difference

``test_autk_schema_vendored`` checks the copy against the record offline; the
scheduled ``autk-schema`` workflow runs ``--check`` against the registry.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "@urban-toolkit/autk-grammar"
MEMBER = "package/build/autk-grammar-schema.json"
SCHEMA = REPO_ROOT / "utk_curio/backend/app/agents/schemas/autk-grammar.v1.json"
RECORD = SCHEMA.with_name("autk-grammar.v1.source.json")


def tarball_url(version: str) -> str:
    return f"https://registry.npmjs.org/{PACKAGE}/-/autk-grammar-{version}.tgz"


def fetch_release(version: str) -> bytes:
    """The schema file inside the release tarball, as published."""
    try:
        with urllib.request.urlopen(tarball_url(version), timeout=60) as response:
            archive = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{PACKAGE}@{version} could not be fetched from npm: HTTP {exc.code}")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = tar.extractfile(MEMBER)
        if member is None:
            raise SystemExit(f"{PACKAGE}@{version} does not ship {MEMBER}")
        return member.read()


def record_for(data: bytes, version: str, source: str) -> dict:
    schema = json.loads(data)
    return {
        "package": PACKAGE,
        "version": version,
        "source": source,
        "id": schema.get("$id"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def write(data: bytes, version: str, source: str) -> None:
    SCHEMA.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA.write_bytes(data)
    RECORD.write_text(json.dumps(record_for(data, version, source), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SCHEMA.relative_to(REPO_ROOT)} from {source} ({PACKAGE}@{version})")


def check() -> int:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    published = fetch_release(record["version"])
    digest = hashlib.sha256(published).hexdigest()
    if digest != hashlib.sha256(SCHEMA.read_bytes()).hexdigest():
        print(f"{SCHEMA.relative_to(REPO_ROOT)} differs from {PACKAGE}@{record['version']} on npm; "
              f"run: python scripts/sync_autk_schema.py --version {record['version']}")
        return 1
    print(f"{SCHEMA.relative_to(REPO_ROOT)} matches {PACKAGE}@{record['version']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="the autk-grammar release to vendor")
    parser.add_argument("--from", dest="source", type=Path,
                        help="a locally built autk-grammar-schema.json of that version")
    parser.add_argument("--check", action="store_true",
                        help="re-fetch the recorded release and compare; write nothing")
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if not args.version:
        parser.error("--version is required")
    if args.source:
        write(args.source.read_bytes(), args.version, "local build")
    else:
        write(fetch_release(args.version), args.version, "npm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
