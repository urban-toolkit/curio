# Deployment

How to deploy Curio on a server you already have, behind HTTPS. For local development see [USAGE.md](USAGE.md) instead.

This guide deploys Curio under a `/curio` path prefix on a hostname you already control (e.g. `https://lab-name.your-uni.edu/curio/`). The path prefix lets you share the hostname with other apps. Replace `lab-name.your-uni.edu` with whatever hostname your server uses, the rest of the steps don't change.

Assumed setup: a Linux server with the hostname already pointing at it, Docker + Compose installed, and [Caddy](https://caddyserver.com) installed as the reverse proxy.

> [!IMPORTANT]
> The frontend bundle is built **inside the Docker image** with `BACKEND_URL` and `PUBLIC_PATH` baked in at build time. Changing the public URL or path prefix means rebuilding the image, there is no runtime override.

## Contents

- [1. Configure the stack](#1-configure-the-stack)
- [2. Configure Caddy](#2-configure-caddy)
- [3. Build and run](#3-build-and-run)
- [Updating](#updating)
- [Optional: dev stack alongside stable](#optional-dev-stack-alongside-stable)
- [Optional: CI/CD with GitHub Actions + Tailscale](#optional-cicd-with-github-actions--tailscale)
- [Cutting a release](#cutting-a-release)
- [The monitor page](#the-monitor-page)
- [Troubleshooting](#troubleshooting)
- [Security checklist](#security-checklist)

## 1. Configure the stack

This step lays down the source tree and the configuration file that tells Docker which ports to use and where the public site will live. Everything Curio runs in production is driven from `/srv/curio/.env`, so getting this right up front saves a rebuild later.

Clone and create the data directories:

```bash
git clone https://github.com/urban-toolkit/curio.git /srv/curio
cd /srv/curio
mkdir -p instance .curio datasets
```

Create `/srv/curio/.env`:

```bash
CURIO_CONTAINER_NAME=curio
CURIO_PORT_5002=5002
CURIO_PORT_8080=8080

# URL prefix the bundle expects. Must match the Caddy path in step 2.
PUBLIC_PATH=/curio/

# Public URL the bundle uses to reach the backend.
# No trailing slash, frontend code does `${BACKEND_URL}/live` etc.
BACKEND_URL=https://lab-name.your-uni.edu/curio/api
```

The three directories you created are bind-mounted into the container and persist across recreates:

| Directory | Holds | Back up? |
|---|---|---|
| `instance/` | The SQLite DB: users, projects, sessions | **Yes** |
| `datasets/` | The shared Data Catalog: every dataset your users publish | **Yes** |
| `datalakes/` | The Data Lake Catalog: one manifest per data portal. Ships with the image | No |
| `.curio/` | Per-user stores, logs, sandbox artifacts, and each account's agent imports and catalog settings | Yes, if users' imported datasets, computed outputs and settings matter |

`packages/` is **not** mounted. The node catalog is baked into the image so it
always matches the deployed commit. Neither is `datalakes/`, for the same
reason: a data lake source declares a host the server makes outbound requests
to, so which sources exist should match the deployed commit rather than be
editable in a mounted volume. Set `CURIO_DATALAKE_ROOT` if you need it
elsewhere.

### Outbound requests

The Data Lake Catalog is the one feature that makes outbound requests on a
user's behalf, so it is worth knowing what bounds them. Every URL - search,
describe, download, and each redirect hop - passes the same default-deny
address policy the agent tools use: https/http only, private, loopback,
link-local and reserved addresses refused *after* DNS resolution, and the
connected peer re-checked before any response body is read.

Two things a deployment should know:

- **A source manifest can never exempt a host from that policy.** The one
  exemption in the codebase is for an operator-configured search provider, and
  this catalog does not use it.
- **The residual documented in `app/common/egress_policy.py` applies here
  too**: the request line and headers are on the wire before the peer can be
  confirmed, so a blind request to an internal service is not *prevented*, only
  its response is withheld. Closing that needs connection-factory work.

Rate limiting is per user, per source, and **in-process**. Under several
workers the effective rate is the configured rate times the worker count. It is
a politeness mechanism toward portals you do not own and a brake on accidental
loops, not a guarantee you can make to a third party.

> [!TIP]
> `datasets/` lives inside the git checkout, so publishing a dataset dirties your
> working tree. To avoid that, point the catalog at a path outside the checkout
> with `CURIO_CATALOG_ROOT` (or `--catalog-root`) and mount that path instead.

## 2. Configure Caddy

Caddy terminates HTTPS and forwards traffic into the Docker container. The two `handle_path` blocks below split incoming requests by URL prefix: anything under `/curio/api/` goes to the backend on port 5002, everything else under `/curio/` goes to the frontend on port 8080. The `handle_path` directive strips the prefix before forwarding, so your backend code sees normal paths like `/live` and `/upload`.

You have two TLS options depending on what your IT department provides. Pick one.

**Path A: Let's Encrypt** (port 80 reachable from the public internet, no institutional cert):

```caddy
lab-name.your-uni.edu {
    handle_path /curio/api/* { reverse_proxy localhost:5002 }
    handle_path /curio/* { reverse_proxy localhost:8080 }
    redir /curio /curio/ 301
}
```

**Path B: institutional cert** (port 80 blocked, or IT issues a cert for the hostname):

```caddy
lab-name.your-uni.edu {
    tls /etc/ssl/certs/lab-name.crt /etc/ssl/private/lab-name.key
    handle_path /curio/api/* { reverse_proxy localhost:5002 }
    handle_path /curio/* { reverse_proxy localhost:8080 }
    redir /curio /curio/ 301
}
```

For Path B, make sure the `caddy` system user can read the key. Otherwise Caddy fails to start with `permission denied`:

```bash
sudo chgrp caddy /etc/ssl/private/lab-name.key
sudo chmod 640 /etc/ssl/private/lab-name.key
# If /etc/ssl/private itself is mode 700:
sudo chmod 750 /etc/ssl/private
sudo chgrp caddy /etc/ssl/private
```

Apply:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## 3. Build and run

This is where the frontend bundle gets compiled with `BACKEND_URL` and `PUBLIC_PATH` baked in. The first build takes 10-15 minutes because it has to install Python and Node dependencies and run the full webpack build, subsequent builds are faster thanks to layer caching.

> [!WARNING]
> **Always deploy with both compose files.** `docker-compose.yml` alone starts
> Curio the way a local dev instance starts: the image's default command has no
> `--deploy`, so [`main.py`](../utk_curio/main.py) sets `CURIO_NO_AUTH=1` and
> **anyone who can reach the URL gets straight in with no login**. The
> [`docker-compose.deploy.yml`](../docker-compose.deploy.yml) overlay is what adds
> `--deploy` (auth + projects on), `--no-allow-publish` (locks the author-only
> catalog mutators), and `restart: unless-stopped`. Exporting `COMPOSE_FILE` once
> per shell applies it to every later `docker compose` command.

```bash
cd /srv/curio
export COMPOSE_FILE=docker-compose.yml:docker-compose.deploy.yml
docker compose build
docker compose up -d
```

Confirm auth actually came up before you hand out the URL. The container logs
the resolved flags on boot:

```bash
docker compose logs curio | grep CURIO_NO_AUTH   # must print CURIO_NO_AUTH=0
```

Verify from outside the server:

```bash
curl https://lab-name.your-uni.edu/curio/api/live
```

Then load `https://lab-name.your-uni.edu/curio/` in a browser. If something looks off, `docker compose logs -f` shows the running container's output.

## Updating

> **One-time, destructive: archived projects are deleted on this upgrade.**
> Archive is no longer an action, and alembic revision `f6a7b8c9d0e1` purges
> what it left behind: every project with `archived_at` set loses its row, its
> execution-cache entries and its files under
> `.curio/users/<user>/projects/<id>/`. It runs automatically during the
> migration step, without prompting, and `downgrade` restores only the column,
> not the data.
>
> Before upgrading, if anyone was using Archive as a holding area, copy those
> trees out. To see what would be removed, query the deployment's database
> (`$DATABASE_URL`, or `instance/urban_workflow.db` when it is unset):
>
> ```bash
> sqlite3 instance/urban_workflow.db \
>   "SELECT id, user_id, name FROM project WHERE archived_at IS NOT NULL"
> ```
>
> Deployments that never archived anything are unaffected; the purge finds
> nothing and only the schema changes.

Pulling new code is straightforward, but the `--no-cache` flag is important: Docker's layer cache occasionally fails to invalidate the npm-build step when build args change, which silently produces a frontend bundle still pointing at the old URL. Forcing a clean build is slower but guarantees correctness.

```bash
cd /srv/curio
export COMPOSE_FILE=docker-compose.yml:docker-compose.deploy.yml
git pull
docker compose build --no-cache
docker compose up -d --force-recreate
```

After the deploy completes, hard-refresh the browser (Ctrl+Shift+R) to drop any cached JavaScript.

`--force-recreate` matters: without it Compose reuses a container whose image
digest has not changed in its view, and the deploy silently keeps serving the old
build.

If `packages/` is dirty from a package published through the UI, `git pull`
refuses to fast-forward. Discard the change:

```bash
git checkout -- packages/ && git clean -fdq packages/
```

## Optional: dev stack alongside stable

A second checkout running on different ports under a different path lets you test changes without disrupting users. The two stacks share the hostname but live at separate URLs (`/curio/` for stable, `/curio-dev/` for dev) and run as separate Docker containers.

| | Stable | Dev |
|---|---|---|
| Path on server | `/srv/curio` | `/srv/curio-dev` |
| Container | `curio` | `curio-dev` |
| Published ports | 5002 / 8080 | 5012 / 8090 |
| Public URL | `lab-name.your-uni.edu/curio/` | `lab-name.your-uni.edu/curio-dev/` |

Clone into `/srv/curio-dev`, write a parallel `.env` with `CURIO_PORT_*=2010/5012/8090`, `PUBLIC_PATH=/curio-dev/`, and `BACKEND_URL=https://lab-name.your-uni.edu/curio-dev/api`. Add two more `handle_path` blocks to the same Caddy site (`/curio-dev/api/*` → 5012, `/curio-dev/*` → 8090). Then:

```bash
cd /srv/curio-dev
export COMPOSE_FILE=docker-compose.yml:docker-compose.deploy.yml
docker compose -p curio-dev build
docker compose -p curio-dev up -d --force-recreate
```

The `-p curio-dev` flag isolates this stack's Compose project so it doesn't conflict with stable.

## Optional: CI/CD with GitHub Actions + Tailscale

The repo includes [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) for push-to-deploy via Tailscale, so the GitHub Actions runner can reach your server without exposing public SSH. This is overkill for a one-person deployment but useful when multiple people merge to `main` and you want each merge automatically reflected on the dev stack.

To adapt it: install Tailscale on the server (`sudo tailscale up --advertise-tags=tag:curio-server --ssh`), create a Tailscale OAuth client with the `auth_keys` scope and tag `tag:ci`, add an ACL allowing `tag:ci -> tag:curio-server:22`, create a `deploy` user on the server with the `docker` group, and set three GitHub secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `DEPLOY_SSH_KEY` (private key whose pubkey is in `~deploy/.ssh/authorized_keys`). Then update the hostname (`utk` → your Tailscale machine name) and the `BACKEND_URL` exports in the workflow file.

Pushing to `main` triggers the dev deploy. Stable runs manually via Actions → Deploy → Run workflow.

`deploy.yml` takes two inputs: `ref` (branch, tag, or SHA; empty deploys the latest `v*` tag) and `target` (`both` / `dev` / `stable`). Both jobs check out the requested ref, export the two-file `COMPOSE_FILE`, and rebuild with `--no-cache --force-recreate`.

## Cutting a release

Version bumps are automated by [`.github/workflows/bump-version.yml`](../.github/workflows/bump-version.yml), which owns `utk_curio/__init__.py`. The bump type is explicit:

| You do | Bump | Tag | Deploys |
|---|---|---|---|
| Push to `main` (touching `utk_curio/**` or `docs/examples/**`) | patch | none | dev only |
| Actions → Bump version → Run workflow, `bump: minor` | minor | `vX.Y.0` | dev **and** stable |
| Actions → Bump version → Run workflow, `bump: major` | major | `vX.0.0` | dev **and** stable |

So a routine merge quietly ships to `curio-dev` and nothing else. Cutting a stable release is a deliberate act: dispatch the workflow with `minor` or `major`, and it bumps the version, tags the bump commit, and dispatches `deploy.yml` with `target: both` to put that exact tag on both stacks.

> [!NOTE]
> Pushes made with `GITHUB_TOKEN` never trigger workflows, which is why the bump job dispatches `deploy.yml` over the API rather than relying on its own commit to set things off. `workflow_dispatch` events are exempt from that recursion guard, so no PAT is needed.

To roll back, dispatch Deploy with `ref` set to the previous tag and `target: stable`.

## The monitor page

Every instance serves `/monitor`, a page that reports what the deployment is
doing and what has recently gone wrong. It exists on a laptop and on a server
alike; there is no flag to turn it on.

It shows:

- **Deployment** - version, the requested and active isolation mode, and which
  optional features are configured. Settings that have a value somebody chose
  (the execution account, the LLM base URL, model and key) are reported only as
  "configured" or "none", never as their value.
- **Hardware** - CPU model and core count, memory, swap, load average (raw and
  per core), and the resident memory of the backend and sandbox processes. The
  hostname is deliberately not reported.
- **Execution** - node runs since launch, failures, a duration histogram, how
  many isolated slots are busy, and a tally of how child processes died
  (timeout, OOM, CPU limit, refused confinement).
- **Accounts and content** - account, session, sign-in, project and dataset
  counts.
- **Storage** - disk usage across the `.curio` tree, as a distribution over
  user stores plus a per-area breakdown.
- **Recent errors** - the last failures from node executions, the sandbox, the
  backend, and the browser.

"Copy diagnostics" puts the whole picture on the clipboard as markdown, ready
to paste into an issue; "Download" saves the same thing as JSON.

Nothing is persisted. Every figure is since the process started, which is why
uptime is on the page, and a restart resets them.

### What the page exposes, and who can read it

**`/monitor` and its four routes are public and unauthenticated**, like
`/version`. On a deployment, anyone who can reach the URL can read them.

The statistics are aggregates by design: no route reports a username, an email
address, an IP address, or a per-user row. That is enforced by a test
(`test_monitor_payload_is_anonymous.py`) rather than by convention.

**The error log is the exception, and it is deliberate.** `GET
/api/monitor/errors` returns raw, unredacted failures so that whoever hits a
problem can share the whole picture without an operator in the loop. Those
entries will contain absolute server paths including the home directory of the
account Curio runs as, fragments of other users' node code, and any values
their tracebacks interpolated.

There is no redaction setting. If that exposure is not acceptable for your
deployment, block `/api/monitor/errors` (or `/monitor` as a whole) at the
reverse proxy. In Caddy:

```caddyfile
@monitor path /monitor /api/monitor*
respond @monitor 404
```

Browser error reports arrive on `POST /api/monitor/errors/client`, which is
also public. It is rate limited per address and globally, caps what it stores,
and keeps browser reports in a separate window from server-side failures, so
flooding it cannot push real errors out of the log.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Caddy: `permission denied` on key | `caddy` user can't read the private key. Fix perms (see Path B above). |
| `Loading failed for the <script> .../bundle.js` | Bundle built with wrong `PUBLIC_PATH`. Check `.env`, rebuild with `--no-cache`. |
| `SSL_ERROR_INTERNAL_ERROR_ALERT` | Caddy has no cert for that hostname. Check the Caddyfile block exists, DNS resolves, and (Path A) port 80 is reachable from the public internet. |
| `systemctl reload caddy` hangs | Caddy stuck in cert-fetch retry. Use `restart` instead, then check `journalctl -u caddy`. |
| Mixed-content errors in browser console | Bundle has an HTTP `BACKEND_URL` baked in. Update `.env`, rebuild with `--no-cache`. |
| Bundle still references old URL after deploy | Cached npm-build layer. Run `docker compose build --no-cache`. |
| Nodes fail and you cannot see why | Open `/monitor`. The error log there holds the last failures with their tracebacks, and survives longer than `.curio/messages.log`, which is truncated on every launch. |
| `/monitor` says the sandbox is unreachable | The sandbox process is down or not answering within 3s. The rest of the page stays current; check `docker compose logs curio`. |

## Security checklist

- **Decide who may read `/monitor`.** It is public and unauthenticated on every instance, and its error log carries raw tracebacks including server paths and fragments of user node code. Block it at the reverse proxy if that is not acceptable; see [The monitor page](#the-monitor-page).
- **Verify auth is on**: `docker compose logs curio | grep CURIO_NO_AUTH` must print `CURIO_NO_AUTH=0`. If it prints `1`, you started without the `docker-compose.deploy.yml` overlay and the instance is open to anyone.
- Set a real `SECRET_KEY`. Auth is on for any real deployment, so this is not optional.
- Keep `--no-allow-publish` (the overlay supplies it). Without it, any signed-in user can publish into or delete from the shared node catalog, and `DELETE /api/packages/catalog/<dirName>` performs no ownership check. See [NODE-CATALOG.md § Operator notes](NODE-CATALOG.md#operator-notes).
- Dataset publishing has no equivalent switch. Any signed-in user can publish into the shared Data Catalog; only the original publisher can unpublish or delete. See [DATA-CATALOG.md](DATA-CATALOG.md#operator-notes).
- **Library installs are on, and scoped per user.** With isolation on (below), an install goes to `.curio/exec-overlays/users/<key>/` rather than the interpreter every user's nodes share. Three limits: a user's tree is readable by other users' node code (the execution account is shared), there is no size quota, so disk is the operator's to watch, and the shared guest cannot install at all.
- **A deployment that cannot isolate does not start.** `--deploy` needs Linux, fork, setrlimit, pyseccomp and the `curio-exec` account; without them it exits with what is missing instead of serving accounts that share one interpreter. Run the Docker image, which has all of it, or drop `--deploy` and run Curio as the single-user tool it then is.
- **Verify the sandbox is not exposed**: `docker compose ps` must not list a published port for 2000. The sandbox executes arbitrary node code; only the backend inside the container should reach it. The image binds it to `127.0.0.1` and publishes nothing, so a published 2000 means a local override added one.
- **Verify the sandbox token is set**: `docker compose logs curio | grep CURIO_SANDBOX_TOKEN` must print `CURIO_SANDBOX_TOKEN=<set>` (the value itself is never logged). A deployment with auth on refuses to start without it.
- **Isolated node execution is on by default.** `--deploy` turns it on wherever the host can provide it: Linux, plus the unprivileged `curio-exec` account the image creates. Each node's Python then runs in a confined child process: memory and CPU capped, network and `ptrace` denied by seccomp, and no read access to `instance/` or `.curio/data`. `docker-compose.deploy.yml` also passes `CURIO_ISOLATION=fork`, which makes it **fail-closed**: if the sandbox cannot confine, it refuses to start. Without that variable a `--deploy` on a host that cannot isolate still boots, unisolated and saying so. The deploy workflow checks the result over `/version` and fails the deployment if it is not `fork`. To check a running instance yourself:

  ```bash
  docker compose -p curio exec -T curio curl -sf http://127.0.0.1:2000/version
  ```

  The `isolation` field must read `fork`. The version badge in the UI shows the same answer.
- **Isolation chmods several paths on the host, permanently.** At every boot the sandbox tightens the bind-mounted `./instance` to `0700` with its files at `0600`, the three stores `./.curio/data`, `./.curio/users` and `./datasets` to `0700`, and `./.env` to `0600`. It changes **modes only, never ownership**, so each path keeps whatever user created it. The three stores keep their *file* modes because a staged input reaches the child as a hardlink, which shares its source's inode. Any other host process that reads these paths, such as a backup job or an operator shell as a third user, loses access and needs to run as root or as the owning account.
- **The boundary is node code against the host, not user against user.** One OS account (`curio-exec`) is what every Curio user's nodes run as. What keeps two users' data apart is session scoping in the parent process, which no child can reach. Because all children share a uid, two nodes running concurrently can reach each other's scratch directories and find each other through `/proc`. Treat "another user's node ran at the same time" as within reach, and "another user's stored artifacts" as not, with one deliberate exception: the outputs a project SAVED are readable by anyone who can load that project, because that is what a shared dataflow or dashboard link shows.
- **Relative writes from node code land in a per-user work directory**, `.curio/exec-scratch/users/<key>/`, which is `0700` and owned by `curio-exec`. It persists between runs and is the only place a node may write; a relative write anywhere else fails, because the launch tree is root-owned. Node output still reaches the user's store, but through the parent's validated persist step rather than the child's filesystem access. Nothing cleans this directory automatically, so include it when you size the disk.
- **Node authoring is still close to shell access.** A node author cannot read `instance/urban_workflow.db` or another session's artifacts, and cannot open a socket, but can run arbitrary Python within the child's limits, and writes are bounded by ownership and `RLIMIT_FSIZE` rather than confined to a directory. Give accounts accordingly. See [ARCHITECTURE.md § Sandbox Isolation](ARCHITECTURE.md#sandbox-isolation).
- **To turn it off** (an incident, or a host where it cannot work), set `CURIO_ISOLATION=off` in `docker-compose.deploy.yml`'s environment and redeploy. Remove the `CURIO_ISOLATION=fork` line at the same time, or the fail-closed setting will keep winning. The permission changes above are not reverted by that; `chmod` them back by hand if something else needs them.
- `.env` is gitignored, but verify with `git status` after creating it.
- Back up `instance/urban_workflow.db`, `datasets/`, and `.curio/` regularly.
  `datalakes/` ships with the image and holds no user data, so it needs none.

