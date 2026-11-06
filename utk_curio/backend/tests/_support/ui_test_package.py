"""``test.ui-node@1``: the test package whose node draws its own interface.

Made with ``python scripts/new_package.py test.ui-node --with-ui``, its bundle
built by ``npm run build:packages`` (``webpack/packageEntries.js`` reads the
test packages too). It declares no Python libraries, so adding it never runs
pip: it is the package a test adds when any package will do, and the one a
test of a node with its own interface uses.

It is not in the shipped catalog. A test that adds it puts it in the catalog
its backend reads for that test and takes it out after: the e2e tests through
``/api/testing/catalog-package`` (``test_frontend/utils/offline_install.py``),
a backend test with :func:`ui_test_package_in`.
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

#: The package's folder, ``<id>@<major>``.
UI_TEST_PACKAGE = "test.ui-node@1"
UI_TEST_PACKAGE_ID = "test.ui-node"
#: Its name, the manifest's ``name``, which the Node Catalog's cards and dialogs show.
UI_TEST_PACKAGE_NAME = "UI Node"
#: Its one node: ``<package id>/<template id>``, and the template's label.
UI_TEST_NODE_TYPE = "test.ui-node/ui-node"
UI_TEST_NODE_LABEL = "UI Node"
#: The global its bundle sets once it has run, which is when it registers the
#: node's behavior: the UMD name ``webpack.packages.config.js`` gives it.
UI_TEST_BUNDLE_GLOBAL = "test_ui-node_1"
#: What the node draws before a frame reaches it. Only the package's own hook
#: draws it: the generic package hook draws nothing in a node with no editor.
UI_TEST_NODE_WAITING = "Connect a DataFrame upstream and run it."
#: The button that keeps the chosen column as the node's output.
UI_TEST_NODE_SEND = "Send this column downstream"

#: The package as the repository holds it.
UI_TEST_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "test_frontend" / "packages" / UI_TEST_PACKAGE


@contextmanager
def ui_test_package_in(catalog: Path) -> Iterator[Path]:
    """The package copied into the package catalog *catalog*, removed after."""
    target = Path(catalog) / UI_TEST_PACKAGE
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(UI_TEST_PACKAGE_DIR, target)
    try:
        yield target
    finally:
        shutil.rmtree(target, ignore_errors=True)
