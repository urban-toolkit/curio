"""An account's own skills: imported leniently through a review, kept in the format, exported, removed.

The import (``application/skill_lifecycle.py``) reads a skill authored
elsewhere as agentskills.io's guide for clients says: a break of the format
is a warning the review shows, and only frontmatter that is no YAML mapping
and a missing description refuse it. Curio keeps it in the format, under a
name no other skill the account sees takes, and gives it to the agents the
review picked; their runs then hold it as they hold Curio's skills. An
export is a zip of the skill's folder that agentskills.io's ``skills-ref``
validates, a skill Curio ships with its markers filled. Publishing, the
guests' refusals and what an adder keeps are held, beside the agents' own,
in ``test_catalog_entry_parity.py``.

``skills-ref`` is imported inside each test, as ``test_skills_ref.py``
imports it, so a missing library fails the test, never skips it.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import skills
from utk_curio.backend.app.agents.infrastructure import agent_skills as agent_skill_store
from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_skills import (  # noqa: F401 - scripted is a fixture
    _attach,
    _listed,
    _names,
    _project,
    _rows_url,
    _run,
    _run_calls,
    scripted,
)

DF = "agent.curio.dataset-finder@1"
RS = "agent.curio.researcher@1"
NAME = "street-trees"
CHECK = "/api/agents/skills/imports/check"
IMPORT = "/api/agents/skills/imports"


def _skill_md(name: str | None = NAME, *, description: str = "Use this skill when a dataflow counts or maps "
              "street trees.", extra: str = "", body: str = "## Street trees\n\nCount trees by block.\n") -> str:
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    lines.append(f"description: {description}")
    return "\n".join(lines) + "\n" + extra + "---\n" + body


def _form(files: dict, *, folder: str | None = NAME, **fields) -> dict:
    """A multipart upload of *files* (paths in the skill's folder to their
    text or bytes), as a picked *folder* sends them, or loose files when
    *folder* is None, with the form's other *fields*."""
    paths = [f"{folder}/{path}" if folder else path for path in files]
    parts = [(io.BytesIO(content if isinstance(content, bytes) else content.encode("utf-8")),
              path.rsplit("/", 1)[-1]) for path, content in zip(paths, files.values())]
    form = {"files": parts, "paths": json.dumps(paths)}
    form.update({key: value if isinstance(value, str) else json.dumps(value) for key, value in fields.items()})
    return form


def _zip(members: dict) -> bytes:
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in members.items():
            archive.writestr(path, content)
    return sink.getvalue()


def _zip_form(members: dict, **fields) -> dict:
    form = {"files": [(io.BytesIO(_zip(members)), "skill.zip")], "paths": json.dumps(["skill.zip"])}
    form.update({key: value if isinstance(value, str) else json.dumps(value) for key, value in fields.items()})
    return form


def _post(client, token, url, form):
    return client.post(url, data=form, content_type="multipart/form-data",
                       headers={"Authorization": f"Bearer {token}"})


def _user_skills():
    """The account's skill store, imported where a test runs, so a checkout
    without it fails each test, never the collection."""
    from utk_curio.backend.app.agents.repositories import user_skills

    return user_skills


def _kept(user, name: str = NAME) -> Path:
    return _user_skills().skill_dir(_user_dir_key(user), name)


def _nothing_kept(user) -> bool:
    return not _user_skills().skills_dir(_user_dir_key(user)).exists()


def _card(client, token, name: str = NAME) -> dict:
    cards = client.get("/api/agents/skills", headers=_auth(token)).get_json()["skills"]
    return next(card for card in cards if card["name"] == name)


def _exported(client, token, name: str, into: Path) -> Path:
    """Unzip the export of *name* into *into*; answers the skill's folder."""
    resp = client.get(f"/api/agents/skills/{name}/export", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.mimetype == "application/zip"
    assert f'filename={name}.zip' in resp.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.get_data())) as archive:
        assert all(member.startswith(f"{name}/") for member in archive.namelist()), archive.namelist()
        archive.extractall(into)
    return into / name


# --- The review --------------------------------------------------------------------


QUIRKY = _skill_md(
    description="Use this skill when: a dataflow counts street trees",
    extra="author: parks-team\nversion: 1.10\nmetadata:\n  level: 3\nallowed-tools: [Read, Grep]\n",
)


