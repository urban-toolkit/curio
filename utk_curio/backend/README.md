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

- Export `CURIO_TESTING=1` (done automatically by `test.sh` and `curio coverage`).
- The backend then resolves `SQLALCHEMY_DATABASE_URI` → `sqlite:///<CURIO_LAUNCH_CWD>/.curio/test/urban_workflow_test.db` (override with `DATABASE_URL_TEST`).
- A session-scoped fixture in `tests/conftest.py` wipes the file and re-applies migrations at the start of every pytest session; a per-test autouse fixture truncates mutable tables between tests.
- Unit tests in `tests/test_users/` and `app/projects/tests/` already use in-memory `sqlite://` and do not need `CURIO_TESTING`.

### Test-only DB stub endpoints

When `CURIO_TESTING=1`, `create_app` additionally registers [`app/testing/`](app/testing/routes.py) — a Flask blueprint exposing:

- `POST /api/testing/stub-login` — create-or-find a user, open a `UserSession`, return `{user, token}`.
- `POST /api/testing/stub-project` — seed an empty `Project` owned by a user, return its `id`/`slug`.

Both handlers re-guard on `CURIO_TESTING` at request time with `abort(404)`, so the blueprint is invisible to production builds even if accidentally imported. Playwright helpers in [`tests/test_frontend/utils.py`](tests/test_frontend/utils.py) (`stub_db_login`, `stub_login_and_enter_workflow`) use these to skip the signup UI for tests where auth is incidental setup — e.g. the parametrized `TestWorkflowCanvas` class. Tests whose subject *is* the auth UI (`test_auth_flow.py`, `test_project_save_load.py`, `test_project_ownership.py`, `test_project_dirty_guard.py`) still drive the real `/auth/signup` and `/auth/signin` forms via `signup_e2e_user` / `signup_and_enter_new_workflow`.

See [`tests/test_frontend/README.md`](tests/test_frontend/README.md) for the full contract.
