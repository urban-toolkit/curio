import os

from flask import current_app


# test the app routes
def test_app_routes(app):
    expected_app_endpoints = [
        "/static/<path:filename>",
        "/",
        "/live",
        "/version",
        "/file/<path:filename>",
        "/processPythonCode",
        "/processJavaScriptCode",
    ]

    expected_app_routes = [
        "static",
        "api.root",
        "api.live",
        "api.version",
        "api.serve_launch_cwd_file",
        "api.process_python_code",
        "api.process_javascript_code",
    ]

    with app.app_context():
        app_endpoints = [rule.endpoint for rule in current_app.url_map.iter_rules()]
        app_routes = [rule.rule for rule in current_app.url_map.iter_rules()]
    # expected_app_endpoints are URL rules; expected_app_routes are endpoint names
    for route in expected_app_endpoints:
        assert route in app_routes, f"Missing route: {route}"
    for endpoint in expected_app_routes:
        assert endpoint in app_endpoints, f"Missing endpoint: {endpoint}"


def test_removed_legacy_routes_stay_removed(app):
    """Routes deleted in the loose-endpoint sweep must not come back.

    Each of these had zero callers when it was removed: debug probes that
    leaked server paths (``/cwd``, ``/launchCwd``, ``/sharedDataPath``),
    deprecated 308 shims superseded by ``/api/auth/me`` (``/getUser``,
    ``/saveUserType``), an unused DB probe (``/checkDB`` - the container
    healthcheck uses ``/health``), and two endpoints superseded by the
    packages and datasets blueprints (``/installPackages`` ->
    ``/api/packages/workflow-deps/install``, ``/upload`` ->
    ``/api/datasets/import``).

    ``/datasets`` joined them for #142: the bare dataset browser that
    ``list_datasets`` fed, removed in 02056f69 along with the frontend
    DatasetsWindow. Every dataset surface is namespaced under
    ``/api/datasets/`` now.
    """
    removed = [
        "/cwd",
        "/launchCwd",
        "/sharedDataPath",
        "/getUser",
        "/saveUserType",
        "/checkDB",
        "/installPackages",
        "/upload",
        "/datasets",
        "/api/packages/install-deps",
        # The pre-agent LLM assistance. Its last caller was the node editor's
        # Explanation tab, replaced by agent.node-explainer - which reads a
        # richer nodeContext from the backend and shares the same prompt file.
        "/llm/chat",
        "/llm/check",
        "/llm/clean",
    ]
    with app.app_context():
        app_routes = {rule.rule for rule in current_app.url_map.iter_rules()}
    for route in removed:
        assert route not in app_routes, (
            f"{route} was removed as a loose endpoint; re-add a caller "
            f"(and this test entry) before restoring it"
        )


def test_file_route_serves_relative_to_launch_cwd(app):
    """GET /file/<path> serves a file resolved relative to CURIO_LAUNCH_CWD."""
    launch_cwd = os.environ["CURIO_LAUNCH_CWD"]
    # The URL path is always forward-slash separated (that's what the frontend
    # sends). Build the filesystem path separately with os.path.join — using
    # os.path.join for the URL would emit a backslash on Windows, and the route
    # splits on '/', so it would 404.
    url_rel = "data/file_route_probe.txt"
    abs_path = os.path.join(launch_cwd, "data", "file_route_probe.txt")
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(b"curio-file-route-ok")
    try:
        # buffered=True so werkzeug reads the body and closes send_file's file
        # handle before returning — otherwise os.remove below raises
        # PermissionError on Windows (the file is still held open).
        resp = app.test_client().get(f"/file/{url_rel}", buffered=True)
        assert resp.status_code == 200
        assert resp.data == b"curio-file-route-ok"
    finally:
        os.remove(abs_path)


def test_file_route_blocks_path_traversal(app):
    """Path-traversal payloads escaping CURIO_LAUNCH_CWD never serve content."""
    resp = app.test_client().get("/file/..%2f..%2f..%2fetc%2fpasswd")
    # werkzeug may normalize the URL (404) or safe_join may reject it (403);
    # either way the file must not be served.
    assert resp.status_code != 200
    assert b"root:" not in resp.data


class TestVersionPassesTheSandboxIsolationFields:
    """The badge's two fields have to survive the proxy.

    ``/api/version`` is what the browser reads; it asks the sandbox and
    forwards the answer. The sandbox reports both the mode it *resolved*
    (``isolation``) and what execution actually did (``isolation_active``),
    and only the second can reveal a stack that resolved ``fork`` and is
    running node code in-process anyway. A proxy that dropped it would put the
    badge back to claiming a boundary that is not there.
    """

    def _get(self, app, payload, *, status=200, boom=None):
        from unittest import mock

        import requests

        from utk_curio.backend.app.api import routes

        class _Response:
            status_code = status

            @staticmethod
            def json():
                return payload

        def _fake_get(*_args, **_kwargs):
            if boom is not None:
                raise boom
            return _Response()

        with mock.patch.object(routes._sandbox_session, "get", _fake_get):
            return app.test_client().get("/version").get_json()

    def test_both_fields_are_forwarded(self, app):
        body = self._get(app, {"isolation": "fork", "isolation_active": "fork"})
        assert body["isolation"] == "fork"
        assert body["isolation_active"] == "fork"

    def test_a_degraded_stack_is_forwarded_as_such(self, app):
        """The combination the field exists for; the proxy must not flatten it."""
        body = self._get(app, {"isolation": "fork", "isolation_active": "off"})
        assert body["isolation"] == "fork"
        assert body["isolation_active"] == "off"

    def test_an_older_sandbox_yields_unknown_not_off(self, app):
        """Absence is not evidence of a failed zygote.

        Reporting ``off`` here would make the badge say "not isolated" on an
        instance that is isolated, which is the mirror of the bug this guards.
        """
        body = self._get(app, {"isolation": "fork"})
        assert body["isolation_active"] == "unknown"

    def test_an_unreachable_sandbox_still_answers(self, app):
        """The badge must render when the sandbox is slow or down."""
        import requests

        body = self._get(app, None, boom=requests.RequestException("down"))
        assert body["isolation"] == "unknown"
        assert body["isolation_active"] == "unknown"
        assert body["version"]
