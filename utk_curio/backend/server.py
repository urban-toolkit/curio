import os
from utk_curio.backend.app import create_app
from utk_curio.backend.extensions import socketio

app = create_app()

with app.app_context():
    try:
        from utk_curio.backend.app.users.services import _shared_guest_user
        from utk_curio.backend.app.projects.services import reconcile_guest_projects
        guest = _shared_guest_user()
        n = reconcile_guest_projects(guest)
        if n:
            app.logger.info("Reconciled %d guest project(s) from filesystem", n)
        if os.environ.get("CURIO_SEED_EXAMPLES", "").lower() in ("1", "true", "yes"):
            from utk_curio.backend.app.projects.seed import seed_example_projects
            s = seed_example_projects(guest)
            app.logger.info("Seeded %d example project(s)", s)
    except Exception:
        app.logger.warning("Could not ensure guest user on startup", exc_info=True)

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

if __name__ == '__main__':
    socketio.run(
        app,
        host=os.getenv('FLASK_BACKEND_HOST', '127.0.0.1'),
        port=int(os.getenv('FLASK_BACKEND_PORT', 5002)),
        debug=True,
        use_reloader=os.getenv('FLASK_USE_RELOADER', '1') != '0',
        allow_unsafe_werkzeug=True,
    )

