"""Worked examples: shipped dataflows chosen per run, for the run's runtime slot.

``llm-prompts/examples.md`` indexes every dataflow Curio ships, one line each,
under "Used" or "Not used". A line links its file and says what the dataflow
shows; the file itself holds the name, task, categories, node types and
datasets, so the index never repeats them.

A run of a mode that takes worked examples (``builtin.gets_worked_examples``)
gets the "Used" dataflows closest to what it knows: the user's message, the
dataflow's task, the attached node's goal and template type, or a delegated
run's inputs. Plain code: no model call, no network, and the same inputs give
the same block. The block is per run, so it rides the runtime slot and the
cached preamble stays fixed.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
from utk_curio.backend.app.projects import services as projects_services

log = logging.getLogger(__name__)

#: The index, beside the prompts in ``llm-prompts/``.
INDEX_FILE = "examples.md"
#: The index's two sections: the dataflows a run may be given, and the rest.
USED = "Used"
NOT_USED = "Not used"

#: At most this many examples per run.
TOP_K = 2
#: The block's size bound, in characters: the size of the example dataflow the
#: shared preamble embedded before this block replaced it ("An example of a
#: dataflow:" through the "Attention:" line after it). An example that does
#: not fit is left out; the next one in rank order may still fit.
MAX_BLOCK_CHARS = 7_232
#: Words shorter than this never count.
MIN_WORD_LEN = 3
#: Added to an example's score when it uses the attached node's template type.
TEMPLATE_BONUS = 2
#: Added to an example's score when it uses a dataset the run's dataflow uses.
DATASET_BONUS = 3
#: Words too common to tell one dataflow from another.
STOP_WORDS = frozenset({
    "about", "after", "all", "also", "and", "any", "are", "before", "both", "but",
    "can", "could", "each", "for", "from", "get", "has", "have", "how", "into",
    "its", "just", "like", "make", "more", "most", "need", "not", "one", "only",
    "other", "our", "out", "over", "per", "please", "same", "should", "show",
    "showing", "shown", "shows", "some", "such", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "two", "use",
    "using", "want", "was", "what", "when", "where", "which", "while", "who",
    "why", "will", "with", "would", "you", "your",
    # Every dataflow has these.
    "builtin", "curio", "data", "dataflow", "dataflows", "dataset", "datasets",
    "docs", "example", "examples", "json", "node", "nodes",
})

#: What opens the block.
HEADING = (
    "Worked examples: shipped Curio dataflows close to this task, chosen for this "
    "run. Learn from how their nodes, code and specs fit together. The datasets "
    "and node types this task uses come from this project, not from these "
    "examples: a dataset is loaded by its Data Catalog id, never a guessed filename."
)

# An evaluation marks the project it builds with ``dataflow.evaluation``
# (``agents/evaluation/authorization.MARKER_KEY``). Its ``fixtureId`` is the
# stem of the example the run is scored against, so no run in that project is
# shown that example, attached, delegated or in a Solve.
_EVALUATION_KEY = "evaluation"

#: The Trill a run is shown: the fields the preamble's Trill block describes,
#: without the layout.
_DATAFLOW_FIELDS = tuple(f for f in contracts.TRILL_PROMPT_FIELDS["dataflowBase"] if f not in ("nodes", "edges"))
_NODE_FIELDS = tuple(f for f in contracts.TRILL_PROMPT_FIELDS["node"] if f not in ("x", "y"))
_EDGE_FIELDS = contracts.TRILL_PROMPT_FIELDS["edge"]

#: The inputs of a delegated run that say what it is for.
_DELEGATED_TEXT_INPUTS = ("subtask", "workflowGoal", "intent", "nodeIntent", "mission")

_LINE_RE = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<target>[^)\s]+)\): (?P<text>\S.*)$")
_WORD_RE = re.compile(r"[a-z0-9]+")
_VERSION_RE = re.compile(r"@\d+$")
_SEP = "\n\n"

_warned_missing = False


@dataclass(frozen=True)
class IndexEntry:
    """One line of the index: its section, its link and what it says."""

    section: str
    title: str
    #: The link as written, relative to ``llm-prompts/`` so it works on GitHub.
    target: str
    text: str

    @property
    def path(self) -> Path:
        return (builtin.PROMPT_SOURCE_DIR / self.target).resolve()

    @property
    def line(self) -> str:
        """The line as a run shows it: the title and what it says, without the link."""
        return f"{self.title}: {self.text}"


@dataclass(frozen=True)
class Example:
    """A "Used" dataflow, read and ready to score."""

    #: Its shipped key: ``09-heterogeneous-data-linked-views``, ``dataflows/Regression``.
    key: str
    entry: IndexEntry
    spec: dict
    words: frozenset
    node_types: frozenset
    dataset_ids: frozenset

    def is_named_by(self, item: object) -> bool:
        """Whether *item* names this example: its key, its file's stem or name, or a path to it."""
        text = str(item or "").strip()
        if not text:
            return False
        path = self.entry.path
        if text in (self.key, path.stem, path.name):
            return True
        tail = Path(text).as_posix().lstrip("./")
        return bool(tail) and path.as_posix().endswith("/" + tail)


