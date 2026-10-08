"""The build step that ships the sandbox's Node.js package list in the pip package.

The repository root's package.json and package-lock.json name the Node.js
packages the sandbox runs (autk-db). A wheel holds only package folders, so the
build copies both into the package, at utk_curio/sandbox/nodejs/, where the
launcher reads them on a pip install (SHIPPED_PACKAGE_FILES in
utk_curio/sandbox/util/node_runtime.py). The sdist carries them at its root
(MANIFEST.in), so the wheel built from it gets them too.

Everything else about the build is in pyproject.toml.
"""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
#: Where the package carries them, under the folder that holds utk_curio/.
TARGET = ("utk_curio", "sandbox", "nodejs")
PACKAGE_FILES = ("package.json", "package-lock.json")


def ship_package_files(build_lib):
    """Copy the repository's package.json and package-lock.json into the
    package being built under *build_lib*. A missing one fails the build: a
    package without them cannot install the sandbox's Node.js packages."""
    target = Path(build_lib, *TARGET)
    target.mkdir(parents=True, exist_ok=True)
    for name in PACKAGE_FILES:
        shutil.copyfile(ROOT / name, target / name)


class BuildPyWithNodePackages(build_py):
    """``build_py``, then the sandbox's Node.js package list into the package."""

    def run(self):
        super().run()
        ship_package_files(self.build_lib)


cmdclass = {"build_py": BuildPyWithNodePackages}

if __name__ == "__main__":
    setup(cmdclass=cmdclass)
