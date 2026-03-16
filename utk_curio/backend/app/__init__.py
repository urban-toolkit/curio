from flask import Flask, request, current_app, g
import os
import logging
import time
from logging.handlers import RotatingFileHandler

from utk_curio.backend.config import Config as config_class
from utk_curio.backend.extensions import db, migrate


def get_locale():
    return request.accept_languages.best_match(current_app.config['LANGUAGES'])


def create_app(config_class=config_class):

    # Flask app
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    from utk_curio.backend.app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='')

    from utk_curio.backend.app.users import bp as users_bp
    app.register_blueprint(users_bp)

    # Make sure request logs emit even in debug
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def _log_request_start():
        g._req_start_time = time.time()

    @app.after_request
    def _log_request_end(response):
        start = getattr(g, "_req_start_time", None)
        duration_ms = int((time.time() - start) * 1000) if start else -1
        app.logger.info(
            "API %s %s -> %s in %sms from %s",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            request.remote_addr,
        )
        return response

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

    return app