def parse_index(text: str) -> list[IndexEntry]:
    """Every linked line of *text*, in order, with the ``## `` section above it."""
    entries: list[IndexEntry] = []
    section = None
    for raw in text.splitlines():
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        match = _LINE_RE.match(raw.strip())
        if section is not None and match:
            entries.append(IndexEntry(section, match["title"], match["target"], match["text"]))
    return entries


def read_index() -> list[IndexEntry]:
    """The index as it is on disk now, read on every call like the prompts; empty when missing."""
    text = builtin.read_prompt_file(INDEX_FILE, wanted_by="the worked examples")
    return parse_index(text) if text else []


def words(text: object) -> set[str]:
    """The words of *text* that count: folded to ASCII lower case, at least
    ``MIN_WORD_LEN`` long, not a stop word, with a plural ``s`` dropped."""
    if not isinstance(text, str):
        return set()
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    out = set()
    for word in _WORD_RE.findall(folded):
        if len(word) < MIN_WORD_LEN or word in STOP_WORDS:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss") and len(word) > MIN_WORD_LEN:
            word = word[:-1]
        if word not in STOP_WORDS:
            out.add(word)
    return out


def dataset_ids_of(spec: object) -> set[str]:
    """The dataset ids a dataflow uses: its node code's catalog calls and its dataset refs."""
    dataflow = _dataflow(spec)
    ids: set[str] = set()
    for node in _dicts(dataflow.get("nodes")):
        ids.update(dataset_ids_in_code(node.get("content")))
    for ref in _dicts(dataflow.get("datasets")):
        raw = ref.get("id") or ref.get("datasetId") or ref.get("dirName")
        if isinstance(raw, str) and raw:
            ids.add(_VERSION_RE.sub("", raw))
    return ids


def excluded_by(spec: object) -> set[str]:
    """What a run in this project must not be shown: the example an evaluation scores it against."""
    marker = _dataflow(spec).get(_EVALUATION_KEY)
    fixture_id = marker.get("fixtureId") if isinstance(marker, dict) else None
    return {fixture_id} if isinstance(fixture_id, str) and fixture_id else set()


