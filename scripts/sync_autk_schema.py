#!/usr/bin/env python3
"""Vendor the Autark grammar's JSON Schema from its npm release, or from the
autk-grammar tarball Curio vendors until a change of it is released.

``@urban-toolkit/autk-grammar`` ships the schema it generates from its own
TypeScript types as ``build/autk-grammar-schema.json``. Curio validates Autark
documents against a byte-for-byte copy of that file, kept beside a record of
where it came from, so the grammar is defined once, upstream.

    python scripts/sync_autk_schema.py --version 0.3.0   # vendor a release
    python scripts/sync_autk_schema.py --from PATH --version 0.3.0
                                                         # vendor a local build
                                                         # of that version
    python scripts/sync_autk_schema.py --tarball PATH    # vendor the packed
                                                         # tarball the frontend
                                                         # installs, in the
                                                         # repository
    python scripts/sync_autk_schema.py --check           # compare with the
                                                         # recorded release, or
                                                         # the recorded tarball;
                                                         # exit 1 on a difference

A tarball's record names the tarball by its repository path, and the version
its package.json gives, so ``--check`` compares the copy with that tarball and
never asks npm, which has no such version.

``test_autk_schema_vendored`` checks the copy against the record offline; the
scheduled ``autk-schema`` workflow runs ``--check``.
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
MANIFEST = "package/package.json"
SCHEMA = REPO_ROOT / "utk_curio/backend/app/agents/schemas/autk-grammar.v1.json"
RECORD = SCHEMA.with_name("autk-grammar.v1.source.json")
#: The record's source for a copy taken from a tarball in the repository.
TARBALL_SOURCE = "vendored tarball"


def tarball_url(version: str) -> str:
    return f"https://registry.npmjs.org/{PACKAGE}/-/autk-grammar-{version}.tgz"


def _member(tar: tarfile.TarFile, name: str, what: str) -> bytes:
    """The file *name* of *tar*, which holds *what*; a missing one stops the script."""
    try:
        member = tar.extractfile(name)
    except KeyError:
        member = None
    if member is None:
        raise SystemExit(f"{what} does not ship {name}")
    return member.read()


def fetch_release(version: str) -> bytes:
    """The schema file inside the release tarball, as published."""
    try:
        with urllib.request.urlopen(tarball_url(version), timeout=60) as response:
            archive = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{PACKAGE}@{version} could not be fetched from npm: HTTP {exc.code}")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        return _member(tar, MEMBER, f"{PACKAGE}@{version}")


def read_tarball(path: Path) -> tuple[bytes, str]:
    """The schema file inside the packed autk-grammar tarball at *path*, and
    the version its package.json gives."""
    with tarfile.open(path, mode="r:gz") as tar:
        manifest = json.loads(_member(tar, MANIFEST, str(path)))
        if manifest.get("name") != PACKAGE:
            raise SystemExit(f"{path} is {manifest.get('name')!r}, not {PACKAGE}")
        return _member(tar, MEMBER, str(path)), str(manifest.get("version"))


def repository_path(path: Path) -> str:
    """*path*, a file in the repository, by its path there; one outside it
    stops the script, since ``--check`` reads the tarball from a checkout."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        raise SystemExit(f"{path} is not in the repository; put the tarball the frontend installs "
                         f"there first (utk_curio/frontend/urban-workflows/vendor/autark/)")


def record_for(data: bytes, version: str, source: str, tarball: str | None = None) -> dict:
    schema = json.loads(data)
    record = {"package": PACKAGE, "version": version, "source": source}
    if tarball is not None:
        record["tarball"] = tarball
    record.update({"id": schema.get("$id"), "sha256": hashlib.sha256(data).hexdigest()})
    return record


def write(data: bytes, version: str, source: str, tarball: str | None = None) -> None:
    SCHEMA.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA.write_bytes(data)
    RECORD.write_text(json.dumps(record_for(data, version, source, tarball), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SCHEMA.relative_to(REPO_ROOT)} from {tarball or source} ({PACKAGE}@{version})")


def check() -> int:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    tarball = record.get("tarball")
    if tarball:
        expected, version = read_tarball(REPO_ROOT / tarball)
        against = f"the vendored tarball {tarball}"
        fix = f"--tarball {tarball}"
        if version != record["version"]:
            print(f"{tarball} is {PACKAGE}@{version}, not the {record['version']} its record names; "
                  f"run: python scripts/sync_autk_schema.py {fix}")
            return 1
    else:
        expected = fetch_release(record["version"])
        against = f"{PACKAGE}@{record['version']} on npm"
        fix = f"--version {record['version']}"
    if hashlib.sha256(expected).hexdigest() != hashlib.sha256(SCHEMA.read_bytes()).hexdigest():
        print(f"{SCHEMA.relative_to(REPO_ROOT)} differs from {against}; "
              f"run: python scripts/sync_autk_schema.py {fix}")
        return 1
    print(f"{SCHEMA.relative_to(REPO_ROOT)} matches {against}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="the autk-grammar release to vendor")
    parser.add_argument("--from", dest="source", type=Path,
                        help="a locally built autk-grammar-schema.json of that version")
    parser.add_argument("--tarball", type=Path,
                        help="the packed autk-grammar tarball the frontend installs, in the repository; "
                             "its package.json gives the version")
    parser.add_argument("--check", action="store_true",
                        help="compare with the recorded release or tarball; write nothing")
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if args.tarball:
        if args.version or args.source:
            parser.error("--tarball gives its own version; name it alone")
        tarball = repository_path(args.tarball)
        data, version = read_tarball(args.tarball)
        write(data, version, TARBALL_SOURCE, tarball)
        return 0
    if not args.version:
        parser.error("--version is required")
    if args.source:
        write(args.source.read_bytes(), args.version, "local build")
    else:
        write(fetch_release(args.version), args.version, "npm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
