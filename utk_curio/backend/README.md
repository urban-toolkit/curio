## Frontend tests (Playwright)

Before running frontend/E2E tests, install the Playwright browser once (use the same Python/venv you use for pytest):

```shell
playwright install chromium
# or: python -m playwright install chromium
```

## Database management

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
