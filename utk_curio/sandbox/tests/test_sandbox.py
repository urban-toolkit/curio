import shutil
import unittest
import tempfile
import os
import sys
import json
from utk_curio.sandbox.app import app
from flask import Flask, jsonify

# Modify sys.path to include the sandbox folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'sandbox')))

_SKIP_NO_NODE = unittest.skipIf(
    shutil.which('node') is None,
    "Node.js is not installed — skipping JS execution tests",
)

# Repo root holds the node_modules the sandbox's `node` subprocess resolves
# @urban-toolkit/autk-db from (installed by _ensure_root_node_modules in main.py).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
_AUTK_DB_AVAILABLE = os.path.isdir(
    os.path.join(_REPO_ROOT, 'node_modules', '@urban-toolkit', 'autk-db')
)
_SKIP_NO_AUTK_DB = unittest.skipUnless(
    _AUTK_DB_AVAILABLE,
    "@urban-toolkit/autk-db not installed at the repo root — run 'npm install' there",
)


# The contract check compileDataSpecToAutkDbJs() now emits after its load loop
# (#248). Kept as a literal mirror, like the data-section test above: the Jest
# suite covers the host-side decision, but only running it in the real Node
# subprocess proves the GENERATED code parses and behaves there.
_CONTRACT_CHECK_JS = (
    "import * as __autkDbMod from '@urban-toolkit/autk-db';\n"
    "const AutkDb = __autkDbMod.AutkDb || __autkDbMod.AutkSpatialDb;\n"
    "const __sources = [{{ type: 'geojson', geojsonObject: {{ type: 'FeatureCollection', "
    "features: [{{ type: 'Feature', geometry: {{ type: 'Point', coordinates: [-87.63, 41.88] }}, "
    "properties: {{ name: 'a' }} }}] }}, outputTableName: 'probe_pts' }}];\n"
    "const __expectedTables = ['probe_pts', 'probe_missing'];\n"
    "const __loadErrors = {load_errors};\n"
    "const db = new AutkDb();\n"
    "await db.init();\n"
    "for (const source of __sources) {{ const {{ type, ...rest }} = source; "
    "if (type === 'geojson') await db.loadGeojson(rest); }}\n"
    "let __tables = [];\n"
    "try {{ __tables = db.getLayerTables ? db.getLayerTables() : []; }}\n"
    "catch (e) {{ __loadErrors.push('getLayerTables: ' + ((e && e.message) || String(e))); }}\n"
    "const __have = new Set(__tables.map((t) => t.name));\n"
    "const __missing = __expectedTables.filter((n) => !__have.has(n));\n"
    "if (__missing.length > 0) {{\n"
    "  const __detail = 'missing: ' + __missing.join(', ')\n"
    "    + (__loadErrors.length > 0 ? ' (' + __loadErrors.join('; ') + ')' : '');\n"
    "  if (__loadErrors.length > 0) {{\n"
    "    throw new Error('autk data load produced ' + __missing.length\n"
    "      + ' fewer table(s) than the spec asked for - ' + __detail);\n"
    "  }}\n"
    "  console.log('[autk-grammar] ' + __detail\n"
    "    + ' - no load error recorded, treating as a genuinely empty query area');\n"
    "}}\n"
    "const __out = [];\n"
    "for (const t of __tables) {{ const geojson = await db.getLayer(t.name); "
    "__out.push({{ name: t.name, type: t.type ?? 'polygons', geojson }}); }}\n"
    "return __out;"
)


