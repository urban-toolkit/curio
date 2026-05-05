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
