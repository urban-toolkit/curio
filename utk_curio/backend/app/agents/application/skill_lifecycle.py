"""An account's own skills: import, export, publish, unpublish and remove them, through the agents' code.

A skill is an entry of the Agent Catalog as an agent is, and each action
runs the code an agent's runs:

- a hosted guest is refused every action but the export
  (``lifecycle.refuse_hosted_guest``);
- an upload is held to its limits (``upload_import.check_upload``, with
  ``upload_import.SKILL_UPLOAD``) and kept in one atomic write
  (``storage.write_folder_atomic``, through ``user_skills.write``), and a
  newer version replaces the account's own, an older or the same one does not
  (``manifest.version_order``);
- a publication follows the shared catalog's rules (``lifecycle.publish_entry``
  and ``lifecycle.unpublish_entry``): only the account's own may be
  published, and only its publisher may publish over it or unpublish it;
- a skill of the shared catalog given to an agent is copied into the
  account's skills first (``skill_catalog._copy_published``).

**Import.** An upload is a skill's folder, its loose files or a zip of it.
It is read as agentskills.io's guide for clients reads a skill authored
elsewhere: leniently (``skills.parse``), each break a warning the import
review shows. :func:`check_import` answers the review and keeps nothing;
:func:`import_skill` checks everything again, keeps the skill in the format
(``skills.in_the_format``) under its name, and gives it to the agents the
review picked (``skill_catalog.add_skill``).

**The name** is the skill's folder, so a skill is kept under a skill's name
that no other skill the account sees takes (:func:`_name_refusal`): not one
Curio ships, not one a package the account reaches ships, and not one the
account holds, unless the upload is a newer version of it. The review names
the skill that takes it, and another name, chosen in the review, renames the
skill, its folder and its ``name`` together.

**Export** (:func:`export_skill`) is a zip of the skill's folder,
``<name>/SKILL.md`` and its other files: a skill Curio ships with its markers
filled, any other as it is kept, so each passes agentskills.io's
``skills-ref``.

**Remove** (:func:`remove_own_skill`) deletes a skill the account holds and
takes it off every agent's list; a skill an agent's instruction or a
capability of it names as its own is refused, as Remove on an agent refuses
one.
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from utk_curio.backend.app.agents.application import catalog
from utk_curio.backend.app.agents.application import lifecycle
from utk_curio.backend.app.agents.application import skill_catalog
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.application.upload_import import SKILL_UPLOAD, check_upload
from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.domain.manifest import version_order
from utk_curio.backend.app.agents.infrastructure import agent_skills as agent_skill_store
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import user_skills
from utk_curio.backend.app.common import safe_archive
from utk_curio.backend.app.packages import service as packages_services

#: What an upload names its files: a skill's folder, its loose files, or a zip.
ZIP_SUFFIX = ".zip"
#: The first bytes of a zip archive.
_ZIP_MAGIC = b"PK\x03\x04"
#: Folders a zip made on macOS holds beside what was zipped.
_NOT_THE_SKILL = ("__MACOSX",)
#: How many members a zip may hold, against the files a skill may: a zip of
#: more than a skill's folder holds files the import leaves out.
_ZIP_MEMBERS = SKILL_UPLOAD.files * 4
#: The noun an upload's limits name its files by.
_FILES_NOUN = "skill files"


# --- Reading an upload -------------------------------------------------------------


@dataclass
class _Upload:
    """A skill's files as an upload holds them."""

    #: The folder the skill came in, when it came in one.
    folder: str | None
    #: Its ``SKILL.md`` and its other files, by their paths in its folder.
    files: dict[str, bytes]
    #: The files the upload holds outside the skill's folder, left out.
    outside: list[str] = field(default_factory=list)


def _is_zip(path: str, data: bytes) -> bool:
    return path.lower().endswith(ZIP_SUFFIX) or data.startswith(_ZIP_MAGIC)


