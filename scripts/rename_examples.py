#!/usr/bin/env python3
"""Name every example file in lowercase words joined by dashes.

Step 16 of the plan for komar41's #914. The numbered gallery in
``docs/examples/`` was already named this way. The test dataflows in
``docs/examples/dataflows/`` were not, and examples 06 and 24 and the SCOUT
test dataflows get descriptive names. ``RENAMES`` below is the map. For each
entry the script:

- moves, with ``git mv``, the file, its prompt fixture, its walkthrough and
  every screenshot baseline named after it, so the frames CI minted keep their
  pixels: ``screenshot_<stem>_test_*`` (``test_workflows.py``) and
  ``screenshot_shipped-drop-<stem>-*`` (``test_shipped_scenario_drops_e2e.py``),
  per-GPU-kind baselines (``<name>.<kind>.png``) with them;
- renames the dataflow (``dataflow.name``) where its name was its file name or
  the map gives it a new one, and its ``provenance_id`` where that was its old
  file name;
- rewrites every reference to an old name in the tracked text files, and
  prints each line it changed;
- updates the prompt fixtures' ``source.sha256`` and the ``integrity.json`` of
  every package whose files it changed.

Usage::

    python scripts/rename_examples.py --dry-run   # print every move and changed line, write nothing
    python scripts/rename_examples.py             # do it; refuses a checkout with changes
    python scripts/rename_examples.py --check     # exit 1 while an old name is still referenced

``--repo <checkout>`` works on another checkout. A run stages the moves and
leaves the rewritten lines unstaged, for review. On a checkout already renamed
it changes nothing. After a run, also run ``scripts/generate_contracts.py
--check`` and ``scripts/validate_trill.py --all --resolve``.

An old name that is also an ordinary word or identifier (``Vega``, ``Image``,
``Scenarios``, ``NetCDF``, ``AutkMap``, ...) changes only where it names the
example: a file name, a ``dataflows/<stem>`` key, a baseline, a fixture id, an
item of a list of examples, or "<stem> dataflow". The bare word stays.
"""
from __future__ import annotations

import argparse
import difflib
import functools
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

#: ``re.compile``, once per pattern: the rules build theirs from the map on every file.
rx = functools.lru_cache(maxsize=None)(re.compile)

EXAMPLES = "docs/examples"
TESTS = "dataflows"
PROMPTS = "docs/examples/prompts"
FRAMES = "docs/examples/dataflows/expected_outputs"
THIS = "scripts/rename_examples.py"


@dataclass(frozen=True)
class Rename:
    old: str
    new: str
    #: "" for a numbered example in docs/examples/, else its subfolder there.
    folder: str = TESTS
    #: The new ``dataflow.name``. None: a name that was the old file name
    #: becomes the new file name, and any other name stays.
    name: Optional[str] = None
    #: The old ``dataflow.name``, when it was not the old file name.
    was: Optional[str] = None
    #: The old file name is also an ordinary word or identifier (a node label,
    #: a file format, a class), so only a reference that names the example
    #: changes, never the bare word.
    word: bool = False
    ext: str = ".json"

    @property
    def dataflow(self) -> bool:
        return self.ext == ".json"

    @property
    def old_name(self) -> str:
        return self.was or self.old

    @property
    def new_name(self) -> str:
        if self.name:
            return self.name
        return self.new if self.old_name == self.old else self.old_name


