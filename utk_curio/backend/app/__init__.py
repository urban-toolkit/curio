from flask import Flask, request, current_app, make_response, jsonify
import os
import logging
import traceback
from logging.handlers import RotatingFileHandler

from utk_curio.backend.config import Config as config_class
from utk_curio.backend.config import _is_dev
from utk_curio.backend.extensions import db, migrate, socketio


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,PUT,POST,PATCH,DELETE,OPTIONS",
    "Access-Control-Max-Age": "600",
}


def _apply_cors(response):
    for k, v in CORS_HEADERS.items():
        response.headers[k] = v
    return response


def get_locale():
    return request.accept_languages.best_match(current_app.config['LANGUAGES'])


def create_app(config_class=config_class):

    # Flask app
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)

    from utk_curio.backend.app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='')

    from utk_curio.backend.app.collaboration import events  # noqa: F401 — registers socket handlers

    from utk_curio.backend.app.users import bp as users_bp
    app.register_blueprint(users_bp)

    from utk_curio.backend.app.users.routes import auth_bp, config_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(config_bp)

    from utk_curio.backend.app.projects.routes import projects_bp
    app.register_blueprint(projects_bp)

    from utk_curio.backend.app.notebooks import notebooks_bp
    app.register_blueprint(notebooks_bp)

    # Non-prod DB stub endpoints for Playwright E2E tests.
    # Lets Playwright seed users / projects directly without the signup form.
    if _is_dev():
        from utk_curio.backend.app.testing.routes import testing_bp
        app.register_blueprint(testing_bp)

    @app.before_request
    def short_circuit_preflight():
        if request.method == "OPTIONS":
            return _apply_cors(make_response("", 204))

    @app.after_request
    def add_cors_headers(response):
        return _apply_cors(response)

    @app.errorhandler(Exception)
    def handle_unhandled_exception(err):
        app.logger.error("Unhandled exception: %s\n%s", err, traceback.format_exc())
        response = jsonify({"error": str(err)})
        response.status_code = 500
        return _apply_cors(response)

    if not app.debug and not app.testing:
        if app.config['LOG_TO_STDOUT']:
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.INFO)
            app.logger.addHandler(stream_handler)
        else:
            if not os.path.exists('logs'):
                os.mkdir('logs')
            file_handler = RotatingFileHandler('logs/backend.log',
                                               maxBytes=10240, backupCount=10)
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s '
                '[in %(pathname)s:%(lineno)d]'))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('Backend startup')

    from utk_curio.backend.app.projects.tasks import start_cleanup_scheduler
    start_cleanup_scheduler(app)

    return app
