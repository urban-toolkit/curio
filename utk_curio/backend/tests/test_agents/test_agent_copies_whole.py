"""A copy of an agent lands in an account's store whole.

Curio writes a copy of an agent it ships into an account's store when it adds
the account's default agents, on a first visit, and when it rewrites a stale
copy after an update changes a prompt the agent ships. A request of the
account can read the store at any moment of that write. On 11-22 a listing of
the account's agents (``GET /api/agents/llm``, run 45049891312) read a
manifest the seeding had opened and not yet written, and answered 500 with
"invalid JSON: Expecting value". Whatever moment a request reads at, it must
find no copy or one whole copy, the old one or the new one, never a part.

Each file written into the store hands the moment it is opened to a reader,
as a request on another thread could read it then, and so does each rename
there. No thread and no wait: the writes themselves make the moments.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from utk_curio.backend.app.agents.application import catalog, lifecycle
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.projects.services import _user_dir_key

#: What a request finds where the store holds no copy of the agent.
NO_COPY = "no copy"
#: The names of the whole copies a request may find.
SHIPPED = "the shipped copy"
STALE = "the stale copy"
#: The instruction an earlier Curio shipped, which a stale copy holds.
EARLIER_INSTRUCTION = "The instruction an earlier Curio shipped.\n"
#: The open modes that write.
WRITES = set("wax+")


def _files(manifest: dict, prompts: dict[str, str]) -> dict[str, object]:
    """A copy as a reader compares it: its manifest, parsed, and the text of
    each prompt by its path in the copy's folder."""
    return {"manifest.json": manifest, **prompts}


def _held(folder: Path) -> dict[str, object]:
    """The copy in *folder*, as :func:`_files` gives one. Raises
    ``ValueError`` when its manifest does not parse."""
    held: dict[str, object] = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name = path.relative_to(folder).as_posix()
        text = path.read_text(encoding="utf-8")
        held[name] = json.loads(text) if name == "manifest.json" else text
    return held


def _differences(held: dict[str, object], copy: dict[str, object]) -> list[str]:
    """How the files a folder holds differ from *copy*'s."""
    found: list[str] = []
    for name in sorted(set(held) | set(copy)):
        if name not in held:
            found.append(f"{name} is missing")
        elif name not in copy:
            found.append(f"{name} is not the copy's")
        elif held[name] != copy[name]:
            found.append(f"{name} holds {len(str(held[name]))} of its {len(str(copy[name]))} characters")
    return found