RENAMES = [
    Rename("06-autark-what-if-shadow-study", "06-back-bay-road-sunlight", folder="",
           name="Back Bay road sunlight when buildings change", was="Autark what-if shadow study"),
    Rename("24-scout-building-rasters", "24-scout-shadow-model-chicago-loop", folder="",
           name="SCOUT shadow model on Chicago Loop buildings", was="SCOUT building rasters"),
    Rename("AutkMap", "autk-map", word=True),
    Rename("DataPool_AutkMap", "data-pool-autk-map"),
    Rename("DataPool_Dataframe", "data-pool-dataframe"),
    Rename("DataPool_Geodataframe", "data-pool-geodataframe"),
    Rename("DataPool_Vega", "data-pool-vega"),
    Rename("DataPool_Vega_2", "data-pool-vega-2"),
    Rename("DefaultWorkflow", "default-workflow", word=True),
    Rename("FloodScenarios", "quad-cities-flood-vulnerability",
           name="Quad Cities flood depth, nature-based solutions and vulnerability"),
    Rename("Image", "image", word=True),
    Rename("ImageUrls", "image-urls", was="Simple View images"),
    Rename("Interaction_Autark", "interaction-autark"),
    Rename("Interaction_AutkMap", "interaction-autk-map"),
    Rename("Interaction_Vega", "interaction-vega"),
    Rename("Interaction_Vega_Autark", "interaction-vega-autark"),
    Rename("Interaction_Vega_Simple", "interaction-vega-simple"),
    Rename("JSComputation", "js-computation"),
    Rename("MultiInput", "multi-input", word=True),
    Rename("MultiInputDataPool", "multi-input-data-pool"),
    Rename("NetCDF", "netcdf-hourly-rain", name="Hourly rain from a NetCDF weather forecast", word=True),
    Rename("Regression", "regression", word=True),
    Rename("Scenarios", "scenarios", word=True),
    Rename("ScoutShadows", "chicago-loop-shadow-towers",
           name="Chicago Loop shadow with towers removed or edited"),
    Rename("SimpleView", "simple-view", word=True),
    Rename("Vega", "vega", word=True),
    Rename("WeatherRouting", "chicago-rain-wind-routing",
           name="Routing around rain and wind in downtown Chicago"),
    Rename("Widget", "widget", word=True),
    # Not a dataflow: the notebook the tours import. No fixture and no name.
    Rename("test_notebook", "test-notebook", word=True, ext=".ipynb"),
]

#: Longest old name first, so a name never matches inside a longer one.
BY_LENGTH = sorted(RENAMES, key=lambda e: (-len(e.old), e.old))

#: Quoted old names that are not the example, for --check: (file, text on the line, why).
NOT_EXAMPLES = [
    ("utk_curio/frontend/urban-workflows/src/providers/FlowProvider.tsx", 'workflowName: "DefaultWorkflow"',
     "the flow context's placeholder name, not the file"),
    ("utk_curio/backend/app/projects/seed.py", 'falls back to "DefaultWorkflow"',
     "the canvas's old default name, not the file"),
    ("utk_curio/backend/tests/test_projects/test_example_seed_names.py", 'falls back to "DefaultWorkflow"',
     "the canvas's old default name, not the file"),
    ("utk_curio/llm-prompts/evaluate_coherence_subtasks_prompt.md", '"name": "DefaultWorkflow"',
     "a sample payload's dataflow name"),
    ("utk_curio/llm-prompts/evaluate_coherence_subtasks_prompt.template.md", '"name": "DefaultWorkflow"',
     "a sample payload's dataflow name"),
    ("utk_curio/backend/tests/test_agents/test_routes_proposals.py", '"label": "Vega"', "the Vega-Lite node's label"),
    ("utk_curio/backend/tests/test_packages/test_available_templates.py", '"Vega"', "the Vega-Lite node's label"),
    ("utk_curio/frontend/urban-workflows/src/services/datasetCatalog/datasetCatalogTypes.ts", '"NetCDF"',
     "the file format's label"),
    ("utk_curio/frontend/urban-workflows/src/tests/components/DatasetDetailPanel.test.tsx", '"NetCDF"',
     "the file format's label"),
    ("utk_curio/frontend/urban-workflows/src/tests/pages/dataCatalogModelCards.test.tsx", '"NetCDF"',
     "the file format's label"),
    ("utk_curio/frontend/urban-workflows/src/tests/services/datasetCatalog.test.ts", '"NetCDF"',
     "the file format's label"),
    ("utk_curio/frontend/urban-workflows/src/tests/components/upMenuScenarios.test.ts", 'label="Scenarios"',
     "a menu label"),
    ("utk_curio/frontend/urban-workflows/src/tests/registry/registryRefreshOrdering.test.ts", "'Widget'",
     "a node label"),
    ("utk_curio/backend/tests/test_frontend/test_scenarios_canvas_e2e.py", '"Scenarios"',
     "the test's own dataflow, not the shipped one"),
]

#: Tracked files the rewrite never reads: data, recordings, baselines, this script.
SKIP = re.compile(
    r"^(?:docs/examples/dataflows/expected_outputs/|datasets/[^/]+/data/|packages/[^/]+/models/|vendor/"
    r"|utk_curio/backend/tests/test_discovery/fixtures/|" + re.escape(THIS) + r"$)"
    r"|(?:\.geojson|vega-schema\.json|package-lock\.json|\.js\.map)$"
)

B = r"(?<![A-Za-z0-9_])"
E = r"(?![A-Za-z0-9_])"


