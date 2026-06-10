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
    def test_exec_js_float_stored_correclty_in_duckdb(self):
        """Floats can be inserted and accsess from duckDB without any side effects"""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        float_artifact_id = save_to_duckdb(3.14159, node_id='JS_COMPUTATION', session_id=None)
        result = execute_js_code('return arg;', float_artifact_id, 'JS_COMPUTATION', 'float', session_id=None)
        self.assertEqual(result['stderr'], '')
        float_value = load_from_duckdb(result['output']['path'], session_id=None)
        self.assertAlmostEqual(float_value, 3.14159)

    @_SKIP_NO_NODE
    def test_exec_js_string_stored_correclty_in_duckdb(self):
        """Strings are stored and accsessed gracefully with DuckDB"""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        string_artifact_id = save_to_duckdb("Hello ", node_id='JS_COMPUTATION', session_id=None)
        result = execute_js_code('return arg + "World";', string_artifact_id, 'JS_COMPUTATION', 'str', session_id=None)
        self.assertEqual(result['stderr'], '')
        string_value =  load_from_duckdb(result['output']['path'], session_id=None)
        self.assertEqual(string_value, "Hello World")
    
    # Tests concerned with interactions between different nodes
    @_SKIP_NO_NODE
    def test_interactions_between_Python_and_JS_node_types(self):
        """Tests whether data will flow nicely from Python to JS nodes"""
        from utk_curio.sandbox.app.worker import execute_js_code, _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        _worker_init()
        init_db()
        artifact_id = save_to_duckdb({"Name": "Ghandi", "Birth_Year": 1947}, node_id="DATA_LOADING", session_id=None)
        result = execute_js_code(
            'let data = arg; data["Birth_Year"] = 1869; return data["Birth_Year"]',
            artifact_id, 'JS_COMPUTATION', 'int', session_id=None
        )
        self.assertEqual(result['stderr'], '')
        value = load_from_duckdb(result['output']['path'], session_id=None)
        self.assertEqual(value, 1869)

    # Tests concerned with error handling
    @_SKIP_NO_NODE
    def test_empty_returns(self):
        """null and undefined return types are handled gracefully"""
        from utk_curio.sandbox.app.worker import execute_js_code, execute_code, _worker_init
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        _worker_init()

        # Testing code execution of empty values
        null_result = execute_js_code('return null;', '', 'JS_COMPUTATION', '', session_id=None)
        undefined_result = execute_js_code('return undefined;', '', 'JS_COMPUTATION', '', session_id=None)

        null_artifact_id = null_result['output']['path']
        undefined_artifact_id = undefined_result['output']['path']

        self.assertEqual(null_result['stderr'], '')
        self.assertEqual(undefined_result['stderr'], '')

        null_value = load_from_duckdb(null_artifact_id, session_id=None)
        undefined_value = load_from_duckdb(undefined_artifact_id, session_id=None)

        self.assertEqual(null_value, None)
        self.assertEqual(undefined_value, None)
        
    @_SKIP_NO_NODE
    def test_artifacts_and_session_ids(self):
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.parsers import save_to_duckdb, load_from_duckdb
        from utk_curio.sandbox.util.db import init_db
        """ This tests the isolation of sessions. Can one session grab information from another?"""
        _worker_init()
        init_db()

        artifact_id = save_to_duckdb(67, 'COMPUTATION_ANALYSIS', session_id='8375e155-836c-47zb-ada0-737660baf2ec')     # Fake session id

        # Does the function work properly
        value = load_from_duckdb(artifact_id, session_id="8375e155-836c-47zb-ada0-737660baf2ec")
        self.assertEqual(value, 67)

        # Different session id's cannot accsess information from eachother
        with self.assertRaises(KeyError):
            load_from_duckdb(artifact_id, session_id='1678x145-221f-72fg-rfg2-444333abf2wq')

        # Edge cases may not be nessecary
        # A session without an id cannot accsess information from a session with an id
        # with self.assertRaises(KeyError):
        #     load_from_duckdb(artifact_id, session_id=None)

        # A session with an id cannot accsess information from a session without one
        # artifact_id = save_to_duckdb(10, 'COMPUTATION_ANALYSIS', session_id=None)
        # with self.assertRaises(KeyError):
        #     load_from_duckdb(artifact_id, session_id='1678x145-221f-72fg-rfg2-444333abf2wq')



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


class TestProjDataDir(unittest.TestCase):
    """Regression test for pyproj 'no database context' on CRS-bearing GeoJSON.

    pyproj bundles a proj.db that can lag behind the system PROJ runtime
    (conda proj 9.7+ uses layout 1.6, pyproj 3.7.2's bundled copy is 1.4).
    _worker_init() calls pyproj.datadir.set_data_dir() to redirect pyproj at
    the system database before any CRS operation.  This test ensures that
    gpd.read_file() on a GeoJSON with an embedded EPSG:32632 CRS succeeds.
    """

    _CENSUS_GJ = os.path.join(
        _REPO_ROOT, "docs", "examples", "data", "09-milan_census.geojson"
    )

    @classmethod
    def setUpClass(cls):
        from utk_curio.sandbox.app.worker import _worker_init
        _worker_init()

    @unittest.skipUnless(
        os.path.exists(os.path.join(
            _REPO_ROOT, "docs", "examples", "data", "09-milan_census.geojson"
        )),
        "09-milan_census.geojson not present — skipping",
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
        os.path.exists(os.path.join(
            _REPO_ROOT, "docs", "examples", "data", "09-milan_census.geojson"
        )),
        "09-milan_census.geojson not present — skipping",
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