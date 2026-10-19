"""The packages of the wheel, the files ``build_py`` adds to it, and the files
both archives leave out. The rest of the build is in pyproject.toml, and
MANIFEST.in says which files ship.

- Curio's code: ``utk_curio`` and every package in it.
- The folders the repository keeps beside ``utk_curio/`` (``datasets/``,
  ``discovery/``, ``packages/``, ``scripts/`` and ``vendor/``),
  and the files of ``docs/`` Curio reads, at ``utk_curio/_shipped/<folder>/``,
  where a pip install reads them (``utk_curio/shipped.py``). A pip install
  then puts nothing in site-packages but ``utk_curio/`` and its dist-info.
  The sdist keeps them where the repository has them.
- The repository's package.json and package-lock.json, at
  ``utk_curio/sandbox/nodejs/``, where a pip install's launcher reads them
  (SHIPPED_PACKAGE_FILES in utk_curio/sandbox/util/node_runtime.py).
- Not the files a dataset's or model package's manifest names in
  ``downloadOnFirstUse`` (``downloaded_on_first_use`` in utk_curio/shipped.py),
  which a pip install downloads from GitHub the first time Curio needs them:
  ``egg_info`` leaves them out of SOURCES.txt, the list of the files the sdist
  ships and the wheel takes its package data from.
"""

import importlib.util
import os
import shutil
from pathlib import Path

from setuptools import find_namespace_packages, setup
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info, manifest_maker

ROOT = Path(__file__).resolve().parent
#: Where the package carries them, under the folder that holds utk_curio/.
TARGET = ("utk_curio", "sandbox", "nodejs")
PACKAGE_FILES = ("package.json", "package-lock.json")
#: The folders the repository keeps beside utk_curio/ (FOLDERS in
#: utk_curio/shipped.py), and the package that carries them in the wheel
#: (IN_THE_PACKAGE there).
SHIPPED_FOLDERS = ("datasets", "discovery", "docs", "packages", "scripts", "vendor")
SHIPPED_PACKAGE = "utk_curio._shipped"


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
        packages += [f"{name}.{inner}" for inner in find_namespace_packages(where=str(Path(root) / folder))]
    return packages, package_dir


def ship_package_files(build_lib):
    """Copy the repository's package.json and package-lock.json into the
    package under *build_lib*; a missing one fails the build."""
    target = Path(build_lib, *TARGET)
    target.mkdir(parents=True, exist_ok=True)
    for name in PACKAGE_FILES:
        shutil.copyfile(ROOT / name, target / name)


def _shipped():
    """``utk_curio/shipped.py``, read by its path: the build imports nothing
    of the package it builds."""
    spec = importlib.util.spec_from_file_location("_curio_shipped", ROOT / "utk_curio" / "shipped.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def leave_out_first_use_files(filelist, root=ROOT):
    """Drop from *filelist*, setuptools' list of the files that ship, by their
    paths under *root*, each file the manifests under *root* name in
    ``downloadOnFirstUse``, and each file in a folder they name. A manifest
    that names a path outside its folder fails the build."""
    shipped = _shipped()
    left_out = shipped.downloaded_on_first_use(root)
    filelist.files = [name for name in filelist.files if not shipped.covers(left_out, name.replace(os.sep, "/"))]


class BuildPyWithNodePackages(build_py):
    """``build_py``, then the sandbox's Node.js package list into the package."""

    def run(self):
        super().run()
        ship_package_files(self.build_lib)


class ManifestWithoutFirstUseFiles(manifest_maker):
    """SOURCES.txt as setuptools makes it, without the files a pip install
    downloads on first use."""

    def prune_file_list(self):
        super().prune_file_list()
        leave_out_first_use_files(self.filelist)


class EggInfoWithoutFirstUseFiles(egg_info):
    """``egg_info``, writing SOURCES.txt with :class:`ManifestWithoutFirstUseFiles`."""

    def find_sources(self):
        maker = ManifestWithoutFirstUseFiles(self.distribution)
        maker.ignore_egg_info_dir = getattr(self, "ignore_egg_info_in_manifest", False)
        maker.manifest = os.path.join(self.egg_info, "SOURCES.txt")
        maker.run()
        self.filelist = maker.filelist


cmdclass = {"build_py": BuildPyWithNodePackages, "egg_info": EggInfoWithoutFirstUseFiles}

if __name__ == "__main__":
    packages, package_dir = packages_and_dirs()
    setup(cmdclass=cmdclass, packages=packages, package_dir=package_dir)