def _sub(pattern: "re.Pattern", new: str, text: str) -> Tuple[str, int]:
    return pattern.subn(lambda _m: new, text)


def _folder(e: Rename) -> str:
    return f"{e.folder}/" if e.folder else ""


def entry_paths(e: Rename, stem: str) -> List[str]:
    """The files that carry *e* under the file name *stem*."""
    paths = [f"{EXAMPLES}/{_folder(e)}{stem}{e.ext}"]
    if e.dataflow:
        paths.append(f"{PROMPTS}/{_folder(e)}{stem}.prompt.json")
        if not e.folder:
            paths.append(f"{EXAMPLES}/{stem}.md")
    return paths


def _exts(e: Rename) -> List[str]:
    exts = [re.escape(e.ext)]
    if e.dataflow:
        exts.append(r"\.prompt\.json")
        if not e.folder:
            exts.append(r"\.md")
    return exts


def file_name_rx(e: Rename) -> "re.Pattern":
    """*e*'s old name as the name of one of its files."""
    return rx(B + re.escape(e.old) + r"(?=(?:" + "|".join(_exts(e)) + r")(?![A-Za-z0-9]))")


def frame_target(name: str) -> Optional[str]:
    """A baseline's new file name, or None when it is not named after an old example."""
    for e in BY_LENGTH:
        for prefix in (f"screenshot_{e.old}_test_", f"screenshot_shipped-drop-{e.old}-"):
            if name.startswith(prefix):
                return prefix.replace(e.old, e.new, 1) + name[len(prefix):]
    return None


# --------------------------------------------------------------------------
# Rewriting one file
# --------------------------------------------------------------------------

LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def rule_links(text: str, path: str) -> Tuple[str, int]:
    """A Markdown link to an old file: the new file, and the new name where
    the link's text was the dataflow's old name."""
    count = 0

    def repl(m):
        nonlocal count
        title, target = m.group(1), m.group(2)
        for e in BY_LENGTH:
            ends = r"(?:^|/)" + re.escape(e.old) + r"(?:" + "|".join(_exts(e)) + r")(?:#|$)"
            if rx(ends).search(target):
                new_title = e.new_name if title.strip() == e.old_name else title
                new_target = file_name_rx(e).sub(lambda _m: e.new, target)
                count += 1
                return f"[{new_title}]({new_target})"
        return m.group(0)

    return LINK.sub(repl, text), count


def _phrase(words: str) -> str:
    return r"(?<![A-Za-z0-9])" + r"\s+".join(map(re.escape, words.split())) + r"(?![A-Za-z0-9])"


def named_in(text: str) -> List[Rename]:
    """The entries whose old file name, or the first word of whose old name, *text* holds."""
    return [e for e in BY_LENGTH if e.old in text or (e.was and e.was.split()[0] in text)]


def rule_old_names(text: str, path: str) -> Tuple[str, int]:
    """A dataflow's old name where it was not its file name (06 and 24)."""
    total = 0
    for e in named_in(text):
        if e.was and e.new_name != e.was:
            text, n = _sub(rx(_phrase(e.was)), e.new_name, text)
            total += n
    return text, total


def rule_shown_names(text: str, path: str) -> Tuple[str, int]:
    """The name the app shows for a dataflow whose name was its file name and
    becomes a new name: a project name constant, and the drop's notice."""
    total = 0
    for e in named_in(text):
        if not e.dataflow or e.old_name != e.old or e.new_name == e.new:
            continue
        for q in ('"', "'"):
            pattern = rx(r"(?<=_NAME = " + q + r")" + re.escape(e.old) + r"(?=" + q + r")")
            text, n = _sub(pattern, e.new_name, text)
            total += n
        if path.endswith(".md"):
            pattern = rx(r"(Running [^\n\"]*? in )" + re.escape(e.old) + r"( for )")
            text, n = pattern.subn(lambda m: m.group(1) + e.new_name + m.group(2), text)
            total += n
    return text, total


ID_CONTEXTS = [r"_by_id\({q}", r"fixture_id == {q}", r"\"fixtureId\": {q}", r"by_name\[{q}", r"FIXTURE = {q}"]


def rule_fixture_ids(text: str, path: str) -> Tuple[str, int]:
    """An old name that is a word, where code reads it as a fixture or file id."""
    total = 0
    for e in named_in(text):
        if not e.word or not e.dataflow:
            continue
        for q in ('"', "'"):
            for context in ID_CONTEXTS:
                pattern = rx(r"(?<=" + context.format(q=q) + r")" + re.escape(e.old) + r"(?=" + q + r")")
                text, n = _sub(pattern, e.new, text)
                total += n
    return text, total


