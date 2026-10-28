"""A package's skills in runs: listed where it is used, handed to runs writing its nodes, named once, kept as written.

A package ships skills for Curio's agents in ``skills/<name>/SKILL.md``
(``packages/repositories/skills.py``). A run on a dataflow holds the skills of
the packages its lockfile names (``dataflow.packages``), whatever its agent's
manifest names: its chat lists them after the agent's own, and a run that
writes one of the package's nodes is handed those whose ``curio-templates``
names that node's template among the package's own. A name shows once:
Curio's skill, then the first package's in the lockfile's order, and a warning
names each skill left out. A package's skill is read strictly, as Curio's
are, and held as written: no marker of its own is filled. Scout
(``curio.scout@1``) ships the first, ``scout``.

Runs go through the scripted provider (``testing_provider``), on an account
whose store holds Scout as the repository ships it. New names are read inside
each test, so this module imports on a checkout without them and each test
fails on its own.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_agents.test_skill_runs import (  # noqa: F401 - scripted is a fixture
    CA,
    CODE_SKILLS,
    DF,
    ENDPOINT,
    FEATURE_SKILLS,
    NB,
    READER,
    VEGA_SKILLS,
    _attach,
    _listed,
    _manifest,
    _names,
    _preamble,
    _read,
    _run,
    _run_calls,
    _slot,
    _turns,
    _wrapped,
    scripted,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SCOUT = "curio.scout@1"
SCOUT_DIR = REPO_ROOT / "packages" / SCOUT
SCOUT_SKILL = SCOUT_DIR / "skills" / "scout"
CALC = "curio.scout/raster-calculator"
BARS = "curio.scout/bars"
#: An account whose store the pure calls read, under the test's own folder.
KEY = "4343"
PID = "p-package-skills"
#: A dataflow that uses Scout: a Raster Calculator, a Scout chart, and a
#: Python node of Curio's.
SCOUT_NODES = [
    {"id": "calc", "type": CALC, "content": "", "x": 0, "y": 0},
    {"id": "chart", "type": BARS, "content": "{}", "x": 400, "y": 0},
    {"id": "count", "type": CA, "content": "return 1", "x": 0, "y": 300},
]
SKILL_LOGGER = "utk_curio.backend.app.agents.application.skill_runs"


def _skill_runs():
    from utk_curio.backend.app.agents.application import skill_runs

    return skill_runs


def _store_scout(key: str) -> None:
    """Scout in *key*'s store, as the repository ships it."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    shutil.copytree(SCOUT_DIR, user_packages_dir(key) / SCOUT, dirs_exist_ok=True)


def _skill(name: str, body: str, metadata: str = "") -> str:
    """A ``SKILL.md`` named *name*, holding *body*, with *metadata*'s lines
    under the author's."""
    return (f"---\nname: {name}\ndescription: Use this skill when a node works on {name}.\nlicense: MIT\n"
            f"metadata:\n  author: test\n{metadata}---\n{body}")


def _store_package(key: str, package_id: str, skills: dict[str, str], templates: tuple[str, ...] = ()) -> str:
    """A package of *package_id* in *key*'s store, as an install leaves it: a
    manifest with Python templates *templates* (one when none is given), and
    each of *skills*, a ``SKILL.md`` by its folder's name."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    dir_name = f"{package_id}@1"
    root = user_packages_dir(key) / dir_name
    root.mkdir(parents=True)
    manifest = {
        "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1}, "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [
            {"id": template, "label": template, "category": "computation", "engine": "python", "editor": "code",
             "behavior": "code", "hasCode": True, "inputPorts": [],
             "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}]}
            for template in templates or ("count",)
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, text in skills.items():
        (root / "skills" / name).mkdir(parents=True)
        (root / "skills" / name / "SKILL.md").write_text(text, encoding="utf-8")
    return dir_name


def _project(client, headers, *, packages=(), nodes=()) -> str:
    body = {"name": "p", "spec": {"dataflow": {"nodes": list(nodes), "edges": [], "packages": list(packages)}},
            "outputs": []}
    resp = client.post("/api/projects", json=body, headers=headers)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _scout_held() -> str:
    """Scout's skill as a run holds it: its body as written, wrapped."""
    from utk_curio.backend.app.agents.domain import skills

    return f'<skill_content name="scout">\n{skills.parse(SCOUT_SKILL).body.rstrip()}\n</skill_content>'


def _warnings(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records
            if record.name == SKILL_LOGGER and record.levelno == logging.WARNING]


# --- Scout's skill in runs ----------------------------------------------------------------


