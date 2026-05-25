"""Tests for :mod:`utk_curio.backend.app.packages.dependency_scanner`."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.packages.dependency_scanner import (
    scan_imports_for_filename,
    scan_js_imports,
    scan_python_imports,
)


class TestScanPythonImports:
    def test_plain_import(self):
        assert scan_python_imports("import numpy\n") == ["numpy"]

    def test_from_import(self):
        assert scan_python_imports("from pandas import DataFrame\n") == ["pandas"]

    def test_aliased_import(self):
        assert scan_python_imports("import numpy as np\n") == ["numpy"]

    def test_dotted_module_keeps_top_level(self):
        assert scan_python_imports("import xml.etree.ElementTree\n") == []  # xml is stdlib
        assert scan_python_imports("import foo.bar.baz\n") == ["foo"]

    def test_multiple_imports_deduped_and_sorted(self):
        src = "import numpy\nimport pandas\nimport numpy as np2\nfrom rasterio import open\n"
        assert scan_python_imports(src) == ["numpy", "pandas", "rasterio"]

    def test_stdlib_filtered(self):
        src = "import os\nimport sys\nimport json\nimport numpy\n"
        assert scan_python_imports(src) == ["numpy"]

    def test_alias_map_applied(self):
        assert scan_python_imports("import cv2\n") == ["opencv-python"]
        assert scan_python_imports("import sklearn\nimport yaml\n") == [
            "pyyaml",
            "scikit-learn",
        ]
        assert scan_python_imports("from PIL import Image\n") == ["pillow"]

    def test_curio_provided_filtered(self):
        assert scan_python_imports("import curio\nimport utk_curio\n") == []

    def test_syntax_error_returns_empty(self):
        assert scan_python_imports("def broken(:\n    pass\n") == []

    def test_empty_source(self):
        assert scan_python_imports("") == []

    def test_relative_imports_skipped(self):
        # `from . import x` and `from .foo import y` are package-internal.
        src = "from . import sibling\nfrom .helpers import h\nimport numpy\n"
        assert scan_python_imports(src) == ["numpy"]


class TestScanJsImports:
    def test_bare_import(self):
        assert scan_js_imports('import x from "lodash";') == ["lodash"]

    def test_default_and_named(self):
        src = 'import React, { useState } from "react";'
        assert scan_js_imports(src) == ["react"]

    def test_dynamic_import(self):
        assert scan_js_imports('const x = await import("d3");') == ["d3"]

    def test_require(self):
        assert scan_js_imports("const fs = require('foo');") == ["foo"]

    def test_relative_paths_ignored(self):
        src = 'import x from "./local";\nimport y from "../sibling";\nimport z from "/abs";'
        assert scan_js_imports(src) == []

    def test_subpath_collapses_to_top_level(self):
        assert scan_js_imports('import x from "lodash/fp";') == ["lodash"]

    def test_scoped_package_keeps_scope(self):
        assert scan_js_imports('import x from "@scope/pkg";') == ["@scope/pkg"]
        assert scan_js_imports('import x from "@scope/pkg/subpath";') == ["@scope/pkg"]

    def test_mixed_quotes_and_forms(self):
        src = """
        import a from 'aa';
        import b from "bb";
        const c = require('cc');
        const d = await import("dd");
        """
        assert scan_js_imports(src) == ["aa", "bb", "cc", "dd"]


class TestScanImportsForFilename:
    def test_python_dispatch(self):
        py, js = scan_imports_for_filename("foo.py", "import numpy\n")
        assert py == ["numpy"]
        assert js == []

    def test_js_dispatch(self):
        py, js = scan_imports_for_filename("foo.js", 'import x from "lodash";')
        assert py == []
        assert js == ["lodash"]

    def test_unknown_extension_returns_empty(self):
        py, js = scan_imports_for_filename("foo.txt", "anything")
        assert py == []
        assert js == []