def test_the_review_reads_an_upload_leniently_and_keeps_nothing(client, user_and_token, tmp_curio):
    user, token = user_and_token
    resp = _post(client, token, CHECK, _form({"SKILL.md": QUIRKY, "references/species.md": "Oak, elm."},
                                             folder="Street Trees Skill"))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    review = resp.get_json()
    assert review["name"] == NAME and review["givenName"] == NAME
    assert review["description"] == "Use this skill when: a dataflow counts street trees"
    said = " | ".join(review["warnings"])
    assert "colon" in said and "author, version" in said and "allowed-tools" in said and "'level'" in said, said
    # The folder it came in is renamed after the skill, so no warning speaks of it.
    assert "folder" not in said, said
    assert review["files"] == ["references/species.md"]
    assert review["problem"] is None and review["rename"] is False and review["replaces"] is False
    assert review["leftOut"] == []
    offered = {agent["coord"] for agent in review["agents"]}
    assert {DF, RS, "agent.curio.node-builder@1", "agent.curio.dataflow-builder@1"} <= offered
    assert not any(agent["coord"].startswith("agent.curio.dataflow-planner") for agent in review["agents"])
    assert _nothing_kept(user)


def test_an_imported_skill_is_kept_in_the_format_and_reaches_the_agents_the_review_picked(
    client, user_and_token, tmp_curio, scripted,
):
    user, token = user_and_token
    resp = _post(client, token, IMPORT, _form({"SKILL.md": QUIRKY, "references/species.md": "Oak, elm."},
                                              agents=[DF]))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["agents"] == ["Dataset Finder"] and body["replaced"] is False
    card = body["skill"]
    assert card["source"] == "yours" and card["removable"] is True and card["publishable"] is True
    assert card["published"] is False and card["files"] == ["references/species.md"]
    assert [(agent["coord"], agent["added"]) for agent in card["agents"]] == [(DF, True)]

    folder = _kept(user)
    kept = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert kept == skills.in_the_format(QUIRKY, name=NAME)[0]
    strict = skills.parse(folder)
    assert strict.description == "Use this skill when: a dataflow counts street trees"
    assert dict(strict.metadata) == {"level": "3", "author": "parks-team", "version": "1.10"}
    assert strict.allowed_tools == "Read Grep"
    assert (folder / "references" / "species.md").read_text(encoding="utf-8") == "Oak, elm."
    choices = agent_skill_store.default_store().read(_user_dir_key(user))
    assert choices["agent.curio.dataset-finder"].added == (NAME,)

    pid = _project(client, scripted)
    finder, researcher = _attach(client, scripted, pid, DF), _attach(client, scripted, pid, RS)
    testing_provider.push_reply("Hello.")
    testing_provider.push_reply("Hello.")
    _run(client, scripted, pid, finder)
    _run(client, scripted, pid, researcher)
    (finder_system, *_), (researcher_system, *_) = _run_calls()
    assert _listed(finder_system)[-1] == NAME
    assert NAME not in _listed(researcher_system)


#: Each break lenient mode lets through, the folder the upload comes in, and
#: what the review's warnings say of it (None: the import fixes it unasked).
LENIENT = {
    "a colon in a plain value": (_skill_md(description="Use this skill when: trees are counted"), NAME, "colon"),
    "fields the format does not define": (_skill_md(extra="tags: trees\nowner: parks\n"), NAME,
                                          "tags, owner, which the format does not define"),
    "metadata that is no text": (_skill_md(extra="metadata:\n  level: 3\n  reviewed: yes\n"), NAME,
                                 "where it holds strings by string keys"),
    "a list of allowed tools": (_skill_md(extra="allowed-tools:\n  - Read\n  - Grep\n"), NAME,
                                "allowed-tools is no string"),
    "Windows line ends and a byte order mark": ("﻿" + _skill_md().replace("\n", "\r\n"), NAME, None),
    "a folder named otherwise": (_skill_md(), "Elsewhere", None),
    "no name": (_skill_md(None), NAME, "it gives no name"),
    "600 lines": (_skill_md(body="## Street trees\n" + "Count trees by block.\n" * 600), NAME, "lines"),
}


