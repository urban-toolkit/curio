"""JS bare-specifier resolution for the Node subprocess.

``resolve_pkg_entry_url`` is what lets a JS node write ``import x from "pkg"``:
the import rewriter turns the bare specifier into an absolute ``file://`` URL
under the repo-root ``node_modules``. That rewrite is not a nicety - Node's ESM
resolver ignores ``NODE_PATH`` and resolves a bare specifier by walking
``node_modules`` up from the importing module, which fails whenever the
subprocess cwd sits outside the repo (``CURIO_LAUNCH_CWD`` /
``CURIO_TEST_WORKSPACE``).

The regression these tests exist for: package.json export conditions NEST, so
``exports["."]["import"]`` is often another condition object rather than a path.
Reading one level deep and handing a dict to pathlib raised TypeError, which was
swallowed as "unresolvable" - degrading to the bare specifier and making JS
imports silently cwd-dependent. ``test_nested_export_conditions_resolve`` is the
guard.

Run:  pytest utk_curio/sandbox/tests/test_js_module_resolution.py -v
"""

import json
import pathlib
import shutil
import tempfile
import unittest

from utk_curio.sandbox.app.worker import (
    _pick_export_entry,
    execute_js_code,
    resolve_pkg_entry_url,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ROOT_NODE_MODULES = _REPO_ROOT / 'node_modules'

_SKIP_NO_NODE = unittest.skipIf(
    shutil.which('node') is None,
    "Node.js is not installed - skipping JS execution tests",
)


def _skip_unless_installed(test, pkg, rel_entry):
    """Skip when a hoisted transitive dep isn't present.

    Neither package is a direct dependency of the root package.json - both
    arrive hoisted under @urban-toolkit/autk-db. Absence is an npm-layout fact,
    not a Curio bug, so skip rather than fail.
    """
    entry = _ROOT_NODE_MODULES / pkg / rel_entry
    if not entry.is_file():
        test.skipTest(
            f"{entry} is absent - '{pkg}' is a hoisted transitive dep. Run "
            f"`npm install` at the repo root, or repoint this test at another "
            f"zero-dep package in root node_modules."
        )
    return entry


class TestPickExportEntry(unittest.TestCase):
    """The pure condition walker, independent of the filesystem."""

    def test_plain_string(self):
        self.assertEqual(_pick_export_entry('./index.js'), './index.js')

    def test_flat_condition_map(self):
        node = {'import': './esm.mjs', 'require': './cjs.js'}
        self.assertEqual(_pick_export_entry(node), './esm.mjs')

    def test_nested_condition_map(self):
        # bignumber.js's real shape: the value of "import" is itself a
        # condition object whose "default" holds the path.
        node = {
            'import': {'types': './bignumber.d.mts', 'default': './bignumber.mjs'},
            'require': {'types': './bignumber.d.ts', 'default': './bignumber.js'},
        }
        self.assertEqual(_pick_export_entry(node), './bignumber.mjs')

    def test_esm_conditions_win_over_require(self):
        node = {'require': './cjs.js', 'module': './esm.mjs'}
        self.assertEqual(_pick_export_entry(node), './esm.mjs')

    def test_types_only_branch_is_skipped(self):
        # "types" is not a runtime condition; a branch offering only types must
        # not win, or we would import a .d.ts.
        node = {'import': {'types': './only.d.ts'}, 'default': './real.js'}
        self.assertEqual(_pick_export_entry(node), './real.js')

    def test_unresolvable_shapes_return_none(self):
        for node in (None, 42, [], {}, {'types': './x.d.ts'}):
            with self.subTest(node=node):
                self.assertIsNone(_pick_export_entry(node))


class TestResolvePkgEntryUrl(unittest.TestCase):
    """Filesystem-backed resolution against the real root node_modules."""

    def test_flat_string_exports_resolve(self):
        entry = _skip_unless_installed(self, 'quickselect', 'index.js')
        url = resolve_pkg_entry_url('quickselect', _ROOT_NODE_MODULES)
        self.assertEqual(url, entry.resolve().as_uri())

    def test_nested_export_conditions_resolve(self):
        """The regression guard. Fails before the nested-condition fix."""
        entry = _skip_unless_installed(self, 'bignumber.js', 'bignumber.mjs')
        url = resolve_pkg_entry_url('bignumber.js', _ROOT_NODE_MODULES)
        self.assertEqual(
            url, entry.resolve().as_uri(),
            msg="nested exports['.']['import'] must resolve to a file URL, not "
                "fall through to the bare specifier",
        )

    def test_scoped_package_keeps_both_segments(self):
        pkg_json = _ROOT_NODE_MODULES / '@urban-toolkit' / 'autk-db' / 'package.json'
        if not pkg_json.is_file():
            self.skipTest(f"{pkg_json} is absent - run `npm install` at the repo root")
        url = resolve_pkg_entry_url('@urban-toolkit/autk-db', _ROOT_NODE_MODULES)
        self.assertIsNotNone(url)
        self.assertIn('/autk-db/', url)

    def test_subpath_specifier_resolves_the_package_root(self):
        # Only the top-level specifier is rewritten; the package's own internal
        # imports still resolve relative to its installed location.
        _skip_unless_installed(self, 'quickselect', 'index.js')
        self.assertEqual(
            resolve_pkg_entry_url('quickselect/whatever', _ROOT_NODE_MODULES),
            resolve_pkg_entry_url('quickselect', _ROOT_NODE_MODULES),
        )

    def test_non_bare_specifiers_are_rejected(self):
        for spec in ('', './local.js', '../up.js', '/abs.js',
                     'node:fs', 'https://cdn.example/x.js'):
            with self.subTest(spec=spec):
                self.assertIsNone(resolve_pkg_entry_url(spec, _ROOT_NODE_MODULES))

    def test_uninstalled_package_returns_none(self):
        self.assertIsNone(
            resolve_pkg_entry_url('zzz-not-a-real-package-qq', _ROOT_NODE_MODULES)
        )


class TestResolvePkgEntryUrlSynthetic(unittest.TestCase):
    """Cases that need a package.json we control."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / 'node_modules'
        self.root.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_pkg(self, name, meta, files=('index.js',)):
        pkg_dir = self.root / name
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / 'package.json').write_text(json.dumps(meta), encoding='utf-8')
        for rel in files:
            target = pkg_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('export default 1;\n', encoding='utf-8')
        return pkg_dir

    def test_falls_back_to_module_then_main_then_index(self):
        self._write_pkg('only-main', {'main': 'lib/entry.js'},
                        files=('lib/entry.js',))
        url = resolve_pkg_entry_url('only-main', self.root)
        self.assertTrue(url.endswith('/lib/entry.js'), url)

        self._write_pkg('module-wins', {'main': 'cjs.js', 'module': 'esm.mjs'},
                        files=('cjs.js', 'esm.mjs'))
        url = resolve_pkg_entry_url('module-wins', self.root)
        self.assertTrue(url.endswith('/esm.mjs'), url)

        self._write_pkg('bare', {})
        url = resolve_pkg_entry_url('bare', self.root)
        self.assertTrue(url.endswith('/index.js'), url)

    def test_entry_escaping_node_modules_is_refused(self):
        outside = pathlib.Path(self._tmp.name) / 'outside.js'
        outside.write_text('export default 1;\n', encoding='utf-8')
        self._write_pkg('escaper', {'exports': '../../outside.js'})
        self.assertIsNone(resolve_pkg_entry_url('escaper', self.root))

    def test_missing_entry_file_returns_none(self):
        self._write_pkg('ghost', {'exports': './nope.mjs'})
        self.assertIsNone(resolve_pkg_entry_url('ghost', self.root))

    def test_malformed_package_json_returns_none(self):
        pkg_dir = self.root / 'broken'
        pkg_dir.mkdir(parents=True)
        (pkg_dir / 'package.json').write_text('{not json', encoding='utf-8')
        self.assertIsNone(resolve_pkg_entry_url('broken', self.root))

    def test_condition_map_without_dot_key_applies_to_the_root(self):
        # web-worker's shape: a bare condition map with no "." subpath.
        self._write_pkg(
            'no-dot',
            {'exports': {'import': {'default': './esm.mjs'}, 'require': './cjs.js'}},
            files=('esm.mjs', 'cjs.js'),
        )
        url = resolve_pkg_entry_url('no-dot', self.root)
        self.assertTrue(url.endswith('/esm.mjs'), url)

    def test_dict_entry_that_never_resolves_falls_back_to_main(self):
        self._write_pkg(
            'types-only',
            {'exports': {'.': {'import': {'types': './x.d.ts'}}}, 'main': 'fallback.js'},
            files=('fallback.js',),
        )
        url = resolve_pkg_entry_url('types-only', self.root)
        self.assertTrue(url.endswith('/fallback.js'), url)


class TestJsImportIsCwdIndependent(unittest.TestCase):
    """End-to-end guard for the reason the rewrite exists at all.

    A bare specifier that falls through unrewritten still *works* when the Node
    subprocess cwd is inside the repo, because Node then walks up into the
    repo-root node_modules. Running from a directory outside the repo is the
    only way to prove the absolute-file-URL rewrite actually happened, which is
    what makes this the regression guard for CURIO_LAUNCH_CWD /
    CURIO_TEST_WORKSPACE pointing elsewhere.
    """

    @_SKIP_NO_NODE
    def test_bare_specifier_resolves_from_a_cwd_outside_the_repo(self):
        entry = _ROOT_NODE_MODULES / 'quickselect' / 'index.js'
        if not entry.is_file():
            self.skipTest(
                f"{entry} is absent - 'quickselect' is a hoisted transitive dep "
                f"(autk-db -> rbush -> quickselect). Run `npm install` at the repo root."
            )
        code = (
            'import quickselect from "quickselect"\n'
            'const a = [5, 1, 4, 2, 3];\n'
            'quickselect(a, 2);\n'
            'return a[2];'
        )
        with tempfile.TemporaryDirectory() as outside:
            result = execute_js_code(
                code, '', 'JS_COMPUTATION', '',
                launch_dir=outside, session_id=None, save_dataset=False,
            )
        self.assertEqual(result['stderr'], '', msg=result.get('stderr'))
        self.assertNotEqual(
            result['output']['path'], '',
            msg="bare specifier failed to resolve from outside the repo - the "
                "import rewriter did not produce an absolute file:// URL",
        )


if __name__ == '__main__':
    unittest.main()
