"""A plain ``npm run build`` records its mode, as a build by the launcher does.

The launcher reuses ``dist/`` only when ``dist/.curio-build`` names the mode
of package.json's build script (``frontend_build._build_stamp_reason``). It
wrote that file only after a build it ran itself, and the Dockerfile writes it
after its own. The PyPI release runs ``npm run build`` and wrote none, so a
pip install read its ``dist/`` as "built in an unrecorded mode" and every
``curio start`` ran ``npm install`` and the whole build inside site-packages,
or stopped with "npm not found in PATH" where Node is not installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from utk_curio.cli import frontend_build

FRONTEND = Path(frontend_build.__file__).resolve().parents[1] / "frontend" / "urban-workflows"
PACKAGE_JSON = FRONTEND / "package.json"

#: The Autark data compiler a build writes beside the page
#: (``common/autk_data_compiler.COMPILER_NAME``).
COMPILER_NAME = "autk-data-compile.cjs"


def _postbuild() -> str:
    return json.loads(PACKAGE_JSON.read_text(encoding="utf-8")).get("scripts", {}).get("postbuild", "")


def _built_frontend(root: Path) -> Path:
    """*root* as a release has it once webpack is done: Curio's package.json,
    the stamp writer and a dist/ with no stamp."""
    shutil.copy(PACKAGE_JSON, root / "package.json")
    (root / "scripts").mkdir()
    for script in (FRONTEND / "scripts").iterdir():
        shutil.copy(script, root / "scripts" / script.name)
    (root / "dist").mkdir()
    (root / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "dist" / COMPILER_NAME).write_text("the Autark data compiler", encoding="utf-8")
    return root


def test_npm_runs_a_step_after_every_build():
    assert _postbuild().startswith("node scripts/"), (
        "package.json has no postbuild script, so `npm run build` alone leaves "
        "dist/ with no record of its mode"
    )


def test_the_step_after_the_build_makes_dist_one_the_launcher_reuses(tmp_path):
    root = _built_frontend(tmp_path)
    assert frontend_build._build_stamp_reason(str(root)) == "built in an unrecorded mode, need production"
    command = _postbuild().split()
    assert command[:1] == ["node"], f"postbuild is {_postbuild()!r}"

    # npm runs a package's scripts from the package's folder.
    subprocess.run(command, cwd=root, check=True, timeout=60)

    assert frontend_build._build_stamp_reason(str(root)) is None
    assert (root / "dist" / frontend_build.BUILD_STAMP).read_text(encoding="utf-8") == (
        f"{frontend_build._frontend_build_mode(str(root))}\n"
    )