def used_examples() -> list[Example]:
    """The "Used" dataflows, read now. Empty, with one warning per process,
    when this install ships no dataflows (a pip install has no ``docs/examples``)."""
    global _warned_missing
    shipped = projects_services.shipped_dataflow_paths()
    if not shipped:
        if not _warned_missing:
            _warned_missing = True
            log.warning(
                "No shipped dataflows found (an installed Curio ships no docs/examples), "
                "so runs get no worked examples"
            )
        return []
    keys = {path.resolve(): key for key, path in shipped.items()}
    out = []
    for entry in read_index():
        key = keys.get(entry.path)
        if entry.section != USED or key is None:
            continue
        try:
            spec = json.loads(entry.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Worked example %s is unreadable (%s); runs go without it", entry.target, exc)
            continue
        out.append(_example(key, entry, spec))
    return out


def select(query: str, *, node_type: object = None, dataset_ids=(), exclude=(),
           examples: list[Example] | None = None) -> list[Example]:
    """The examples a run asking *query* gets, best first, at most ``TOP_K``.

    An example scores one point per word it shares with the query (its index
    line, file name, task and categories against the query and the node's
    template type), plus ``TEMPLATE_BONUS`` when it uses *node_type* and
    ``DATASET_BONUS`` when it uses one of *dataset_ids*. The bonuses rank the
    examples that share a word; alone they choose nothing. Ties keep index
    order. *exclude* names examples to leave out (``Example.is_named_by``).
    """
    wanted = words(query) | words(node_type)
    if not wanted:
        return []
    pool = used_examples() if examples is None else examples
    node_type = _unversioned(node_type)
    dataset_ids = set(dataset_ids)
    ranked = []
    for position, example in enumerate(pool):
        if any(example.is_named_by(item) for item in exclude):
            continue
        overlap = len(wanted & example.words)
        if not overlap:
            continue
        score = (
            overlap
            + (TEMPLATE_BONUS if node_type and node_type in example.node_types else 0)
            + (DATASET_BONUS if dataset_ids & example.dataset_ids else 0)
        )
        ranked.append((-score, position, example))
    ranked.sort(key=lambda row: row[:2])
    return [example for _score, _position, example in ranked[:TOP_K]]


def render(chosen: list[Example], *, cap: int = MAX_BLOCK_CHARS) -> str | None:
    """The block for *chosen*, in order: the heading, then each example's line
    and its Trill. An example that would take the block past *cap* is left out;
    None when none fits."""
    pieces: list[str] = []
    size = len(HEADING)
    for example in chosen:
        piece = f"{example.entry.line}\n```json\n{trill_text(example.spec)}\n```"
        if size + len(_SEP) + len(piece) > cap:
            continue
        pieces.append(piece)
        size += len(_SEP) + len(piece)
    return _SEP.join([HEADING, *pieces]) if pieces else None


def trill_text(spec: object) -> str:
    """*spec* as a run is shown it: name, task, nodes and edges, one line per
    node and per edge, without layout or empty fields. Valid JSON."""
    dataflow = _dataflow(spec)
    head = [f"  {json.dumps(key)}: {_dump(value)}," for key, value in _kept(dataflow, _DATAFLOW_FIELDS).items()]
    nodes = ",\n".join(f"    {_dump(_kept(node, _NODE_FIELDS))}" for node in _dicts(dataflow.get("nodes")))
    edges = ",\n".join(f"    {_dump(_kept(edge, _EDGE_FIELDS))}" for edge in _dicts(dataflow.get("edges")))
    return "\n".join(['{"dataflow": {', *head, '  "nodes": [', nodes, "  ],", '  "edges": [', edges, "  ]", "}}"])


def block_for(query: str, *, node_type: object = None, dataset_ids=(), exclude=()) -> str | None:
    """The worked-examples block for one run, or None when nothing matches."""
    try:
        return render(select(query, node_type=node_type, dataset_ids=dataset_ids, exclude=exclude))
    except Exception as exc:  # a broken index or file costs the examples, never the run
        log.warning("Worked examples unavailable (%s: %s); the run goes without them",
                    type(exc).__name__, exc)
        return None


def attached_block(coord: str, spec: object, target: object, message: str) -> str | None:
    """The block an attached run of *coord* carries in its runtime slot, or None.

    The query is the user's message, the dataflow's task, and the attached
    node's goal and template type."""
    if not builtin.gets_worked_examples(coord):
        return None
    dataflow = _dataflow(spec)
    node = _target_node(dataflow, target)
    query = " ".join(_texts(message, dataflow.get("task"), node.get("goal")))
    return block_for(query, node_type=node.get("type"), dataset_ids=dataset_ids_of(spec),
                     exclude=excluded_by(spec))


def delegated_block(coord: str, capability: str, spec: object, inputs: object) -> str | None:
    """The block a delegated run of *coord* in *capability*'s mode carries, or None.

    The query is what the parent handed it: the subtask, the workflow goal,
    the node's intent and the node context's goals."""
    if not builtin.gets_worked_examples(coord, capability):
        return None
    inputs = inputs if isinstance(inputs, dict) else {}
    context = inputs.get("nodeContext") if isinstance(inputs.get("nodeContext"), dict) else {}
    summary = context.get("graphSummary") if isinstance(context.get("graphSummary"), dict) else {}
    query = " ".join(_texts(*(inputs.get(k) for k in _DELEGATED_TEXT_INPUTS),
                            context.get("intent"), summary.get("goal")))
    return block_for(query, node_type=inputs.get("nodeType") or context.get("nodeType"),
                     dataset_ids=dataset_ids_of(spec), exclude=excluded_by(spec))


def _example(key: str, entry: IndexEntry, spec: dict) -> Example:
    dataflow = _dataflow(spec)
    categories = dataflow.get("categories") if isinstance(dataflow.get("categories"), dict) else {}
    values = [str(v) for vs in categories.values() if isinstance(vs, list) for v in vs]
    text = " ".join([entry.title, entry.path.stem, entry.text,
                     *_texts(dataflow.get("name"), dataflow.get("task")), *values])
    types = {_unversioned(node.get("type")) for node in _dicts(dataflow.get("nodes"))}
    return Example(key=key, entry=entry, spec=spec, words=frozenset(words(text)),
                   node_types=frozenset(t for t in types if t), dataset_ids=frozenset(dataset_ids_of(spec)))


def _target_node(dataflow: dict, target: object) -> dict:
    if not isinstance(target, dict) or target.get("kind") != "node":
        return {}
    return next((n for n in _dicts(dataflow.get("nodes")) if n.get("id") == target.get("targetId")), {})


def _unversioned(node_type: object) -> str | None:
    return _VERSION_RE.sub("", node_type) if isinstance(node_type, str) and node_type else None


def _dataflow(spec: object) -> dict:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    return dataflow if isinstance(dataflow, dict) else {}


def _dicts(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _texts(*values: object) -> list[str]:
    return [v for v in values if isinstance(v, str) and v.strip()]


def _kept(item: dict, fields) -> dict:
    return {f: item[f] for f in fields if f in item and not _empty(item[f])}


def _empty(value: object) -> bool:
    if isinstance(value, dict):
        return all(_empty(v) for v in value.values())
    return value is None or value == "" or value == []


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
