"""Copies the repository's package.json and package-lock.json into the wheel,
at utk_curio/sandbox/nodejs/, where a pip install's launcher reads them
(SHIPPED_PACKAGE_FILES in utk_curio/sandbox/util/node_runtime.py).

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
    package under *build_lib*; a missing one fails the build."""
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