def _read(key: str, coord: str, copies: dict[str, dict[str, object]]) -> str:
    """What a request that reads *coord* in *key*'s store finds now: no copy,
    the name of the one of *copies* it finds, or what is wrong."""
    try:
        # The frames of 11-22's 500: the definition's resolution, which loads
        # the store's copy first.
        storage.load_installed_agent_definition(key, coord)
        catalog._resolve_definition(key, coord)
    except Exception as exc:  # noqa: BLE001 - what the request answers with a 500
        return f"{type(exc).__name__}: {exc}"
    folder = storage.agent_definition_dir(key, coord)
    if not folder.exists():
        return NO_COPY
    try:
        held = _held(folder)
    except (OSError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"
    for name, copy in copies.items():
        if held == copy:
            return name
    name, copy = min(copies.items(), key=lambda item: len(_differences(held, item[1])))
    return f"a part of {name}: " + "; ".join(_differences(held, copy))


class _Reads:
    """What a request finds of each agent at each moment a write into *key*'s
    store opens a file or renames a folder there, while *patch* (a
    ``monkeypatch.context()``) holds: ``moments``, each ``(what, {coord:
    found})``. Each agent's ``copies`` are the whole ones it may be."""

    def __init__(self, patch, key: str, copies: dict[str, dict[str, dict[str, object]]]):
        self.key, self.copies = key, copies
        self.store = storage.user_agents_dir(key).resolve()
        self.moments: list[tuple[str, dict[str, str]]] = []
        self._reading = threading.local()
        real_open, real_replace = Path.open, os.replace

        def open_(path, mode="r", *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            if set(mode) & WRITES:
                # The file is there now, empty, as a request would find it.
                self._look(lambda: f"{self._name(path)} opened", path)
            return handle

        def replace(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            self._look(lambda: f"{self._name(src)} renamed to {self._name(dst)}", src, dst)

        patch.setattr(Path, "open", open_)
        patch.setattr(os, "replace", replace)

    def _in_store(self, path) -> bool:
        return Path(path).resolve().is_relative_to(self.store)

    def _name(self, path) -> str:
        return Path(path).resolve().relative_to(self.store).as_posix() if self._in_store(path) else str(path)

    def _look(self, what, *paths) -> None:
        if getattr(self._reading, "now", False) or not any(self._in_store(p) for p in paths):
            return
        self._reading.now = True
        try:
            self.moments.append((what(), self.now()))
        finally:
            self._reading.now = False

    def now(self) -> dict[str, str]:
        """What a request finds of each agent now."""
        return {coord: _read(self.key, coord, copies) for coord, copies in self.copies.items()}

    def wrong(self, whole: set[str]) -> list[str]:
        """Each read of a moment that found neither no copy nor one of *whole*."""
        return [
            f"when {what}, {coord} read: {found}"
            for what, reads in self.moments for coord, found in reads.items() if found not in whole
        ]

    def manifests_opened(self) -> list[str]:
        return [what for what, _ in self.moments if what.endswith("/manifest.json opened")]


def _shipped(coord: str) -> dict:
    """The bundle Curio writes as *coord*'s copy."""
    bundle = catalog.builtin_definition_bundle(coord)
    assert bundle is not None, f"{coord} is not an agent Curio ships"
    return bundle


def _hidden(key: str) -> list[str]:
    """The hidden names in *key*'s agent store: a write's staging folders,
    which none may leave behind."""
    store = storage.user_agents_dir(key)
    return sorted(p.name for p in store.iterdir() if p.name.startswith(".")) if store.is_dir() else []


def _report(wrong: list[str]) -> str:
    return f"{len(wrong)} reads found a part of a copy:\n" + "\n".join(wrong[:12])


def test_a_request_while_the_default_agents_are_added_never_reads_a_part_of_a_copy(
    new_account_and_token, monkeypatch,
):
    """A new account's first visit, the seeding of run 45049891312: Curio adds
    the account's default agents, a copy of each in its store, while the page
    lists them."""
    user, _token = new_account_and_token
    key = _user_dir_key(user)
    coords = lifecycle.default_agent_coords()
    assert coords, "Curio ships no default agent, so this proves nothing"
    copies = {}
    for coord in coords:
        bundle = _shipped(coord)
        copies[coord] = {SHIPPED: _files(bundle["manifest"], bundle["prompts"])}

    with monkeypatch.context() as patch:
        reads = _Reads(patch, key, copies)
        assert reads.now() == {coord: NO_COPY for coord in coords}
        added = lifecycle.seed_default_agents(key, user)

    assert sorted(added) == sorted(coords)
    assert len(reads.manifests_opened()) >= len(coords), (
        f"the seeding opened {reads.manifests_opened()}, not a manifest per agent, so no read "
        "came at the moment a manifest is written"
    )
    wrong = reads.wrong({NO_COPY, SHIPPED})
    assert not wrong, _report(wrong)
    assert reads.now() == {coord: SHIPPED for coord in coords}
    assert _hidden(key) == []


def test_a_request_while_a_stale_copy_is_rewritten_never_reads_a_part_of_a_copy(
    new_account_and_token, monkeypatch,
):
    """An update changed the instruction an agent ships, and the account's
    copy holds the earlier one: Curio rewrites it at its next install, File >
    New or Add to all projects (``_materialize_definition``), while a request
    reads it."""
    user, _token = new_account_and_token
    key = _user_dir_key(user)
    coords = lifecycle.default_agent_coords()
    assert coords, "Curio ships no default agent, so this proves nothing"
    copies = {}
    for coord in coords:
        bundle = _shipped(coord)
        instruction = bundle["manifest"]["prompts"]["instruction"]["path"]
        stale = {**bundle["prompts"], instruction: EARLIER_INSTRUCTION}
        assert stale != bundle["prompts"], f"{coord} ships the earlier instruction, so its copy is not stale"
        storage.write_definition_atomic(key, coord, bundle["manifest"], stale, replace=True)
        copies[coord] = {
            STALE: _files(bundle["manifest"], stale),
            SHIPPED: _files(bundle["manifest"], bundle["prompts"]),
        }

    with monkeypatch.context() as patch:
        reads = _Reads(patch, key, copies)
        assert reads.now() == {coord: STALE for coord in coords}
        for coord in coords:
            catalog._materialize_definition(key, coord)

    assert len(reads.manifests_opened()) >= len(coords), (
        f"the rewrite opened {reads.manifests_opened()}, not a manifest per agent, so no read "
        "came at the moment a manifest is written"
    )
    wrong = reads.wrong({NO_COPY, STALE, SHIPPED})
    assert not wrong, _report(wrong)
    assert reads.now() == {coord: SHIPPED for coord in coords}
    assert _hidden(key) == []
