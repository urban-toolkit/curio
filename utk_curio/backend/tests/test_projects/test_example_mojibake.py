"""No shipped example holds text that was read in the wrong encoding.

UTF-8 text read back as Windows-1252 (cp1252) turns each character that is not
ASCII into two to four others, one per byte. Example 04's map chart was titled
"Spatial Map", then U+00E2 U+20AC U+201C, then "Select Area to Filter": its en
dash's three bytes read as cp1252. The rework of the example set on 2026-05-08
wrote that, and wrote examples 06 and 08's "Niteroi" with its o acute as
U+00C3 U+00B3; those two were set right the next day, 04's title was not.

The check reads every dataflow, walkthrough, prompt fixture, skill and agent
under ``docs/examples`` (not its data, nor the frames): every string of a JSON
file, keys included, with a string that holds a JSON document (a chart's spec
in a node's content) read as that document's strings; and every line of a
Markdown file. It looks for the misreading itself, never for text that is not
ASCII: a character cp1252 reads a UTF-8 lead byte as (U+00C2 to U+00F4)
followed by the characters it reads that character's other bytes as, or
U+00E2 U+20AC, the start of a punctuation mark whose last byte cp1252 has no
character for. "Niteroi" written with its o acute, as examples 36 and 37 write
it, is fine.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.projects.shipped import examples_dir

#: Files whose text is JSON: dataflows, prompt fixtures, manifests and the
#: notebook the tours import.
JSON_SUFFIXES = (".json", ".ipynb")
#: Files whose text is read as written: walkthroughs, skills, prompts.
TEXT_SUFFIXES = (".md",)
#: Folders under docs/examples that hold data and frames, not text of ours.
LEFT_OUT = frozenset({"data", "expected_outputs"})
#: Fewer files than this means the scan read the wrong folder.
SOME_FILES = 100
#: Files of each kind the scan must read.
SOME_OF_EACH_KIND = {
    "04-vega-lite-multi-flow-dashboard.json",
    "04-vega-lite-multi-flow-dashboard.md",
    "dataflows/test_notebook.ipynb",
    "prompts/04-vega-lite-multi-flow-dashboard.prompt.json",
    "skills/street-trees/SKILL.md",
    "agents/agent.you.tree-counter@1/manifest.json",
}
#: Example 04's map chart title, inside the spec its node holds.
EXAMPLE_04_CHART_TITLE = "dataflow.nodes[3ad91d4c-3f0f-4db6-98a0-83fcbc564598].content > hconcat[0].title"

#: The character cp1252 reads each byte from 0x80 to 0xBF as, the bytes that
#: carry on a character in UTF-8, mapped back to its byte. cp1252 has no
#: character for five of them, which Windows reads as the control character of
#: the same number.
_CONTINUATION = {
    (bytes([byte]).decode("cp1252", errors="ignore") or chr(byte)): byte
    for byte in range(0x80, 0xC0)
}
#: U+00E2 U+20AC: the first two bytes of every character from U+2000 to
#: U+203F (dashes, quotation marks, the ellipsis), read as cp1252.
_PUNCTUATION_START = "\xe2\N{EURO SIGN}"


def _bytes_after(lead: str) -> int:
    """How many bytes follow the UTF-8 lead byte cp1252 reads as *lead*."""
    code = ord(lead)
    if 0xC2 <= code <= 0xDF:
        return 1
    if 0xE0 <= code <= 0xEF:
        return 2
    if 0xF0 <= code <= 0xF4:
        return 3
    return 0


def misread(text: str) -> list[tuple[int, str, str | None]]:
    """Each place in *text* that holds a UTF-8 character's bytes read as cp1252:
    where it starts, what it reads, and the character it was (None for a
    punctuation mark whose last byte was lost)."""
    found = []
    for at, lead in enumerate(text):
        count = _bytes_after(lead)
        run = text[at + 1:at + 1 + count]
        if count and len(run) == count and all(char in _CONTINUATION for char in run):
            try:
                meant = bytes([ord(lead), *(_CONTINUATION[char] for char in run)]).decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                found.append((at, lead + run, meant))
                continue
        if text.startswith(_PUNCTUATION_START, at):
            found.append((at, _PUNCTUATION_START, None))
    return found


def _child(where: str, key: str) -> str:
    if not where:
        return key
    return f"{where} {key}" if where.endswith(">") else f"{where}.{key}"


def _strings(value, where: str = ""):
    """(where, text) for every string in *value*, keys included. A string that
    holds a JSON document gives that document's strings instead of its own
    text, so a spec's escapes are read as the spec reads them. A list item with
    an ``id`` is named by it."""
    if isinstance(value, str):
        if value.lstrip()[:1] in ("{", "["):
            try:
                inner = json.loads(value)
            except ValueError:
                pass
            else:
                if isinstance(inner, (dict, list)):
                    yield from _strings(inner, f"{where} >")
                    return
        yield where, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield f"{_child(where, key)} (its key)", key
            yield from _strings(item, _child(where, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            name = item.get("id") if isinstance(item, dict) else None
            yield from _strings(item, f"{where}[{name if isinstance(name, str) else index}]")


def _texts(path: Path):
    """(where, text) for the text *path* holds."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix in TEXT_SUFFIXES:
        for number, line in enumerate(raw.splitlines(), start=1):
            yield f"line {number}", line
    else:
        yield from _strings(json.loads(raw))