@pytest.mark.parametrize("case", list(LENIENT), ids=list(LENIENT))
def test_a_lenient_import_keeps_what_the_format_refuses_in_the_format(client, user_and_token, tmp_curio, tmp_path,
                                                                     case):
    """Each break lenient mode lets through: the review warns of it, the
    import keeps the skill in the format, a run of the account holds it, and
    its export passes ``skills-ref``."""
    import skills_ref

    from utk_curio.backend.app.agents.application import skill_runs

    user, token = user_and_token
    text, folder, warned = LENIENT[case]
    review = _post(client, token, CHECK, _form({"SKILL.md": text}, folder=folder)).get_json()
    assert review["name"] == NAME and review["problem"] is None, review
    if warned is None:
        assert review["warnings"] == [], review
    else:
        assert any(warned in warning for warning in review["warnings"]), review
    assert _post(client, token, IMPORT, _form({"SKILL.md": text}, folder=folder)).status_code == 201
    strict = skills.parse(_kept(user), strict=False)
    assert strict.name == NAME and [w for w in strict.warnings if "lines" not in w] == []
    assert NAME in skill_runs.account_skills(_user_dir_key(user))
    exported = _exported(client, token, NAME, tmp_path)
    assert skills_ref.validate(exported) == []


def test_a_description_the_format_has_no_room_for_is_the_reviews_problem_and_refused(client, user_and_token,
                                                                                      tmp_curio):
    """A description over 1,024 characters reads leniently, with a warning,
    but the format has no room for it, so the review says why it cannot be
    kept, and the import refuses it."""
    user, token = user_and_token
    upload = {"SKILL.md": _skill_md(description="Use this skill when trees are counted. " + "a" * 1000)}
    review = _post(client, token, CHECK, _form(upload)).get_json()
    assert review["problem"] == "its description is 1,039 characters, more than 1,024", review
    assert review["rename"] is False
    resp = _post(client, token, IMPORT, _form(upload))
    assert resp.status_code == 400 and resp.get_json()["error"] == review["problem"], resp.get_json()
    assert _nothing_kept(user)


@pytest.mark.parametrize(("case", "form", "status", "said"), [
    ("no description", lambda: _form({"SKILL.md": "---\nname: street-trees\n---\nBody\n"}), 400, "no description"),
    ("frontmatter that is no mapping", lambda: _form({"SKILL.md": "---\n- one\n- two\n---\nBody\n"}), 400,
     "no YAML mapping"),
    ("no SKILL.md", lambda: _form({"README.md": "Trees."}), 400, "holds no SKILL.md"),
    ("two skills", lambda: _zip_form({"one/SKILL.md": _skill_md("one"), "two/SKILL.md": _skill_md("two")}), 400,
     "import one at a time"),
    ("a path that climbs out", lambda: _form({"SKILL.md": _skill_md(), "../escape.md": "x"}), 400, ".."),
    ("more files than an upload holds",
     lambda: _form({"SKILL.md": _skill_md(), **{f"references/{n}.md": "x" for n in range(64)}}), 413,
     "at most 64 skill files"),
])
def test_an_upload_the_import_cannot_keep_is_refused_and_nothing_is_kept(
    client, user_and_token, tmp_curio, case, form, status, said,
):
    user, token = user_and_token
    for url in (CHECK, IMPORT):
        resp = _post(client, token, url, form())
        assert resp.status_code == status, (url, resp.get_data(as_text=True))
        assert said in resp.get_json()["error"], (url, resp.get_json())
    assert _nothing_kept(user)


# --- The name ------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "status", "said"), [
    ("widgets", 409, "Curio ships a skill named widgets"),
    ("scout", 409, "the package curio.scout@1 ships a skill named scout"),
    ("Street Trees", 400, "is no skill's name"),
])
def test_a_taken_name_is_refused_naming_whose_it_is_and_another_name_keeps_the_skill(
    client, user_and_token, tmp_curio, name, status, said,
):
    user, token = user_and_token
    upload = {"SKILL.md": _skill_md(name), "references/species.md": "Oak."}
    review = _post(client, token, CHECK, _form(upload)).get_json()
    assert review["problem"].startswith(said) or said in review["problem"], review
    assert review["rename"] is True
    resp = _post(client, token, IMPORT, _form(upload))
    assert resp.status_code == status and said in resp.get_json()["error"], resp.get_json()

    # Renamed in the review: its folder and its name change together.
    review = _post(client, token, CHECK, _form(upload, name="my-trees")).get_json()
    assert review["name"] == "my-trees" and review["problem"] is None, review
    assert _post(client, token, IMPORT, _form(upload, name="my-trees")).status_code == 201
    kept = skills.parse(_kept(user, "my-trees"))
    assert kept.name == "my-trees" and kept.files == ("references/species.md",)


