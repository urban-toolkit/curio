from flask import current_app


# test the app routes
def test_app_routes(app):
    expected_app_endpoints = [
        "/static/<path:filename>",
        "/",
        "/live",
        "/upload",
        "/processPythonCode",
        "/toLayers",
        "/saveWorkflowProv",
        "/newBoxProv",
        "/deleteBoxProv",
        "/newConnectionProv",
        "/deleteConnectionProv",
        "/boxExecProv",
        "/getBoxGraph",
        "/truncateDBProv",
        "/signin",
        "/getUser",
        "/saveUserType",
        "/saveUserProv",
    ]

    expected_app_routes = [
        "static",
        "api.root",
        "api.live",
        "api.upload_file",
        "api.process_python_code",
        "api.toLayers",
        "api.save_workflow_prov",
        "api.new_box_prov",
        "api.delete_box_prov",
        "api.new_connection_prov",
        "api.delete_connection_prov",
        "api.box_exec_prov",
        "api.get_box_graph",
        "api.truncate_db_prov",
        "api.signin",
        "api.get_user",
        "api.save_user_type",
        "api.save_user_prov",
    ]

    with app.app_context():
        app_endpoints = [rule.endpoint for rule in current_app.url_map.iter_rules()]
        app_routes = [rule.rule for rule in current_app.url_map.iter_rules()]
    # expected_app_endpoints are URL rules; expected_app_routes are endpoint names
    for route in expected_app_endpoints:
        assert route in app_routes, f"Missing route: {route}"
    for endpoint in expected_app_routes:
        assert endpoint in app_endpoints, f"Missing endpoint: {endpoint}"
