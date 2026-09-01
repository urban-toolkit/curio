## Database management

See [CONTRIBUTING.md](../../docs/CONTRIBUTING.md#database-migrations) for
repo-wide migration guidance. Backend-specific notes are below.

- Create migration

```shell
# after update any model, run it to generate a new migration
FLASK_APP=server.py flask db migrate -m "Migration Name"
```

- Apply migrations

```shell
# run it to apply any migration that hasn't run yet
FLASK_APP=server.py flask db upgrade
```

## Test databases

Any test that boots the real backend (Playwright/E2E suite under `tests/test_frontend/`) runs against a **dedicated, wiped-clean test database**, never the dev `urban_workflow.db`. This keeps dev and test state fully separate.

- `CURIO_TESTING=1` must be set. `tests/conftest.py` exports it at import time, so every pytest run under `tests/` has it, whether launched by `curio test` or by pytest directly.
- The backend then resolves `SQLALCHEMY_DATABASE_URI` → `sqlite:///<CURIO_LAUNCH_CWD>/.curio/test/urban_workflow_test.db` (override with `DATABASE_URL_TEST`).
- A session-scoped fixture in `tests/conftest.py` wipes the file and re-applies migrations at the start of every pytest session; a per-test autouse fixture truncates mutable tables between tests.
- Unit tests in `tests/test_users/` and `app/projects/tests/` already use in-memory `sqlite://` and do not need `CURIO_TESTING`.

### Test-only DB stub endpoints

`create_app` registers [`app/testing/`](app/testing/routes.py) whenever `_is_dev()` (`CURIO_ENV != 'prod'`) - a Flask blueprint exposing:

- `POST /api/testing/stub-login` - create-or-find a user, open a `UserSession`, return `{user, token}`. A `password` is used only when creating the account; it is never applied to an account that already exists.
- `POST /api/testing/stub-project` - seed an empty `Project` owned by a user, return its `id`/`slug`.
- `POST /api/testing/reset-db` - truncate the mutable tables (`exec_cache_entry`, `project`, `auth_attempt`, `user_session`, `user`). A request may name a subset; anything outside that set is refused.
- `POST|GET|DELETE /api/testing/agent-script` - the out-of-process door to the scripted LLM provider's reply queue (see [`app/agents/testing_provider.py`](app/agents/testing_provider.py)).

A blueprint-level `before_request` refuses with 404 unless `_is_dev()` **and** `CURIO_TESTING` are both set, and the `agent-script` routes additionally require the scripted provider to be enabled. Both factors matter: `CURIO_ENV` defaults to `dev`, so `_is_dev()` alone would mount `stub-login` - which issues a valid session for any username with no password - on any deployment whose operator never set it. The guard returns a response rather than calling `abort`, because `create_app`'s catch-all error handler would rewrite an `HTTPException` into a 500. Playwright helpers in [`tests/test_frontend/utils.py`](tests/test_frontend/utils.py) (`stub_db_login`, `stub_login_and_enter_workflow`) use these to skip the signup UI for tests where auth is incidental setup - e.g. the parametrized `TestWorkflowCanvas` class. Tests whose subject *is* the auth UI (`test_auth_flow.py`, `test_project_save_load.py`, `test_project_ownership.py`, `test_project_dirty_guard.py`) still drive the real `/auth/signup` and `/auth/signin` forms via `signup_e2e_user` / `signup_and_enter_new_workflow`.

See [`tests/test_frontend/README.md`](tests/test_frontend/README.md) for the full contract.