class TestSandbox(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_live(self):
        response = self.client.get('/live')
        self.assertEqual(response.data.decode('utf-8'), 'Sandbox is live.')
        self.assertEqual(response.status_code, 200)

    @_SKIP_NO_NODE
    def test_exec_js_returns_scalar(self):
        """POST /execJs with a scalar return value."""
        response = self.client.post('/execJs', json={
            'code': 'return 42;',
            'file_path': '',
            'nodeType': 'JS_COMPUTATION',
            'dataType': '',
            'session_id': None,
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('output', data)
        self.assertIn('stdout', data)
        self.assertIn('stderr', data)
        self.assertEqual(data['stderr'], '')
        self.assertNotEqual(data['output']['path'], '')

    @_SKIP_NO_NODE
    def test_exec_js_console_log_captured(self):
        """console.log output appears in stdout."""
        response = self.client.post('/execJs', json={
            'code': 'console.log("hello"); return 1;',
            'file_path': '',
            'nodeType': 'JS_COMPUTATION',
            'dataType': '',
            'session_id': None,
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('hello', data['stdout'])

    @_SKIP_NO_NODE
    def test_exec_js_syntax_error_returned_in_stderr(self):
        """A JS syntax/runtime error is returned in stderr, not as a 500."""
        response = self.client.post('/execJs', json={
            'code': 'throw new Error("oops");',
            'file_path': '',
            'nodeType': 'JS_COMPUTATION',
            'dataType': '',
            'session_id': None,
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('oops', data['stderr'])
        self.assertEqual(data['output']['path'], '')

    @_SKIP_NO_NODE
    def test_execute_js_code_direct(self):
        """Unit-test execute_js_code() directly."""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        _worker_init()
        result = execute_js_code('return arg * 2;', '', 'JS_COMPUTATION', '', session_id=None)
        self.assertIn('output', result)
        self.assertEqual(result['stderr'], '')

    @_SKIP_NO_NODE
    def test_exec_js_result_stored_in_duckdb(self):
        """JS result is retrievable from Python DuckDB via the returned artifact ID."""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import load_from_duckdb
        _worker_init()
        result = execute_js_code('return 42;', '', 'JS_COMPUTATION', '', session_id=None)
        self.assertEqual(result['stderr'], '')
        artifact_id = result['output']['path']
        self.assertNotEqual(artifact_id, '')
        value = load_from_duckdb(artifact_id, session_id=None)
        self.assertEqual(value, 42)

    @_SKIP_NO_NODE
    def test_exec_js_receives_input_from_duckdb(self):
        """JS code receives Python-DuckDB-stored input via the arg parameter."""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        artifact_id = save_to_duckdb(10, node_id='JS_COMPUTATION', session_id=None)
        result = execute_js_code('return arg + 1;', artifact_id, 'JS_COMPUTATION', 'int', session_id=None)
        self.assertEqual(result['stderr'], '')
        value = load_from_duckdb(result['output']['path'], session_id=None)
        self.assertEqual(value, 11)


    @_SKIP_NO_NODE
    @_SKIP_NO_AUTK_DB
    def test_exec_js_autk_grammar_data_section(self):
        """The Autark grammar's data section runs server-side via autk-db.

        Mirrors what compileDataSpecToAutkDbJs() emits in the frontend: a tiny
        inline-geojson `data` section compiled to an autk-db loader. Exercises
        the full server-side path — module resolution, the import rewriter, the
        js_wrapper, the Node subprocess, and the DuckDB round-trip — without any
        network or PBF dependency. The result is the layer array the render path
        injects back into the grammar.
        """
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import load_from_duckdb
        _worker_init()

        code = (
            "import * as __autkDbMod from '@urban-toolkit/autk-db';\n"
            # Mirror compileDataSpecToAutkDbJs: the v2.0 frontend build exports
            # AutkDb, but the older root-level install the sandbox resolves
            # exports AutkSpatialDb. Accept either so the snippet matches the
            # real emit and doesn't throw "AutkDb is not a constructor".
            "const AutkDb = __autkDbMod.AutkDb || __autkDbMod.AutkSpatialDb;\n"
            "if (typeof AutkDb !== 'function') throw new Error("
            "'@urban-toolkit/autk-db: neither AutkDb nor AutkSpatialDb is exported');\n"
            "const __sources = [{ type: 'geojson', geojsonObject: { type: 'FeatureCollection', "
            "features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [-87.63, 41.88] }, "
            "properties: { name: 'a' } }] }, outputTableName: 'probe_pts' }];\n"
            "const db = new AutkDb();\n"
            "await db.init();\n"
            "for (const source of __sources) { const { type, ...rest } = source; "
            "if (type === 'geojson') await db.loadGeojson(rest); }\n"
            "const out = [];\n"
            "for (const t of (db.getLayerTables ? db.getLayerTables() : [])) { "
            "const geojson = await db.getLayer(t.name); "
            "out.push({ name: t.name, type: t.type ?? 'polygons', geojson }); }\n"
            "return out;"
        )

        result = execute_js_code(
            code, '', 'AUTK_GRAMMAR', '', launch_dir=_REPO_ROOT, session_id=None,
        )
        self.assertEqual(result['stderr'], '', msg=result.get('stderr'))
        artifact_id = result['output']['path']
        self.assertNotEqual(artifact_id, '')
        self.assertEqual(result['output']['dataType'], 'list')

        layers = load_from_duckdb(artifact_id, session_id=None)
        self.assertIsInstance(layers, list)
        self.assertEqual(len(layers), 1)
        layer = layers[0]
        self.assertEqual(layer['name'], 'probe_pts')
        self.assertEqual(layer['geojson']['type'], 'FeatureCollection')
        self.assertEqual(len(layer['geojson']['features']), 1)

    def test_backend_base_url_follows_the_running_stack(self):
        """The backend URL handed to JS comes from the environment, not a constant.

        The frontend cannot know which address the sandbox subprocess must dial -
        under Docker the two are in different network namespaces, and on a
        custom-port stack the page's own port is not the sandbox's. It used to
        force :5002 for any loopback backend, so every OSM/PBF load on a
        non-default-port stack died with "fetch failed" (#248).
        """
        import os
        from utk_curio.sandbox.app.worker import backend_base_url

        saved = {k: os.environ.get(k) for k in ('FLASK_BACKEND_HOST', 'FLASK_BACKEND_PORT')}
        try:
            os.environ['FLASK_BACKEND_HOST'] = 'localhost'
            os.environ['FLASK_BACKEND_PORT'] = '5248'
            # localhost is normalised: Node's fetch can stall on ::1 while Flask
            # listens on IPv4 only.
            self.assertEqual(backend_base_url(), 'http://127.0.0.1:5248')

            os.environ['FLASK_BACKEND_HOST'] = '0.0.0.0'
            self.assertEqual(backend_base_url(), 'http://127.0.0.1:5248')

            os.environ['FLASK_BACKEND_HOST'] = 'backend.internal'
            self.assertEqual(backend_base_url(), 'http://backend.internal:5248')

            # Standalone sandbox with nothing exported: the documented default.
            del os.environ['FLASK_BACKEND_HOST']
            del os.environ['FLASK_BACKEND_PORT']
            self.assertEqual(backend_base_url(), 'http://127.0.0.1:5002')
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @_SKIP_NO_NODE
    def test_exec_js_substitutes_the_backend_url_token(self):
        """The placeholder is replaced before the user code runs."""
        import os
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import load_from_duckdb
        _worker_init()

        saved = os.environ.get('FLASK_BACKEND_PORT')
        os.environ['FLASK_BACKEND_PORT'] = '5248'
        try:
            result = execute_js_code(
                "return '__CURIO_BACKEND_URL__/file/docs/examples/data/niteroi.osm.pbf';",
                '', 'JS_COMPUTATION', '', launch_dir=_REPO_ROOT, session_id=None,
            )
            self.assertEqual(result['stderr'], '', msg=result.get('stderr'))
            value = load_from_duckdb(result['output']['path'], session_id=None)
            self.assertEqual(
                value, 'http://127.0.0.1:5248/file/docs/examples/data/niteroi.osm.pbf')
        finally:
            if saved is None:
                os.environ.pop('FLASK_BACKEND_PORT', None)
            else:
                os.environ['FLASK_BACKEND_PORT'] = saved

    @_SKIP_NO_NODE
    @_SKIP_NO_AUTK_DB
    def test_exec_js_autk_short_load_fails_the_node(self):
        """A data load that comes back SHORT fails, naming the missing table.

        This is #248: autk-db's loadOsm walks autoLoadLayers.layers in order and
        lets a per-layer failure propagate, so a throw partway leaves the earlier
        tables registered and the later ones absent. The emit used to publish
        whatever getLayerTables() held, so the node that failed reported "Done"
        and a consumer two hops downstream died on "Table table_osm_roads not
        found". Failing here is also what makes the loss reachable by
        runDataInBackend's retry: `success: false` returns an empty output.path,
        the one shape that retry has always keyed on.
        """
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        _worker_init()

        result = execute_js_code(
            _CONTRACT_CHECK_JS.format(load_errors="['osm: undici assert(!this.paused)']"),
            '', 'AUTK_GRAMMAR', '', launch_dir=_REPO_ROOT, session_id=None,
        )
        self.assertIn('probe_missing', result['stderr'])
        self.assertIn('fewer table(s) than the spec asked for', result['stderr'])
        # The recorded reason travels with the failure - it is the only account
        # of WHY the layer is missing, and used to be discarded to a console.log.
        self.assertIn('undici', result['stderr'])
        # No artifact: the short layer array must not reach a downstream node,
        # and an empty path is what triggers the caller's retry.
        self.assertEqual(result['output']['path'], '')

    @_SKIP_NO_NODE
    @_SKIP_NO_AUTK_DB
    def test_exec_js_autk_empty_area_still_succeeds(self):
        """Missing tables with NO recorded error is a sparse area, not a failure.

        The other half of the predicate. autk-db creates a layer table even at
        zero features, so a missing table always coincides with a caught reason
        when the load actually broke - which is what lets the check above throw
        without turning a genuinely empty query area into a red node.
        """
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import load_from_duckdb
        _worker_init()

        result = execute_js_code(
            _CONTRACT_CHECK_JS.format(load_errors='[]'),
            '', 'AUTK_GRAMMAR', '', launch_dir=_REPO_ROOT, session_id=None,
        )
        self.assertEqual(result['stderr'], '', msg=result.get('stderr'))
        layers = load_from_duckdb(result['output']['path'], session_id=None)
        self.assertEqual([l['name'] for l in layers], ['probe_pts'])


class TestProjDataDir(unittest.TestCase):
    """Regression test for pyproj 'no database context' on CRS-bearing GeoJSON.

    pyproj bundles a proj.db that can lag behind the system PROJ runtime
    (conda proj 9.7+ uses layout 1.6, pyproj 3.7.2's bundled copy is 1.4).
    _worker_init() calls pyproj.datadir.set_data_dir() to redirect pyproj at
    the system database before any CRS operation.  This test ensures that
    gpd.read_file() on a GeoJSON with an embedded EPSG:32632 CRS succeeds.
    """

    #: The Milan census polygons, now a Data Catalog dataset rather than a loose
    #: file under docs/examples/data. Addressed by path, not by
    #: ``curio_dataset_path``, because these tests call ``execute_code``
    #: directly and so never get the backend's resolved ``dataset_paths``.
    _CENSUS_GJ = os.path.join(
        _REPO_ROOT,
        "datasets",
        "data.urbanlab.milan-census-gt65@1",
        "data",
        "milan-census-gt65.geojson",
    )

    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init
        _worker_init()

    @unittest.skipUnless(
        os.path.exists(_CENSUS_GJ),
        f"{_CENSUS_GJ} not present (is the Data Catalog checked out?), skipping",
    )
    def test_census_load_resolves_epsg_32632(self):
        """execute_code() must load the census GeoJSON without a CRS error."""
        from utk_curio.sandbox.app.worker import execute_code

        code = (
            "    import geopandas as gpd\n"
            f"    gdf = gpd.read_file(r'{self._CENSUS_GJ}')\n"
            "    return gdf\n"
        )
        result = execute_code(
            code,
            file_path='',
            node_type='DATA_LOADING',
            data_type='',
            launch_dir=_REPO_ROOT,
            session_id=None,
        )

        self.assertEqual(result['stderr'], '', msg=result['stderr'])
        self.assertNotEqual(result['output']['path'], '')
        self.assertEqual(result['output']['dataType'], 'geodataframe')

    @unittest.skipUnless(
        os.path.exists(_CENSUS_GJ),
        f"{_CENSUS_GJ} not present (is the Data Catalog checked out?), skipping",
    )
    def test_reproject_epsg_3395(self):
        """set_crs(32632).to_crs(3395) must not raise after _worker_init()."""
        from utk_curio.sandbox.app.worker import execute_code

        # First produce the census GeoDataFrame as an artifact.
        load_code = (
            "    import geopandas as gpd\n"
            f"    gdf = gpd.read_file(r'{self._CENSUS_GJ}')\n"
            "    return gdf\n"
        )
        load_result = execute_code(
            load_code, '', 'DATA_LOADING', '', launch_dir=_REPO_ROOT, session_id=None,
        )
        self.assertEqual(load_result['stderr'], '', msg=load_result['stderr'])

        reproject_code = (
            "    gdf = arg\n"
            "    return gdf.set_crs(32632).to_crs(3395)\n"
        )
        reproject_result = execute_code(
            reproject_code,
            file_path=load_result['output']['path'],
            node_type='DATA_TRANSFORMATION',
            data_type='geodataframe',
            launch_dir=_REPO_ROOT,
            session_id=None,
        )
        self.assertEqual(reproject_result['stderr'], '', msg=reproject_result['stderr'])
        self.assertNotEqual(reproject_result['output']['path'], '')


if __name__ == "__main__":
    unittest.main()

class TestNoInputTripwire(unittest.TestCase):
    """The ``arg``-without-input guard names the upstream failure (#276).

    A downstream node whose upstream just failed used to report only that it
    "received no input", which reads as a wiring problem and sent the reporter
    hunting through edges before finding the 404 one node up. The message now
    says the input is missing because an upstream node has not run, failed, or
    is not wired, and says what to do about each.
    """

    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init
        _worker_init()

    def test_message_points_at_the_upstream_node(self):
        from utk_curio.sandbox.app.worker import execute_code

        result = execute_code(
            "    return arg.head()\n",
            file_path='',
            node_type='DATA_TRANSFORMATION',
            data_type='',
            launch_dir=_REPO_ROOT,
            session_id=None,
        )

        stderr = result['stderr']
        self.assertIn("received no input but its code references `arg`", stderr)
        self.assertIn("has not run yet, failed, or is not wired", stderr)
        self.assertIn("fix any that show an error", stderr)
        self.assertEqual(result['output']['path'], '')

    def test_a_loader_that_never_reads_arg_is_not_refused(self):
        """A standalone loader may contain the letters "arg" and still run (#273).

        The guard used to be ``'arg' in code``, a substring test, so an
        input-free Data Loading node was refused for ordinary words like
        ``target`` or a URL query parameter. Every name below contains the
        substring; none of them reads the input.
        """
        from utk_curio.sandbox.app.worker import execute_code

        code = (
            "    target = 2\n"
            "    large_margin = 3  # arguably enough\n"
            "    return target * large_margin\n"
        )
        result = execute_code(
            code,
            file_path='',
            node_type='DATA_LOADING',
            data_type='',
            launch_dir=_REPO_ROOT,
            session_id=None,
        )

        # Not asserting an empty stderr: this returns an int, which Data Loading's
        # own output validation rejects. The claim here is only that the no-input
        # tripwire did not fire.
        self.assertNotIn("received no input", result['stderr'])

    def test_binding_arg_without_reading_it_is_not_refused(self):
        """Binding ``arg`` is a Store, not a read, so it needs no input (#273)."""
        from utk_curio.sandbox.app.worker import execute_code

        result = execute_code(
            "    arg = 7\n    return 7\n",
            file_path='',
            node_type='DATA_TRANSFORMATION',
            data_type='',
            launch_dir=_REPO_ROOT,
            session_id=None,
        )

        self.assertNotIn("received no input", result['stderr'])

    def test_the_guard_still_fires_for_code_that_reads_arg(self):
        """Reading the input is still detected, however it is spelled (#276)."""
        from utk_curio.sandbox.app.worker import _code_reads_arg

        self.assertTrue(_code_reads_arg("    return arg.head()\n"))
        self.assertTrue(_code_reads_arg("    for row in arg:\n        pass\n"))
        self.assertTrue(_code_reads_arg("    return [x for x in arg]\n"))
        self.assertFalse(_code_reads_arg("    return 'targets and arguments'\n"))
        self.assertFalse(_code_reads_arg("    # arg is not used here\n    return 1\n"))
