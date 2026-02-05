import sys
from .test_frontend.fixtures import *  # noqa
import pytest
from server import create_app

sys.dont_write_bytecode = True


def pytest_addoption(parser):
    parser.addoption(
        "--longrun",
        action="store_true",
        dest="longrun",
        default=False,
        help="enable longrundecorated tests",
    )


def pytest_configure(config):
    if not config.option.longrun:
        setattr(config.option, "markexpr", "not externalapi")


@pytest.fixture(scope="session")
def app():
    """Creates a Flask test app instance."""
    app = create_app()
    app.config.update(
        {
            "TESTING": True,
            "LIVESERVER_PORT": 5002,
            # Use 5002 so frontend (dotenv .env / default) finds the backend
            "BACKEND_PORT": 5002,
            "SANDBOX_PORT": 2000,
            "FRONTEND_PORT": 8080,
        }
    )
    return app