def test_a_skill_of_yours_is_replaced_only_by_a_newer_version(client, user_and_token, tmp_curio):
    user, token = user_and_token

    def upload(version: str) -> dict:
        return _form({"SKILL.md": _skill_md(extra=f"metadata:\n  version: \"{version}\"\n")}, agents=[DF])

    assert _post(client, token, IMPORT, upload("1.0.0")).status_code == 201
    same = _post(client, token, IMPORT, upload("1.0.0"))
    assert same.status_code == 409, same.get_json()
    assert same.get_json()["error"] == (f"you hold a skill named {NAME}, version 1.0.0: only a newer version "
                                        "of it replaces it")
    newer = _post(client, token, IMPORT, upload("1.2.0"))
    assert newer.status_code == 201 and newer.get_json()["replaced"] is True, newer.get_json()
    assert skills.parse(_kept(user)).metadata["version"] == "1.2.0"
    assert _post(client, token, IMPORT, upload("1.1.0")).status_code == 409
    assert NAME in _names(client.get(_rows_url(DF), headers=_auth(token)).get_json())


# --- How an upload comes ------------------------------------------------------------------


@pytest.mark.parametrize("how", ["a picked folder", "loose files", "a zip from macOS", "a zip of the files"])
def test_an_upload_is_a_folder_its_loose_files_or_a_zip(client, user_and_token, tmp_curio, how):
    user, token = user_and_token
    files = {"SKILL.md": _skill_md(), "references/species.md": "Oak, elm."}
    if how == "a picked folder":
        form = _form({**files, ".DS_Store": b"\x00\x01"})
    elif how == "loose files":
        form = _form(files, folder=None)
    elif how == "a zip from macOS":
        form = _zip_form({**{f"{NAME}/{path}": text for path, text in files.items()},
                          f"__MACOSX/{NAME}/._SKILL.md": b"\x00\x05", f"{NAME}/.DS_Store": b"\x00"})
    else:
        form = _zip_form(files)
    resp = _post(client, token, IMPORT, form)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert resp.get_json()["skill"]["files"] == ["references/species.md"]
    assert sorted(p.relative_to(_kept(user)).as_posix() for p in _kept(user).rglob("*") if p.is_file()) == [
        "SKILL.md", "references/species.md",
    ]


def test_files_outside_the_skills_folder_are_left_out_and_named(client, user_and_token, tmp_curio):
    user, token = user_and_token
    form = _zip_form({"repo/README.md": "A repository.", f"repo/skills/{NAME}/SKILL.md": _skill_md(),
                      f"repo/skills/{NAME}/references/species.md": "Oak."})
    review = _post(client, token, CHECK, form).get_json()
    assert review["leftOut"] == ["repo/README.md, which is outside the skill's folder"], review
    assert review["files"] == ["references/species.md"]


# --- Export ----------------------------------------------------------------------------


def test_every_skill_curio_ships_exports_to_a_folder_skills_ref_validates(client, user_and_token, tmp_curio,
                                                                           tmp_path):
    """The plan's promise: a skill leaving Curio passes ``skills-ref``. Curio's
    markers are filled, so the body is what an agent reads, and the
    frontmatter is the one Curio's strict reader takes."""
    import skills_ref

    _, token = user_and_token
    folders = skills.shipped_folders()
    assert len(folders) == 21
    for shipped in folders:
        name = shipped.name
        exported = _exported(client, token, name, tmp_path / name)
        assert skills_ref.validate(exported) == [], name
        text = (exported / "SKILL.md").read_text(encoding="utf-8")
        assert "{{" not in text, name
        ours = skills.parse(exported)
        assert ours.body.rstrip("\n") == agent_text.skill_text(name), name
        read = skills_ref.read_properties(exported)
        assert (read.name, read.description, read.license, read.compatibility, read.metadata) == (
            ours.name, ours.description, ours.license, ours.compatibility, dict(ours.metadata),
        ), name
        assert dict(skills.parse(shipped).metadata) == dict(ours.metadata), name


