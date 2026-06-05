import os

from flask import current_app


# test the app routes
def test_app_routes(app):
    expected_app_endpoints = [
        "/static/<path:filename>",
        "/",
        "/live",
        "/upload",
        "/processPythonCode",
        "/signin",
        "/getUser",
        "/saveUserType",
        "/checkDB",
    ]

    expected_app_routes = [
        "static",
        "api.root",
        "api.live",
        "api.upload_file",
        "api.process_python_code",
        "api.signin_legacy",
        "api.get_user_legacy",
        "api.save_user_type_legacy",
        "api.check_db",
    ]

    with app.app_context():
        app_endpoints = [rule.endpoint for rule in current_app.url_map.iter_rules()]
        app_routes = [rule.rule for rule in current_app.url_map.iter_rules()]
    # expected_app_endpoints are URL rules; expected_app_routes are endpoint names
    for route in expected_app_endpoints:
        assert route in app_routes, f"Missing route: {route}"
    for endpoint in expected_app_routes:
        assert endpoint in app_endpoints, f"Missing endpoint: {endpoint}"


def test_file_route_serves_relative_to_launch_cwd(app):
    """GET /file/<path> serves a file resolved relative to CURIO_LAUNCH_CWD."""
    launch_cwd = os.environ["CURIO_LAUNCH_CWD"]
    rel = os.path.join("data", "file_route_probe.txt")
    abs_path = os.path.join(launch_cwd, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(b"curio-file-route-ok")
    try:
        resp = app.test_client().get(f"/file/{rel}")
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