def test_a_chat_on_a_scout_dataflow_lists_scout_after_its_agents_skills_and_loads_it_and_one_without_does_not(
    client, user_and_token, tmp_curio, scripted, record_property,
):
    """The Node Builder's chat on a dataflow that uses Scout lists Scout's
    skill after the skills its manifest names, and skill.read loads it as
    written, its frontmatter left out, and records it; on a dataflow without
    Scout, the same account's chat lists the manifest's skills alone."""
    user, _ = user_and_token
    key = _user_dir_key(user)
    _store_scout(key)
    with_scout = _project(client, scripted, packages=[SCOUT], nodes=SCOUT_NODES)
    assert SCOUT in projects_storage.read_spec(key, with_scout)["dataflow"]["packages"]
    att = _attach(client, scripted, with_scout, NB)
    testing_provider.push_replies(_read("scout"), "Done.")
    _run(client, scripted, with_scout, att)
    calls = _run_calls()
    listed = _listed(_slot(calls[0][0], "skill-catalog"))
    record_property("a chat's catalog on a Scout dataflow", json.dumps(listed))
    assert listed == [*FEATURE_SKILLS, "scout"]
    assert _scout_held() in calls[1][-1]["content"]
    record = _turns(client, scripted, with_scout, att)[-1]["execution"]
    assert record["pins"]["skills"] == {"catalog": [*FEATURE_SKILLS, "scout"]}
    assert record["skillsLoaded"] == ["scout"]

    testing_provider.reset()
    without = _project(client, scripted, nodes=SCOUT_NODES[2:])
    att = _attach(client, scripted, without, NB)
    testing_provider.push_reply("Hello.")
    _run(client, scripted, without, att)
    (system, *_), = _run_calls()
    assert _listed(_slot(system, "skill-catalog")) == FEATURE_SKILLS
    assert '<name>scout</name>' not in system["content"]


def test_a_run_writing_a_scout_node_is_handed_scout_and_one_writing_curios_python_node_is_not(
    client, user_and_token, tmp_curio, scripted, record_property,
):
    """On a dataflow that uses Scout, a delegated run that writes the Raster
    Calculator, or a Scout chart named by its node, is handed Scout's skill
    after the skills of the node's behavior, and its record names it; a run
    that writes Curio's Python node there is handed the skills of node code
    alone. A chat attached to the Raster Calculator holds it from its first
    message."""
    from utk_curio.backend.app.agents.application import delegation

    user, _ = user_and_token
    key = _user_dir_key(user)
    _store_scout(key)
    pid = _project(client, scripted, packages=[SCOUT], nodes=SCOUT_NODES)
    for inputs, handed in (
        ({"nodeType": CALC, "intent": "how much the flood depth changed"}, [*CODE_SKILLS, "scout"]),
        ({"nodeId": "chart", "intent": "compare the scenarios' costs"}, [*VEGA_SKILLS, "scout"]),
        ({"nodeType": CA, "intent": "count the rows"}, CODE_SKILLS),
    ):
        testing_provider.reset()
        status, _text, record = delegation.run_delegate(
            key, pid, NB, "node.content.generate", inputs, ENDPOINT,
            parent_execution_id="p", parent_coord="agent.curio.dataflow-builder@1", attachment_id=None,
        )
        assert status == "ok", _text
        (system, *_), = testing_provider.captured()
        record_property(f"handed to a run writing {inputs.get('nodeType') or inputs['nodeId']}",
                        json.dumps(_wrapped(_slot(system, "skills"))))
        assert _wrapped(_slot(system, "skills")) == handed, inputs
        assert record["pins"]["skills"] == {"handed": handed}
        assert (_scout_held() in _slot(system, "skills")) == ("scout" in handed)

    testing_provider.reset()
    att = _attach(client, scripted, pid, NB, {"kind": "node", "targetId": "calc"})
    testing_provider.push_reply("Done.")
    _run(client, scripted, pid, att)
    (system, *_), = _run_calls()
    assert _wrapped(_slot(system, "skills")) == [*CODE_SKILLS, "scout"]
    assert _listed(_slot(system, "skill-catalog")) == [*FEATURE_SKILLS, "scout"]


