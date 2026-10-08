"""The packages of the wheel, and the files ``build_py`` adds to it. The rest
of the build is in pyproject.toml, and MANIFEST.in says which files ship.

- Curio's code: ``utk_curio`` and every package in it.
- The folders the repository keeps beside ``utk_curio/`` (``datasets/``,
  ``discovery/``, ``models/``, ``packages/``, ``scripts/`` and ``vendor/``),
  and the files of ``docs/`` Curio reads, at ``utk_curio/_shipped/<folder>/``,
  where a pip install reads them (``utk_curio/shipped.py``). A pip install
  then puts nothing in site-packages but ``utk_curio/`` and its dist-info.
  The sdist keeps them where the repository has them.
- The repository's package.json and package-lock.json, at
  ``utk_curio/sandbox/nodejs/``, where a pip install's launcher reads them
  (SHIPPED_PACKAGE_FILES in utk_curio/sandbox/util/node_runtime.py).
"""

import shutil
from pathlib import Path

from setuptools import find_namespace_packages, setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
#: Where the package carries them, under the folder that holds utk_curio/.
TARGET = ("utk_curio", "sandbox", "nodejs")
PACKAGE_FILES = ("package.json", "package-lock.json")
#: The folders the repository keeps beside utk_curio/ (FOLDERS in
#: utk_curio/shipped.py), and the package that carries them in the wheel
#: (IN_THE_PACKAGE there).
SHIPPED_FOLDERS = ("datasets", "discovery", "docs", "models", "packages", "scripts", "vendor")
SHIPPED_PACKAGE = "utk_curio._shipped"
#: Folders of a shipped folder that hold Python Curio does not read: the
#: bring-your-own-model guide's worked example (docs/BRINGING-MODELS.md).
NOT_SHIPPED = {"docs": ["bring-your-own-model", "bring-your-own-model.*"]}


def packages_and_dirs(root=ROOT):
    """The packages of the wheel, and the folder of each that is not where its
    name says: each shipped folder under *root* is ``utk_curio._shipped.<folder>``,
    with the packages in it."""
    packages = find_namespace_packages(where=str(root), include=["utk_curio", "utk_curio.*"])
    package_dir = {}
    for folder in SHIPPED_FOLDERS:
        if not (Path(root) / folder).is_dir():
            continue
        name = f"{SHIPPED_PACKAGE}.{folder}"
        package_dir[name] = folder
        packages.append(name)
        inner_packages = find_namespace_packages(where=str(Path(root) / folder), exclude=NOT_SHIPPED.get(folder, ()))
        packages += [f"{name}.{inner}" for inner in inner_packages]
    return packages, package_dir


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
    packages, package_dir = packages_and_dirs()
    setup(cmdclass=cmdclass, packages=packages, package_dir=package_dir)