def test_an_imported_skill_exports_as_it_is_kept_and_the_same_every_time(client, user_and_token, tmp_curio,
                                                                          tmp_path):
    import skills_ref

    user, token = user_and_token
    assert _post(client, token, IMPORT, _form({"SKILL.md": QUIRKY, "references/species.md": "Oak, elm."})
                 ).status_code == 201
    exported = _exported(client, token, NAME, tmp_path)
    assert skills_ref.validate(exported) == []
    assert (exported / "SKILL.md").read_bytes() == (_kept(user) / "SKILL.md").read_bytes()
    assert (exported / "references" / "species.md").read_text(encoding="utf-8") == "Oak, elm."
    first = client.get(f"/api/agents/skills/{NAME}/export", headers=_auth(token)).get_data()
    assert client.get(f"/api/agents/skills/{NAME}/export", headers=_auth(token)).get_data() == first
    assert client.get("/api/agents/skills/no-such-skill/export", headers=_auth(token)).status_code == 404


# --- Remove ----------------------------------------------------------------------------


def test_removing_a_skill_takes_it_off_every_agent_so_a_later_one_of_its_name_joins_none(
    client, user_and_token, tmp_curio,
):
    user, token = user_and_token
    assert _post(client, token, IMPORT, _form({"SKILL.md": _skill_md()}, agents=[DF, RS])).status_code == 201
    resp = client.delete(f"/api/agents/skills/{NAME}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json() == {"name": NAME, "removed": True,
                               "agents": ["agent.curio.dataset-finder", "agent.curio.researcher"]}
    assert not _kept(user).exists()
    choices = agent_skill_store.default_store().read(_user_dir_key(user))
    assert all(NAME not in choice.added and NAME not in choice.removed for choice in choices.values())
    assert client.delete(f"/api/agents/skills/{NAME}", headers=_auth(token)).status_code == 404

    assert _post(client, token, IMPORT, _form({"SKILL.md": _skill_md()})).status_code == 201
    assert NAME not in _names(client.get(_rows_url(DF), headers=_auth(token)).get_json())
    assert _card(client, token)["agents"] == []


def test_a_skill_an_agent_always_holds_cannot_be_removed(client, user_and_token, tmp_curio):
    """An agent of the account whose chat instruction names the skill as its
    own holds it whatever its list is, so removing the skill is refused, as
    Remove on the agent refuses it."""
    user, token = user_and_token
    assert _post(client, token, IMPORT, _form({"SKILL.md": _skill_md()})).status_code == 201
    uploaded = client.post("/api/agents/imports/upload", json={
        "manifest": {
            "id": "agent.test.tree-counter", "name": "Tree Counter", "category": "canvas", "version": "1.0.0",
            "capabilities": [{"id": "chat.reply", "contractVersion": "1"}],
            "compatibleTargets": [{"kind": "canvas", "requires": []}],
            "prompts": {"instruction": {"path": "prompts/instruction.txt", "variables": [], "skills": [NAME]}},
            "provenance": {"publisher": "alice", "trust": "imported"},
        },
        "prompts": {"prompts/instruction.txt": "You count street trees."},
    }, headers=_auth(token))
    assert uploaded.status_code == 201, uploaded.get_data(as_text=True)
    resp = client.delete(f"/api/agents/skills/{NAME}", headers=_auth(token))
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == f"{NAME} is always held by the chat of Tree Counter, so it cannot be removed"
    assert _kept(user).is_dir()


# --- The format, as the import keeps it ------------------------------------------------------


@pytest.mark.parametrize(("value", "written"), [
    ("plain words", "plain words"),
    ("1.10", '"1.10"'),
    ("yes", '"yes"'),
    ("when: it rains", '"when: it rains"'),
    ("a --- b", '"a \\x2d-- b"'),
    ("two\nlines", '"two\\nlines"'),
    (" padded", '" padded"'),
])
def test_a_value_is_written_so_every_reader_takes_the_same_text(value, written, tmp_path):
    import skills_ref

    kept, _ = skills.in_the_format(_skill_md(extra=f"metadata:\n  note: {json.dumps(value)}\n"), name=NAME)
    assert f"  note: {written}\n" in kept
    folder = tmp_path / NAME
    folder.mkdir()
    (folder / "SKILL.md").write_text(kept, encoding="utf-8")
    assert skills.parse(folder).metadata["note"] == value
    assert skills_ref.read_properties(folder).metadata["note"] == value
    assert skills_ref.validate(folder) == []