def test_every_scout_template_is_handed_scout_and_every_agent_on_its_dataflow_lists_it(tmp_curio):
    """Each of Scout's seventeen templates, versioned or not, is handed its
    skill; so is a mode that reads a dataflow holding Scout's nodes. A
    dataflow that uses Scout with none of its nodes hands it to no reader,
    and every agent's chat lists it there, the Dataset Finder's too, after
    the one skill its manifest names."""
    skill_runs = _skill_runs()
    _store_scout(KEY)
    manifest = json.loads((SCOUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    templates = [template["id"] for template in manifest["templates"]]
    assert len(templates) == 17, templates
    spec = {"dataflow": {"packages": [SCOUT], "nodes": SCOUT_NODES, "edges": []}}
    unhanded = [
        node_type for template in templates
        for node_type in (f"curio.scout/{template}", f"curio.scout/{template}@1")
        if "scout" not in _names(skill_runs.for_delegated(
            KEY, PID, _manifest(NB), "node.content.generate", {"nodeType": node_type}, spec, _preamble(NB),
        ).handed)
    ]
    assert unhanded == []
    reader = skill_runs.for_delegated(KEY, PID, _manifest(READER), "dataflow.explain", {}, spec, _preamble(READER))
    assert _names(reader.handed)[-1] == "scout", _names(reader.handed)

    no_scout_nodes = {"dataflow": {"packages": [SCOUT], "nodes": SCOUT_NODES[2:], "edges": []}}
    reader = skill_runs.for_delegated(KEY, PID, _manifest(READER), "dataflow.explain", {}, no_scout_nodes,
                                      _preamble(READER))
    assert "scout" not in _names(reader.handed)
    finder = skill_runs.for_chat(KEY, PID, _manifest(DF), no_scout_nodes, {"kind": "canvas"}, _preamble(DF), [])
    assert finder.names == ["catalogs", "scout"]
    assert skill_runs.grants([], finder) == ["skill.read"]


# --- A package's skills, in order ---------------------------------------------------------


def test_a_package_skill_named_as_curios_or_an_earlier_packages_is_listed_once_with_a_warning(tmp_curio, caplog):
    """A package's ``widgets`` is left out for Curio's, even for an agent
    whose manifest does not name Curio's, and a ``street-trees`` of a second
    package for the first one's, in the lockfile's order; a warning names
    each skill left out, its package, and who ships the skill runs hold."""
    from utk_curio.backend.app.agents.domain import skills

    skill_runs = _skill_runs()
    first = _store_package(KEY, "acme.first", {"street-trees": _skill("street-trees", "## Trees\n\nThe first's.\n")})
    second = _store_package(KEY, "acme.second", {
        "widgets": _skill("widgets", "## Widgets\n\nThe second's.\n"),
        "street-trees": _skill("street-trees", "## Trees\n\nThe second's.\n"),
        "park-shade": _skill("park-shade", "## Shade\n\nThe second's.\n"),
    })
    spec = {"dataflow": {"packages": [second, first], "nodes": [], "edges": []}}
    with caplog.at_level(logging.WARNING, logger=SKILL_LOGGER):
        chat = skill_runs.for_chat(KEY, PID, _manifest(NB), spec, {"kind": "canvas"}, _preamble(NB), [])
        finder = skill_runs.for_chat(KEY, PID, _manifest(DF), spec, {"kind": "canvas"}, _preamble(DF), [])
    assert chat.names == [*FEATURE_SKILLS, "street-trees", "park-shade"]
    assert finder.names == ["catalogs", "street-trees", "park-shade"]
    by_name = {skill.name: skill for skill in chat.catalog}
    assert skills.is_shipped(by_name["widgets"])
    assert by_name["street-trees"].folder.parent.parent.name == first
    warned = _warnings(caplog)
    assert any("widgets" in line and second in line and "Curio" in line for line in warned), warned
    assert any("street-trees" in line and second in line and first in line for line in warned), warned


def test_a_package_skill_is_held_as_written_where_curios_is_rendered(tmp_curio):
    """A package's skill keeps the markers its body holds, in the catalog's
    load and in the turn it is handed to, where a skill Curio ships has its
    markers filled."""
    skill_runs = _skill_runs()
    marked = "## Notes\n\nA {{template.label:curio.builtin/edit-features}} node, and {{skill:widgets}} here.\n"
    notes = _store_package(KEY, "acme.notes", {"edit-notes": _skill("edit-notes", marked)})
    spec = {"dataflow": {"packages": [notes], "nodes": [], "edges": []}}
    chat = skill_runs.for_chat(KEY, PID, _manifest(NB), spec, {"kind": "canvas"}, _preamble(NB), [])
    by_name = {skill.name: skill for skill in chat.catalog}
    assert {"edit-notes", "map-edits"} <= set(by_name), chat.names
    held = f'<skill_content name="edit-notes">\n{marked.rstrip()}\n</skill_content>'
    assert skill_runs.content(by_name["edit-notes"], readable=True) == held
    status, text = skill_runs.read(chat, {"name": "edit-notes"})
    assert status == "ok" and marked.rstrip() in text
    map_edits = skill_runs.content(by_name["map-edits"], readable=True)
    assert "{{" not in map_edits and "## Map Editor" in map_edits


def test_a_package_skill_serves_its_own_packages_templates_and_no_others(tmp_curio):
    """``curio-templates`` names templates of the skill's own package, by
    their ids in its manifest: a skill naming ``computation-analysis`` serves
    its package's node of that id, which it has none of, never Curio's
    Python node."""
    skill_runs = _skill_runs()
    trees = _store_package(
        KEY, "acme.trees",
        {"street-trees": _skill("street-trees", "## Trees\n", "  curio-templates: tree-count computation-analysis\n")},
        templates=("tree-count",),
    )
    nodes = [{"id": "t", "type": "acme.trees/tree-count"}, {"id": "c", "type": CA}]
    spec = {"dataflow": {"packages": [trees], "nodes": nodes, "edges": []}}

    def handed(inputs) -> list[str]:
        return _names(skill_runs.for_delegated(
            KEY, PID, _manifest(NB), "node.content.generate", inputs, spec, _preamble(NB),
        ).handed)

    assert handed({"nodeType": "acme.trees/tree-count"}) == [*CODE_SKILLS, "street-trees"]
    assert handed({"nodeId": "t"}) == [*CODE_SKILLS, "street-trees"]
    assert handed({"nodeType": CA}) == CODE_SKILLS
    chat = skill_runs.for_chat(KEY, PID, _manifest(NB), spec, {"kind": "canvas"}, _preamble(NB), [])
    by_name = {skill.name: skill for skill in chat.catalog}
    assert "street-trees" in by_name, chat.names
    skill = by_name["street-trees"]
    assert skill_runs.templates_served(skill, trees) == {"acme.trees/tree-count", "acme.trees/computation-analysis"}
    assert skill_runs.templates_served(skill, None) == set()


def test_a_package_skill_that_cannot_be_read_is_left_out_and_logged(tmp_curio, caplog):
    """A skill in an account's copy that breaks the format, as only a hand
    edit can leave one, is left out of runs and logged, naming its package and
    its file; the package's other skills are listed."""
    skill_runs = _skill_runs()
    mixed = _store_package(KEY, "acme.mixed", {
        "bad-name": _skill("Bad-Name", "## Bad\n"),
        "park-shade": _skill("park-shade", "## Shade\n"),
    })
    spec = {"dataflow": {"packages": [mixed], "nodes": [], "edges": []}}
    with caplog.at_level(logging.WARNING, logger=SKILL_LOGGER):
        chat = skill_runs.for_chat(KEY, PID, _manifest(NB), spec, {"kind": "canvas"}, _preamble(NB), [])
    assert chat.names == [*FEATURE_SKILLS, "park-shade"]
    warned = _warnings(caplog)
    assert any(mixed in line and "bad-name/SKILL.md" in line for line in warned), warned


def test_every_skill_a_shipped_package_ships_serves_its_own_templates_by_names_the_code_knows():
    """Each skill a package Curio ships ships is read strictly, says when to
    use it, and names what it serves by names the code knows: templates of
    its own package, behaviors Curio's templates declare, and features
    ``skill_runs`` reads. Scout's serves every Scout template, and no
    behavior, since its templates' behaviors are those of Curio's Python and
    Vega-Lite nodes; a package's skill holds no marker, since it is read as
    written."""
    from utk_curio.backend.app.agents.domain import skills
    from utk_curio.backend.app.packages.repositories.skills import skill_folders

    skill_runs = _skill_runs()
    roots = [root for root in sorted((REPO_ROOT / "packages").iterdir()) if (root / "manifest.json").is_file()]
    behaviors = {
        template["behavior"] for root in roots
        for template in json.loads((root / "manifest.json").read_text(encoding="utf-8"))["templates"]
        if template.get("behavior")
    }
    served = {}
    for root in roots:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        own = {template["id"] for template in manifest["templates"]}
        for folder in skill_folders(root):
            skill = skills.parse(folder)
            named = {key: str(skill.metadata.get(key) or "").split() for key in (
                skill_runs.TEMPLATES_KEY, skill_runs.BEHAVIORS_KEY, skill_runs.FEATURES_KEY)}
            assert skill.description.startswith("Use this skill when"), folder
            assert set(named[skill_runs.TEMPLATES_KEY]) <= own, (folder, set(named[skill_runs.TEMPLATES_KEY]) - own)
            assert set(named[skill_runs.BEHAVIORS_KEY]) <= behaviors, folder
            assert set(named[skill_runs.FEATURES_KEY]) <= set(skill_runs.FEATURES), folder
            assert "{{" not in skill.body, folder
            served[f"{root.name}/{folder.name}"] = named
    assert list(served) == [f"{SCOUT}/scout"], list(served)
    scout = skills.parse(SCOUT_SKILL)
    assert (scout.license, scout.metadata["author"]) == ("MIT", "curio")
    templates = [t["id"] for t in json.loads((SCOUT_DIR / "manifest.json").read_text(encoding="utf-8"))["templates"]]
    assert served[f"{SCOUT}/scout"] == {
        skill_runs.TEMPLATES_KEY: templates, skill_runs.BEHAVIORS_KEY: [], skill_runs.FEATURES_KEY: [],
    }
