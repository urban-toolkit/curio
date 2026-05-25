import os
from dotenv import load_dotenv


basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))
load_dotenv(os.path.join(basedir, '.flaskenv'))

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


CURIO_ENV = os.environ.get("CURIO_ENV", "dev")  # dev | prod

CURIO_NO_PROJECT = _env_flag("CURIO_NO_PROJECT", False)
# Skipping the projects page implies skipping auth as well: the shared-guest
# auto-signin path is the only way to reach the canvas without a login form.
CURIO_NO_AUTH = _env_flag("CURIO_NO_AUTH", False) or CURIO_NO_PROJECT

ALLOW_GUEST_LOGIN = _env_flag("ALLOW_GUEST_LOGIN", CURIO_ENV != "prod")

GUEST_PROJECT_CLEANUP = _env_flag("GUEST_PROJECT_CLEANUP", False)

CURIO_SHARED_GUEST_USERNAME = os.environ.get(
    "CURIO_SHARED_GUEST_USERNAME", "guest_shared"
)

CURIO_SHARED_GUEST_NAME = os.environ.get(
    "CURIO_SHARED_GUEST_NAME", "Shared Guest"
)

CURIO_PROJECT_EXEC_CACHE = _env_flag("CURIO_PROJECT_EXEC_CACHE", False)

# Catalog author actions (publish/unpublish into <repo_root>/packages/).
# Default ON so dev installs keep working without extra config; operators
# locking down a deployment can disable with =0/false/no/off.
CURIO_ALLOW_FACTORY_CATALOG_PUBLISH = _env_flag(
    "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", True
)
# Force re-seeding catalog packages into the guest user's package store at
# startup, even when the per-user seed-state marker would normally skip them.
CURIO_RESEED_PACKAGES = _env_flag("CURIO_RESEED_PACKAGES", False)
# Seed example projects from docs/examples/ on startup.
CURIO_SEED_EXAMPLES = _env_flag("CURIO_SEED_EXAMPLES", False)

GUEST_LLM_API_TYPE = os.environ.get("GUEST_LLM_API_TYPE", "openai_compatible")
GUEST_LLM_BASE_URL = os.environ.get("GUEST_LLM_BASE_URL", "")
GUEST_LLM_API_KEY = os.environ.get("GUEST_LLM_API_KEY", "")
GUEST_LLM_MODEL = os.environ.get("GUEST_LLM_MODEL", "gpt-4o-mini")


def _is_dev() -> bool:
    """True when the backend is NOT running in production.

    Gates dev-only surfaces (e.g. /api/testing/* stub endpoints) without
    forcing the caller to opt into the dedicated test DB.
    """
    return CURIO_ENV != "prod"


def _is_testing() -> bool:
    """True when the backend is running against the dedicated test database.

    A single env flag switches every DB path to a test-only location so dev
    state is never touched by pytest / Playwright.
    """
    return _env_flag("CURIO_TESTING", False)


def _test_launch_dir() -> str:
    return os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd()


def _resolve_database_uri() -> str:
    """Return the SQLAlchemy URL to use.

    When ``CURIO_TESTING=1`` the URL points to a dedicated test DB under
    ``<CURIO_LAUNCH_CWD>/.curio/test/urban_workflow_test.db`` (overridable
    via ``DATABASE_URL_TEST``). Otherwise the normal ``DATABASE_URL`` /
    dev default applies.
    """
    if _is_testing():
        explicit = os.environ.get("DATABASE_URL_TEST")
        if explicit:
            return explicit
        test_dir = os.path.join(_test_launch_dir(), ".curio", "test")
        os.makedirs(test_dir, exist_ok=True)
        return "sqlite:///" + os.path.join(test_dir, "urban_workflow_test.db")
    return os.environ.get("DATABASE_URL") or "sqlite:///urban_workflow.db"


class Config:
    LOG_TO_STDOUT = os.environ.get('LOG_TO_STDOUT')

    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'

    SQLALCHEMY_DATABASE_URI = _resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = True

    WTF_CSRF_ENABLED = True

    ADMINS = ['your-email@example.com']

    SANDBOX_RELATIVE_PATH = (os.environ.get('SANDBOX_RELATIVE_PATH') or
                             '../sandbox')
    FRONTEND_RELATIVE_PATH = (os.environ.get('FRONTEND_RELATIVE_PATH') or
                                '../urban-workflows')
    FRONTEND_PORT = os.environ.get('FRONTEND_PORT') or 8080
    SANDBOX_PORT = os.environ.get('SANDBOX_PORT') or 2000
    BACKEND_PORT = os.environ.get('BACKEND_PORT') or 5002