def _zip_members(data: bytes) -> list[tuple[str, bytes]]:
    """The files of the zip *data*, by their paths in it, through the one
    extractor of every archive Curio opens (``common/safe_archive.py``): a
    name that climbs out, a link, an encrypted member and a zip past the
    limits are refused."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AgentServiceError(f"the zip cannot be read ({exc})", 400) from exc
    members = [info for info in archive.infolist() if not info.is_dir()]
    if len(members) > _ZIP_MEMBERS:
        raise AgentServiceError(f"the zip holds {len(members)} files, more than {_ZIP_MEMBERS}", 413)
    budget = safe_archive.Budget(safe_archive.Caps(
        max_member_bytes=SKILL_UPLOAD.file_bytes, max_total_bytes=SKILL_UPLOAD.total_bytes,
    ))
    found: list[tuple[str, bytes]] = []
    with archive, tempfile.TemporaryDirectory(prefix="curio-skill-zip-") as unpacked:
        for index, info in enumerate(members):
            try:
                segments = safe_archive.member_segments(info.filename)
            except safe_archive.ArchiveRefused as exc:
                raise AgentServiceError(str(exc), 400) from exc
            if _left_out(segments):
                continue
            if safe_archive.is_symlink(info) or safe_archive.is_encrypted(info):
                raise AgentServiceError(f"the zip's {info.filename!r} is a link or encrypted", 400)
            dest = Path(unpacked, str(index))
            try:
                safe_archive.copy_member(archive, info, dest, budget)
            except safe_archive.ArchiveRefused as exc:
                raise AgentServiceError(str(exc), 413) from exc
            found.append(("/".join(segments), dest.read_bytes()))
    return found


def _left_out(segments: tuple[str, ...]) -> bool:
    """Whether a file of an upload is none of the skill's: a hidden file, or
    one in a hidden folder or in a folder macOS adds to a zip. A skill's
    listing of its files leaves hidden ones out, so an import keeps none."""
    return segments[0] in _NOT_THE_SKILL or any(segment.startswith(".") for segment in segments)


def read_upload(parts: list[tuple[str, bytes]]) -> _Upload:
    """The skill an upload holds: *parts*, each a path and its bytes, from a
    picked folder, from loose files, or one zip. Its folder is the one that
    holds its ``SKILL.md``, the shallowest when there are more; files outside
    it are left out, and an upload of two skills is refused."""
    if not parts:
        raise AgentServiceError("pick a skill: its folder, its SKILL.md and its other files, or a zip of it", 400)
    entries = _zip_members(parts[0][1]) if len(parts) == 1 and _is_zip(*parts[0]) else list(parts)
    kept: list[tuple[str, bytes]] = []
    for raw, data in entries:
        try:
            segments = safe_archive.member_segments(raw)
        except safe_archive.ArchiveRefused as exc:
            raise AgentServiceError(str(exc).replace("archive member", "file"), 400) from exc
        if not _left_out(segments):
            kept.append(("/".join(segments), data))
    skill_files = [path for path, _ in kept if path.rsplit("/", 1)[-1] == skill_format.SKILL_FILE]
    if not skill_files:
        raise AgentServiceError(f"the upload holds no {skill_format.SKILL_FILE}", 400)
    depth = min(path.count("/") for path in skill_files)
    tops = sorted(path for path in skill_files if path.count("/") == depth)
    if len(tops) > 1:
        folders = ", ".join(path.rsplit("/", 1)[0] if "/" in path else "the top" for path in tops)
        raise AgentServiceError(f"the upload holds {len(tops)} skills ({folders}): import one at a time", 400)
    root = tops[0][: -len(skill_format.SKILL_FILE)]
    files = {path[len(root):]: data for path, data in kept if path.startswith(root)}
    check_upload(files, SKILL_UPLOAD, noun=_FILES_NOUN)
    return _Upload(
        folder=root.rstrip("/").rsplit("/", 1)[-1] or None,
        files=files,
        outside=[path for path, _ in kept if not path.startswith(root)],
    )


# --- The review ----------------------------------------------------------------------


@dataclass
class _Review:
    """What an import review shows of an upload, and what keeping it writes."""

    name: str
    given_name: str
    description: str
    warnings: list[str]
    left_out: list[str]
    files: list[str]
    #: Why it cannot be kept under :attr:`name`, or None.
    problem: str | None = None
    #: The status a refusal for :attr:`problem` answers with.
    status: int = 400
    #: The problem is its name: another name keeps it.
    rename: bool = False
    #: It replaces the account's own skill of that name, a newer version of it.
    replaces: bool = False
    #: Its ``SKILL.md`` as Curio keeps it, when it can be kept.
    kept: str | None = None
    #: Its other files, by their paths in its folder.
    others: dict[str, bytes] = field(default_factory=dict)


def _version(skill: skill_format.Skill) -> str | None:
    return skill.metadata.get(skill_catalog.VERSION_KEY)


def _name_refusal(user_key: str, name: str, version: str | None,
                  seen: skill_catalog.Seen) -> tuple[str | None, int, bool]:
    """Why an imported skill cannot be kept under *name*, with the status it
    answers with, and whether it replaces the account's own skill of that
    name: a newer *version* of it does. None when nothing takes the name."""
    if not skill_format.is_name(name):
        return (f"{name!r} is no skill's name: a name is 1 to {skill_format.NAME_MAX} lowercase letters, digits "
                "and single hyphens, with no hyphen first or last"), 400, False
    if name in seen.shipped:
        return f"Curio ships a skill named {name}", 409, False
    package = packages_services.package_skill_names(user_key).get(name)
    if package:
        return f"the package {package} ships a skill named {name}", 409, False
    held = seen.own.get(name)
    if held is None:
        return None, 200, False
    held_version = _version(held)
    if version and held_version and version_order(version) > version_order(held_version):
        return None, 200, True
    whose = ("a copy of the shared catalog's skill " if user_skills.is_copy(held.folder) else "a skill ")
    return (f"you hold {whose}named {name}"
            + (f", version {held_version}" if held_version else "")
            + ": only a newer version of it replaces it"), 409, False


def _review(user_key: str, parts: list[tuple[str, bytes]], name: str | None) -> _Review:
    """Read the upload *parts* as the review shows it, to be kept under
    *name*, or under the name its ``SKILL.md`` gives."""
    upload = read_upload(parts)
    try:
        text = upload.files[skill_format.SKILL_FILE].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentServiceError(f"{skill_format.SKILL_FILE} is not UTF-8 text", 400) from exc
    with tempfile.TemporaryDirectory(prefix="curio-skill-") as staging:
        skill = _staged(Path(staging), upload, text)
    chosen = name if isinstance(name, str) and name else skill.name
    where = f"{skill.folder.name}/{skill_format.SKILL_FILE}: "
    review = _Review(
        name=chosen, given_name=skill.name, description=skill.description,
        warnings=[warning.removeprefix(where) for warning in skill.warnings],
        left_out=[f"{path}, which is outside the skill's folder" for path in upload.outside],
        files=list(skill.files),
        others={path: data for path, data in upload.files.items() if path != skill_format.SKILL_FILE},
    )
    seen = skill_catalog.seen_skills(user_key)
    problem, status, replaces = _name_refusal(user_key, chosen, _version(skill), seen)
    if problem is not None:
        review.problem, review.status, review.rename = problem, status, True
        return review
    review.replaces = replaces
    try:
        review.kept, left_out = skill_format.in_the_format(text, name=chosen)
    except skill_format.SkillError as exc:
        review.problem = str(exc).removeprefix(f"{skill_format.SKILL_FILE}: ")
        return review
    review.left_out[:0] = left_out
    return review


def _staged(staging: Path, upload: _Upload, text: str) -> skill_format.Skill:
    """The upload read leniently from a folder of *staging*: named as the
    folder it came in, then as the skill it holds when that is a skill's
    name, so a warning about its folder speaks of a name Curio would keep."""
    folder = staging / (upload.folder or "skill")
    for path, data in upload.files.items():
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    try:
        skill = skill_format.parse(folder, strict=False, text=text)
        if skill_format.is_name(skill.name) and skill.name != folder.name:
            folder = folder.rename(staging / skill.name) if not (staging / skill.name).exists() else folder
            skill = skill_format.parse(folder, strict=False, text=text)
    except skill_format.SkillError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    return skill


def _offered_agents(user_key: str) -> list[dict]:
    """The agents an import review offers the skill to: those whose skills
    the account may change, by name, each once."""
    choosable = [row["id"] for row in catalog.choosable_agents(user_key)]
    coords: dict[str, tuple[str, str]] = {}
    for m in skill_catalog._agents(user_key):
        coords.setdefault(m.agent_id, (m.dir_name, m.name))
    return [{"id": agent_id, "coord": coords[agent_id][0], "name": coords[agent_id][1]}
            for agent_id in choosable if agent_id in coords]


def check_import(user, user_key: str, parts: list[tuple[str, bytes]], *, name: str | None = None) -> dict:
    """What the import review shows of the upload *parts*, kept under *name*
    or the name its ``SKILL.md`` gives: the skill as lenient mode reads it,
    what does not follow the format, what keeping it leaves out, why it
    cannot be kept (``problem``, with ``rename`` when another name keeps it,
    and ``replaces`` when it replaces the account's own, older one), and the
    agents it may be given. Nothing is kept."""
    lifecycle.refuse_hosted_guest(user, "import skills")
    review = _review(user_key, parts, name)
    return {
        "name": review.name,
        "givenName": review.given_name,
        "description": review.description,
        "warnings": review.warnings,
        "leftOut": review.left_out,
        "files": review.files,
        "problem": review.problem,
        "rename": review.rename,
        "replaces": review.replaces,
        "agents": _offered_agents(user_key),
    }


def import_skill(user, user_key: str, parts: list[tuple[str, bytes]], *, name: str | None = None,
                 agents=()) -> dict:
    """Keep the upload *parts* as the account's skill *name*, or the name its
    ``SKILL.md`` gives, and give it to the agents at the coordinates
    *agents*: everything :func:`check_import` checks is checked again, and
    each agent before anything is kept. Answers the skill's card and the
    agents that were given it."""
    lifecycle.refuse_hosted_guest(user, "import skills")
    if not isinstance(agents, (list, tuple)):
        raise AgentServiceError("'agents' must list agents' coordinates", 400)
    review = _review(user_key, parts, name)
    if review.problem is not None:
        raise AgentServiceError(review.problem, review.status)
    picked = [skill_catalog.changeable_agent(user_key, coord) for coord in dict.fromkeys(agents)]
    files = {skill_format.SKILL_FILE: review.kept or "", **review.others}
    try:
        user_skills.write(user_key, review.name, files, replace=review.replaces)
    except FileExistsError as exc:
        raise AgentServiceError(
            f"{review.name} was kept by another import at the same time; import it again", 409,
        ) from exc
    for m in picked:
        skill_catalog.add_skill(user_key, m.dir_name, review.name)
    card = next(card for card in skill_catalog.skills_listing(user_key) if card["name"] == review.name)
    return {"skill": card, "agents": [m.name for m in picked], "replaced": review.replaces}


# --- Export ----------------------------------------------------------------------------


#: The date every member of an export carries, so an export of the same
#: skill is the same file.
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _filled(skill: skill_format.Skill) -> str:
    """The ``SKILL.md`` of a skill Curio ships with its markers filled: its
    frontmatter as written, then its body as an agent reads it
    (``agent_text.skill_text``)."""
    text = skill.file.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    head = "\n".join(text.split("\n")[: skill.body_line - 1])
    return head + "\n" + agent_text.skill_text(skill.name) + "\n"


def export_skill(user_key: str | None, name: str) -> tuple[str, bytes]:
    """The skill *name* the account sees, as ``(<name>.zip, its bytes)``: a
    zip of its folder, ``<name>/SKILL.md`` and its other files. A skill Curio
    ships carries its markers filled (:func:`_filled`); any other is as it is
    kept. Every member carries one date, so the same skill exports to the
    same bytes."""
    seen = skill_catalog.seen_skills(user_key)
    skill = seen.find(name)
    if skill is None:
        raise AgentServiceError(f"Curio ships no skill named {name}, and you see none by that name", 404)
    files = user_skills.read_files(skill.folder)
    if skill.name in seen.shipped:
        files[skill_format.SKILL_FILE] = _filled(skill).encode("utf-8")
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{skill.name}/{path}", date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[path])
    return f"{skill.name}{ZIP_SUFFIX}", sink.getvalue()


# --- Publish, unpublish, remove ----------------------------------------------------------


def publish_skill(user, user_key: str, name: object) -> dict:
    """Publish the account's own skill *name* to the shared catalog, where
    every account on this Curio sees it: only a skill it imported, never
    Curio's, a package's or its copy of the shared catalog's, as only an
    agent it imported may be published (``lifecycle.publish_agent``)."""
    lifecycle.refuse_hosted_guest(user, "publish skills")
    if not (isinstance(name, str) and user_skills.holds(user_key, name)) or user_skills.is_copy(
            user_skills.skill_dir(user_key, name)):
        raise AgentServiceError(
            "only a skill you imported can be published; Curio's skills, packages' skills and copies of "
            "the shared catalog's cannot", 400,
        )
    lifecycle.publish_entry(publications.SKILLS, user_key, name, user_skills.skill_dir(user_key, name))
    return {"name": name, "published": True}


def unpublish_skill(user, user_key: str, name: str) -> dict:
    """Take the skill *name* out of the shared catalog: only its publisher
    may (``lifecycle.unpublish_entry``). An account that added it keeps its
    copy."""
    lifecycle.refuse_hosted_guest(user, "unpublish skills")
    if not skill_format.is_name(name):
        raise AgentServiceError(f"{name!r} names no skill", 404)
    lifecycle.unpublish_entry(publications.SKILLS, user_key, name)
    return {"name": name, "published": False}


def remove_own_skill(user, user_key: str, name: str) -> dict:
    """Delete the account's skill *name*, its own or its copy of the shared
    catalog's, and take it off every agent's list (``agent_skills.forget``).
    A skill an agent holds whatever its skills are (its instruction, a mode
    or another agent's ask names it as its own) is refused and kept. A
    publication of it stays in the shared catalog until its publisher
    unpublishes it."""
    lifecycle.refuse_hosted_guest(user, "remove skills")
    if not user_skills.holds(user_key, name):
        raise AgentServiceError(f"you hold no skill named {name}", 404)
    seen = skill_catalog.seen_skills(user_key)
    for m in skill_catalog._agents(user_key):
        always = skill_catalog.why_always(skill_catalog.held_by(user_key, m, seen), name, m.name)
        if always:
            raise AgentServiceError(always, 400)
    try:
        agents = agent_skill_store.default_store().forget(user_key, name)
    except agent_skill_store.AgentSkillsError as exc:
        raise AgentServiceError(str(exc), exc.status) from exc
    user_skills.remove(user_key, name)
    return {"name": name, "removed": True, "agents": agents}