def _files() -> list[Path]:
    root = examples_dir()
    return sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path.suffix in JSON_SUFFIXES + TEXT_SUFFIXES
        and not LEFT_OUT & set(path.relative_to(root).parts)
    )


FILES = _files()


def test_no_shipped_example_holds_text_read_in_the_wrong_encoding():
    found = []
    for path in FILES:
        for where, text in _texts(path):
            for at, read, meant in misread(text):
                was = f"the bytes of {meant!r}" if meant else "the start of a punctuation mark"
                excerpt = text[max(0, at - 30):at + len(read) + 30]
                found.append(f"{path.relative_to(examples_dir()).as_posix()} {where}: {read!r} "
                             f"in {excerpt!r} is {was}, read as cp1252")
    assert found == [], (
        "this text was saved as UTF-8 and read back as cp1252; write each character as it was:\n"
        + "\n".join(found)
    )


def test_the_check_reads_every_kind_of_file_and_the_specs_inside_the_nodes():
    names = {path.relative_to(examples_dir()).as_posix() for path in FILES}
    assert len(FILES) >= SOME_FILES, f"only {len(FILES)} files read under {examples_dir()}"
    assert SOME_OF_EACH_KIND <= names, f"not read: {sorted(SOME_OF_EACH_KIND - names)}"
    read = dict(_texts(examples_dir() / "04-vega-lite-multi-flow-dashboard.json"))
    assert EXAMPLE_04_CHART_TITLE in read, (
        f"the scan did not read example 04's chart title inside its spec; it read {sorted(read)[:20]}"
    )
    assert read[EXAMPLE_04_CHART_TITLE].startswith("Spatial Map")


@pytest.mark.parametrize("read, meant", [
    # an en dash, as example 04's title held it
    ("\xe2\N{EURO SIGN}\N{LEFT DOUBLE QUOTATION MARK}", "\N{EN DASH}"),
    # an em dash
    ("\xe2\N{EURO SIGN}\N{RIGHT DOUBLE QUOTATION MARK}", "\N{EM DASH}"),
    # a right single quotation mark
    ("\xe2\N{EURO SIGN}\N{TRADE MARK SIGN}", "\N{RIGHT SINGLE QUOTATION MARK}"),
    # a right double quotation mark, whose last byte cp1252 has no character for
    ("\xe2\N{EURO SIGN}\x9d", "\N{RIGHT DOUBLE QUOTATION MARK}"),
    # e acute
    ("\xc3\xa9", "\xe9"),
    # o acute, as 06's and 08's "Niteroi" held it
    ("\xc3\xb3", "\xf3"),
    # a degree sign, as 08's held it
    ("\xc2\xb0", "\xb0"),
    # a superscript two, as 06's held it
    ("\xc2\xb2", "\xb2"),
    # a multiplication sign, as 06's held it
    ("\xc3\N{EM DASH}", "\xd7"),
    # a minus sign, as 06's held it
    ("\xe2\N{MODIFIER LETTER CIRCUMFLEX ACCENT}\N{RIGHT SINGLE QUOTATION MARK}", "\N{MINUS SIGN}"),
    # a character of four bytes
    ("\xf0\N{LATIN CAPITAL LETTER Y WITH DIAERESIS}\N{SMALL TILDE}\N{EURO SIGN}", "\U0001f600"),
])
def test_the_check_finds_each_misread_character(read, meant):
    assert misread(f"before {read} after") == [(7, read, meant)]


def test_the_check_finds_a_punctuation_mark_whose_last_byte_was_lost():
    assert misread("Spatial Map \xe2\N{EURO SIGN} Select") == [(12, "\xe2\N{EURO SIGN}", None)]


@pytest.mark.parametrize("text", [
    "Niter\xf3i",  # examples 36 and 37
    "Niter\xf3i\N{RIGHT SINGLE QUOTATION MARK}s parks",  # those two characters' bytes are no character
    "S\xe3o Paulo",
    "S\xc3O PAULO",
    "caf\xe9",
    "na\xefve",
    "\xe9t\xe9",
    "Bogot\xe1\N{RIGHT SINGLE QUOTATION MARK}s",
    "\xc0 la carte",
    "\xab quoted \xbb",
    "15 \xb0C",
    "40 m\xb2",
    "3 \xd7 4",
    "2001\N{EN DASH}2024",
    "a \N{EM DASH} b",
    "\xc3",
])
def test_the_check_leaves_text_written_right_alone(text):
    assert misread(text) == []