TOKEN = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_./-]*[A-Za-z0-9_])?")
LIST_GAP = re.compile(r"[\s\"'`#*]*(?:,[\s\"'`#*]*(?:(?:and|or)\b[\s\"'`#*]*)?|(?:and|or)\b[\s\"'`#*]*)")
NUMBERED = re.compile(r"\d\d-[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
WORD_OLD = {e.old: e for e in RENAMES if e.word}
STEMS_OLD = {e.old for e in RENAMES}
STEMS_NEW = {e.new for e in RENAMES}
LOOSE_OLD = {e.old for e in RENAMES if not e.word}
LOOSE_NEW = {e.new for e in RENAMES if not e.word}
FILE_EXT = re.compile(r"\.(?:prompt\.json|json|md|ipynb)$")


WORD_AT = re.compile(r"(?<![A-Za-z0-9_./-])(?:" + "|".join(sorted(map(re.escape, WORD_OLD), key=len, reverse=True))
                     + r")(?![A-Za-z0-9_]|[./-][A-Za-z0-9_])")
EXAMPLE_NUMBER = re.compile(r"\b[Ee]xamples? $")
#: How far around an old name its list is read.
REACH = 400


def names_an_example(text: str, token: "re.Match", after: bool) -> bool:
    """Whether *token* names an example beyond doubt: an unambiguous old name
    (or, *after* the rename, new name), a numbered stem, "Example NN", a
    ``dataflows/`` key or an example's file name."""
    word = token.group(0)
    if word in LOOSE_OLD or (after and word in LOOSE_NEW) or NUMBERED.fullmatch(word):
        return True
    if re.fullmatch(r"\d\d", word) and EXAMPLE_NUMBER.search(text, max(0, token.start() - 10), token.start()):
        return True
    bare = FILE_EXT.sub("", word)
    stems = STEMS_OLD | STEMS_NEW
    if bare.startswith("dataflows/"):
        return bare[len("dataflows/"):] in stems
    return bare != word and bare.rsplit("/", 1)[-1] in stems


def listed_words(text: str, after: bool = False) -> List[Tuple[int, int, str]]:
    """Old names that are words, as items of a list that names an example:
    ``"Widget", "Scenarios", "FloodScenarios"``, "ScoutShadows and NetCDF" or
    "Example 08 and Regression". The items of a list are joined by commas,
    "and" or "or", with quotes, backticks and comment marks around them."""
    found = []
    for m in WORD_AT.finditer(text):
        start, end = max(0, m.start() - REACH), min(len(text), m.end() + REACH)
        tokens = [t for t in TOKEN.finditer(text, start, end) if t.group(0) not in ("and", "or")]
        at = next((k for k, t in enumerate(tokens) if t.start() == m.start()), None)
        if at is None:
            continue
        low = high = at
        while low > 0 and LIST_GAP.fullmatch(text, tokens[low - 1].end(), tokens[low].start()):
            low -= 1
        while high + 1 < len(tokens) and LIST_GAP.fullmatch(text, tokens[high].end(), tokens[high + 1].start()):
            high += 1
        if any(names_an_example(text, t, after) for t in tokens[low:high + 1] if t is not tokens[at]):
            found.append((m.start(), m.end(), m.group(0)))
    return found


def rule_listed_words(text: str, path: str) -> Tuple[str, int]:
    spans = listed_words(text)
    for start, end, word in sorted(spans, reverse=True):
        text = text[:start] + WORD_OLD[word].new + text[end:]
    return text, len(spans)


def called_dataflow_rx(e: Rename) -> "re.Pattern":
    return rx(r"(?<![A-Za-z0-9_./-])(?<!Compare )" + re.escape(e.old)
                      + r"(?=(?:'s)? (?:test )?(?:dataflow|example|fixture)s?\b)")


def rule_called_dataflow(text: str, path: str) -> Tuple[str, int]:
    """An old name that is a word, followed by "dataflow", "example" or "fixture"."""
    total = 0
    for e in named_in(text):
        if e.word and e.dataflow:
            text, n = _sub(called_dataflow_rx(e), e.new, text)
            total += n
    return text, total


def rule_file_names(text: str, path: str) -> Tuple[str, int]:
    total = 0
    for e in named_in(text):
        text, n = _sub(file_name_rx(e), e.new, text)
        total += n
    return text, total


def key_rx(e: Rename) -> "re.Pattern":
    return rx(r"(?<=dataflows/)" + re.escape(e.old) + E)


def frame_rxs(e: Rename) -> List["re.Pattern"]:
    return [rx(r"(?<=screenshot_)" + re.escape(e.old) + r"(?=_test_)"),
            rx(r"(?<=shipped-drop-)" + re.escape(e.old) + r"(?=-)")]


def rule_keys_and_frames(text: str, path: str) -> Tuple[str, int]:
    """``dataflows/<stem>`` keys, and baselines named in text."""
    total = 0
    for e in named_in(text):
        patterns = frame_rxs(e) + ([key_rx(e)] if e.dataflow and e.folder == TESTS else [])
        for pattern in patterns:
            text, n = _sub(pattern, e.new, text)
            total += n
    return text, total


def word_rx(e: Rename) -> "re.Pattern":
    return rx(B + re.escape(e.old) + E)


def rule_unambiguous(text: str, path: str) -> Tuple[str, int]:
    """Every other mention of an old name that is not also a word."""
    total = 0
    for e in named_in(text):
        if not e.word:
            text, n = _sub(word_rx(e), e.new, text)
            total += n
    return text, total


RULES: List[Callable[[str, str], Tuple[str, int]]] = [
    rule_links, rule_old_names, rule_shown_names, rule_fixture_ids, rule_listed_words,
    rule_called_dataflow, rule_file_names, rule_keys_and_frames, rule_unambiguous,
]

TRIGGER = re.compile("|".join(
    [re.escape(e.old) for e in BY_LENGTH] + [_phrase(e.was) for e in RENAMES if e.was]))


def rewrite(text: str, path: str) -> Tuple[str, int]:
    if not TRIGGER.search(text):
        return text, 0
    total = 0
    for rule in RULES:
        text, n = rule(text, path)
        total += n
    return text, total


def rename_dataflow(text: str, e: Rename, path: str) -> Tuple[str, int]:
    """The moved dataflow's own name and provenance id, edited in place."""
    flow = json.loads(text).get("dataflow") or {}
    count = 0
    name = flow.get("name")
    if name != e.new_name:
        if name != e.old_name:
            raise SystemExit(f"{path}: its name is {name!r}, not {e.old_name!r} as the map says")
        text, n = _set_field(text, "name", e.old_name, e.new_name, path)
        count += n
    provenance = flow.get("provenance_id")
    if provenance in (e.old, e.old_name) and provenance != e.new_name:
        text, n = _set_field(text, "provenance_id", provenance, e.new_name, path)
        count += n
    return text, count


def _set_field(text: str, key: str, old: str, new: str, path: str) -> Tuple[str, int]:
    pattern = rx(r'("' + key + r'"\s*:\s*)' + re.escape(json.dumps(old)))
    hits = pattern.findall(text)
    if len(hits) != 1:
        raise SystemExit(f"{path}: {key} {old!r} is written {len(hits)} times, not once")
    return pattern.subn(lambda m: m.group(1) + json.dumps(new), text)


# --------------------------------------------------------------------------
# The plan: moves and rewritten texts, all in memory
# --------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def tracked(repo: Path) -> List[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p.decode("utf-8") for p in out.split(b"\0") if p]


def read_text(repo: Path, path: str) -> Optional[str]:
    full = repo / path
    if full.is_symlink() or not full.is_file():
        return None
    data = full.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Plan:
    moves: List[Tuple[str, str]]
    #: Final path -> (path it is read from, old text, new text, references changed).
    texts: Dict[str, Tuple[str, str, str, int]]
    notes: List[str]


def plan(repo: Path) -> Plan:
    files = tracked(repo)
    present = set(files)
    moves: List[Tuple[str, str]] = []
    problems: List[str] = []
    dataflow_of: Dict[str, Rename] = {}
    for e in RENAMES:
        for src, dst in zip(entry_paths(e, e.old), entry_paths(e, e.new)):
            if src in present and dst in present:
                problems.append(f"both {src} and {dst} are tracked")
            elif src in present:
                moves.append((src, dst))
                if e.dataflow and src == entry_paths(e, e.old)[0]:
                    dataflow_of[src] = e
            elif dst not in present:
                problems.append(f"neither {src} nor {dst} is tracked")
    for path in files:
        if path.startswith(FRAMES + "/"):
            new_name = frame_target(path[len(FRAMES) + 1:])
            if new_name:
                dst = f"{FRAMES}/{new_name}"
                if dst in present:
                    problems.append(f"both {path} and {dst} are tracked")
                moves.append((path, dst))
    if problems:
        raise SystemExit("cannot rename:\n  " + "\n  ".join(problems))

    target = dict(moves)
    texts: Dict[str, Tuple[str, str, str, int]] = {}
    for path in files:
        if SKIP.search(path):
            continue
        old = read_text(repo, path)
        if old is None:
            continue
        new, count = old, 0
        if path in dataflow_of:
            new, count = rename_dataflow(new, dataflow_of[path], path)
        new, n = rewrite(new, path)
        count += n
        if new != old:
            texts[target.get(path, path)] = (path, old, new, count)

    notes = digests(repo, files, target, texts) + integrity(repo, files, texts) + shown_name_notes(texts)
    return Plan(moves=moves, texts=texts, notes=notes)


def shown_name_notes(texts) -> List[str]:
    """Quoted new file names of dataflows the app now shows by another name.
    The rewrite writes the file name; where code compares one with a project's
    name (a project lookup, a notice), it should be the shown name instead."""
    notes = []
    renamed = [e for e in BY_LENGTH if e.dataflow and e.old_name == e.old and e.new_name != e.new]
    for final in sorted(texts):
        src, old, new, _count = texts[final]
        lines = new.splitlines()
        for e in renamed:
            if e.old not in old:
                continue
            for m in rx(r"(?<=[\"'`])" + re.escape(e.new) + r"(?=[\"'`])").finditer(new):
                number = new.count("\n", 0, m.start()) + 1
                line = lines[number - 1]
                if re.search(r"(?i)name|text", line) and "fixtureId" not in line:
                    notes.append(f"review {final}:{number}: {e.new!r} is the file name; where it stands "
                                 f"for the project, write {e.new_name!r}")
    return notes


def _final_bytes(repo: Path, path: str, source: Dict[str, str], texts) -> bytes:
    if path in texts:
        return texts[path][2].encode("utf-8")
    return (repo / source.get(path, path)).read_bytes()


def digests(repo: Path, files: List[str], target: Dict[str, str], texts) -> List[str]:
    """Each prompt fixture's ``source.sha256`` follows its example, where this run moved or changed it."""
    notes = []
    source = {dst: src for src, dst in target.items()}
    finals = {target.get(p, p) for p in files}
    touched = set(texts) | set(source)
    for fixture in sorted(p for p in finals if p.startswith(PROMPTS + "/") and p.endswith(".prompt.json")):
        text = texts[fixture][2] if fixture in texts else (repo / source.get(fixture, fixture)).read_text("utf-8")
        recorded = json.loads(text)["source"]
        example = recorded["path"]
        if example not in finals:
            raise SystemExit(f"{fixture}: its example {example} is not in the checkout")
        digest = sha256(_final_bytes(repo, example, source, texts))
        if digest == recorded["sha256"]:
            continue
        if example not in touched:
            notes.append(f"left alone: {fixture}'s digest was already stale for {example}")
            continue
        if text.count(recorded["sha256"]) != 1:
            raise SystemExit(f"{fixture}: its digest is written more than once")
        new = text.replace(recorded["sha256"], digest)
        src, old, _, count = texts.get(fixture, (source.get(fixture, fixture), text, text, 0))
        texts[fixture] = (src, old, new, count + 1)
    return notes


def integrity(repo: Path, files: List[str], texts) -> List[str]:
    """A package's ``integrity.json`` follows the files of it this run changed."""
    notes = []
    by_package: Dict[str, List[str]] = {}
    for path in texts:
        parts = path.split("/")
        if parts[0] == "packages" and len(parts) > 2:
            by_package.setdefault(parts[1], []).append("/".join(parts[2:]))
    for package, changed in sorted(by_package.items()):
        listing = f"packages/{package}/integrity.json"
        if listing not in files:
            notes.append(f"{package} has no integrity.json")
            continue
        text = (repo / listing).read_text("utf-8")
        data = json.loads(text)
        if json.dumps(data, indent=2, sort_keys=True) != text:
            raise SystemExit(f"{listing} is not written as regen_integrity.py writes it")
        for rel in changed:
            if rel in data["sha256"]:
                data["sha256"][rel] = sha256(texts[f"packages/{package}/{rel}"][2].encode("utf-8"))
        new = json.dumps(data, indent=2, sort_keys=True)
        if new != text:
            texts[listing] = (listing, text, new, len(changed))
    return notes


# --------------------------------------------------------------------------
# Printing and doing it
# --------------------------------------------------------------------------

def _clip(line: str, width: int = 300) -> str:
    return line if len(line) <= width else line[:width] + " ..."


def _around(old: str, new: str, width: int = 220) -> Tuple[str, str]:
    """Two long lines cut to the part around their first difference."""
    if len(old) <= width and len(new) <= width:
        return old, new
    same = 0
    while same < min(len(old), len(new)) and old[same] == new[same]:
        same += 1
    start = max(0, same - 60)
    cut = lambda s: ("... " if start else "") + s[start:start + width] + (" ..." if len(s) > start + width else "")
    return cut(old), cut(new)


def show(p: Plan) -> None:
    frames = [m for m in p.moves if m[0].startswith(FRAMES + "/")]
    for src, dst in p.moves:
        print(f"git mv {src} {dst}")
    references = 0
    for final in sorted(p.texts):
        src, old, new, count = p.texts[final]
        references += count
        label = final if src == final else f"{final} (was {src})"
        print(f"\n{label}: {count} reference(s)")
        a, b = old.splitlines(), new.splitlines()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            if i2 - i1 == j2 - j1:
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    before, after = _around(a[i], b[j])
                    print(f"  {i + 1:5d} - {before}")
                    print(f"  {j + 1:5d} + {after}")
                continue
            for i in range(i1, i2):
                print(f"  {i + 1:5d} - {_clip(a[i])}")
            for j in range(j1, j2):
                print(f"  {j + 1:5d} + {_clip(b[j])}")
    for note in p.notes:
        print(f"note: {note}")
    print(f"\n{len(p.moves)} files to move ({len(frames)} baselines), "
          f"{references} references in {len(p.texts)} files")


def dirty(repo: Path) -> List[str]:
    return [line for line in git(repo, "status", "--porcelain").splitlines() if line.strip()]


def run(repo: Path) -> None:
    changes = dirty(repo)
    if changes:
        raise SystemExit("refusing to run on a checkout with changes:\n  " + "\n  ".join(changes[:20]))
    p = plan(repo)
    show(p)
    for src, dst in p.moves:
        (repo / dst).parent.mkdir(parents=True, exist_ok=True)
        git(repo, "mv", src, dst)
    for final, (_src, _old, new, _count) in p.texts.items():
        with open(repo / final, "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
    print("\ndone; now run --check, scripts/generate_contracts.py --check and "
          "scripts/validate_trill.py --all --resolve")


# --------------------------------------------------------------------------
# --check
# --------------------------------------------------------------------------

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+")
OLD_IN_FRAME = re.compile(r"[_-](?:" + "|".join(re.escape(e.old) for e in BY_LENGTH) + r")[_.-]")


def leftovers(text: str) -> List[Tuple[int, str]]:
    """Every place in *text* that still names an old example: (offset, what)."""
    found = []
    for e in named_in(text):
        patterns = [file_name_rx(e)] + frame_rxs(e)
        if e.dataflow and e.folder == TESTS:
            patterns.append(key_rx(e))
        if not e.word:
            patterns.append(word_rx(e))
        if e.word and e.dataflow:
            patterns.append(called_dataflow_rx(e))
            for q in ('"', "'"):
                patterns += [rx(r"(?<=" + c.format(q=q) + r")" + re.escape(e.old) + r"(?=" + q + r")")
                             for c in ID_CONTEXTS]
        if e.was and e.new_name != e.was:
            patterns.append(rx(_phrase(e.was)))
        for pattern in patterns:
            found += [(m.start(), m.group(0)) for m in pattern.finditer(text)]
    found += [(start, word + " (in a list of examples)") for start, _end, word in listed_words(text, after=True)]
    return sorted(set(found))


QUOTED_WORD = re.compile(r"(?<=[\"'`])(?:" + "|".join(re.escape(w) for w in sorted(WORD_OLD, key=len, reverse=True))
                         + r")(?=[\"'`])")


def check(repo: Path) -> int:
    files = tracked(repo)
    present = set(files)
    problems: List[str] = []
    names: List[str] = []
    review: List[str] = []

    for e in RENAMES:
        for src, dst in zip(entry_paths(e, e.old), entry_paths(e, e.new)):
            if src in present:
                problems.append(f"{src} is still there")
            if dst not in present:
                problems.append(f"{dst} is missing")
        if not e.dataflow or entry_paths(e, e.new)[0] not in present:
            continue
        path, fixture = entry_paths(e, e.new)[:2]
        flow = json.loads((repo / path).read_text("utf-8"))["dataflow"]
        if flow.get("name") != e.new_name:
            problems.append(f"{path} is named {flow.get('name')!r}, not {e.new_name!r}")
        if flow.get("provenance_id") in (e.old, e.was) and flow.get("provenance_id") != e.new_name:
            problems.append(f"{path} keeps the provenance id {flow.get('provenance_id')!r}")
        if fixture in present:
            data = json.loads((repo / fixture).read_text("utf-8"))
            walkthrough = entry_paths(e, e.new)[2] if not e.folder else None
            if data.get("fixtureId") != e.new:
                problems.append(f"{fixture}: fixtureId {data.get('fixtureId')!r}, not {e.new!r}")
            if data["source"].get("path") != path or data["source"].get("walkthrough") != walkthrough:
                problems.append(f"{fixture}: its source is {data['source']}, not {path} and {walkthrough}")

    for fixture in sorted(p for p in files if p.startswith(PROMPTS + "/") and p.endswith(".prompt.json")):
        source = json.loads((repo / fixture).read_text("utf-8"))["source"]
        if source["path"] not in present:
            problems.append(f"{fixture}: {source['path']} is not tracked")
        elif sha256((repo / source["path"]).read_bytes()) != source["sha256"]:
            problems.append(f"{fixture}: source.sha256 is not the digest of {source['path']}")

    for folder in (EXAMPLES, f"{EXAMPLES}/{TESTS}"):
        for path in files:
            parent, _, name = path.rpartition("/")
            if parent == folder and not name.startswith(".") and not NAME.fullmatch(name):
                problems.append(f"{path} is not named in lowercase words joined by dashes")

    keys = {p.rsplit("/", 1)[1][:-5] for p in files if re.fullmatch(EXAMPLES + r"/[^/]+\.json", p)}
    keys |= {"dataflows/" + p.rsplit("/", 1)[1][:-5] for p in files
             if re.fullmatch(EXAMPLES + r"/dataflows/[^/]+\.json", p)}
    golden_path = "utk_curio/backend/tests/test_projects/shipped_categories.json"
    if golden_path in present:
        golden = set(json.loads((repo / golden_path).read_text("utf-8")))
        if golden != keys:
            problems.append(f"{golden_path}: keys differ from the shipped dataflows: "
                            f"{sorted(golden ^ keys)}")

    for path in files:
        if path.startswith(FRAMES + "/"):
            name = path[len(FRAMES) + 1:]
            if frame_target(name):
                problems.append(f"{path} is still named after an old example")
            elif OLD_IN_FRAME.search(name):
                problems.append(f"{path} names an old example in a way this script does not move")

    for path in files:
        if path.startswith("packages/") and path.endswith("/integrity.json"):
            root = path[: -len("integrity.json")]
            for rel, digest in json.loads((repo / path).read_text("utf-8"))["sha256"].items():
                full = repo / (root + rel)
                if full.is_file() and sha256(full.read_bytes()) != digest:
                    problems.append(f"{path}: {rel} has changed since it was written")

    for path in files:
        if SKIP.search(path):
            continue
        text = read_text(repo, path)
        if text is None or not TRIGGER.search(text):
            continue
        for offset, what in leftovers(text):
            line = text.count("\n", 0, offset) + 1
            names.append(f"{path}:{line}: still names {what!r}")
        if re.fullmatch(EXAMPLES + r"/(?:dataflows/)?[^/]+\.json", path):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for m in QUOTED_WORD.finditer(line):
                if not any(path == f and allowed in line for f, allowed, _why in NOT_EXAMPLES):
                    review.append(f"{path}:{number}: {m.group(0)!r}: {_clip(line.strip(), 160)}")

    for item in problems:
        print(f"problem: {item}")
    for item in names:
        print(f"old name: {item}")
    for item in review:
        print(f"to review (a quoted word that is also an old name): {item}")
    print(f"\n{len(problems)} problems, {len(names)} old names, {len(review)} to review, "
          f"in {len(files)} tracked files")
    return 1 if problems or names else 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="the checkout to work on (default: this script's)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print every move and changed line, write nothing")
    mode.add_argument("--check", action="store_true", help="exit 1 while an old name is still referenced")
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo = args.repo.resolve()
    if not (repo / EXAMPLES).is_dir():
        raise SystemExit(f"{repo} has no {EXAMPLES}")
    if args.check:
        return check(repo)
    if args.dry_run:
        show(plan(repo))
        return 0
    run(repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
