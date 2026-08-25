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
# CURIO_PORT_2000 is no longer used: the sandbox executes arbitrary node
# code and is no longer published. Harmless to leave in an existing .env.
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
| `.curio/` | Per-user stores, logs, sandbox artifacts | Yes, if users' imported datasets and computed outputs matter |

`packages/` is deliberately **not** mounted. The node catalog is baked into the
image so it always matches the deployed commit; a bind mount there let a single
UI publish rewrite the host's git checkout in place. See the comment block in
`docker-compose.yml` for the full story.

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
build. The CI workflow passes it for the same reason.

If a user published a package from the UI on an older build, `git pull` will
refuse to fast-forward because `packages/` is dirty. That mutation is exactly what
`--no-allow-publish` now prevents, so it is safe to discard:

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

Version bumps are automated by [`.github/workflows/bump-version.yml`](../.github/workflows/bump-version.yml), which owns `utk_curio/__init__.py`. It used to classify each release as minor-or-patch via GitHub Models; that service was retired on 2026-07-30, so the bump type is now explicit.

| You do | Bump | Tag | Deploys |
|---|---|---|---|
| Push to `main` (touching `utk_curio/**` or `docs/examples/**`) | patch | none | dev only |
| Actions → Bump version → Run workflow, `bump: minor` | minor | `vX.Y.0` | dev **and** stable |
| Actions → Bump version → Run workflow, `bump: major` | major | `vX.0.0` | dev **and** stable |

So a routine merge quietly ships to `curio-dev` and nothing else. Cutting a stable release is a deliberate act: dispatch the workflow with `minor` or `major`, and it bumps the version, tags the bump commit, and dispatches `deploy.yml` with `target: both` to put that exact tag on both stacks.

> [!NOTE]
> Pushes made with `GITHUB_TOKEN` never trigger workflows, which is why the bump job dispatches `deploy.yml` over the API rather than relying on its own commit to set things off. `workflow_dispatch` events are exempt from that recursion guard, so no PAT is needed.

To roll back, dispatch Deploy with `ref` set to the previous tag and `target: stable`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Caddy: `permission denied` on key | `caddy` user can't read the private key. Fix perms (see Path B above). |
| `Loading failed for the <script> .../bundle.js` | Bundle built with wrong `PUBLIC_PATH`. Check `.env`, rebuild with `--no-cache`. |
| `SSL_ERROR_INTERNAL_ERROR_ALERT` | Caddy has no cert for that hostname. Check the Caddyfile block exists, DNS resolves, and (Path A) port 80 is reachable from the public internet. |
| `systemctl reload caddy` hangs | Caddy stuck in cert-fetch retry. Use `restart` instead, then check `journalctl -u caddy`. |
| Mixed-content errors in browser console | Bundle has an HTTP `BACKEND_URL` baked in. Update `.env`, rebuild with `--no-cache`. |
| Bundle still references old URL after deploy | Cached npm-build layer. Run `docker compose build --no-cache`. |

## Security checklist

- **Verify auth is on**: `docker compose logs curio | grep CURIO_NO_AUTH` must print `CURIO_NO_AUTH=0`. If it prints `1`, you started without the `docker-compose.deploy.yml` overlay and the instance is open to anyone.
- Set a real `SECRET_KEY`. Auth is on for any real deployment, so this is not optional.
- Keep `--no-allow-publish` (the overlay supplies it). Without it, any signed-in user can publish into or delete from the shared node catalog, and `DELETE /api/packages/catalog/<dirName>` performs no ownership check. See [NODE-CATALOG.md § Operator notes](NODE-CATALOG.md#operator-notes).
- Dataset publishing has no equivalent switch. Any signed-in user can publish into the shared Data Catalog; only the original publisher can unpublish or delete. See [DATA-CATALOG.md](DATA-CATALOG.md#operator-notes).
- **Verify the sandbox is not exposed**: `docker compose ps` must not list a published port for 2000. The sandbox executes arbitrary node code; only the backend inside the container should reach it. The image binds it to `127.0.0.1` and publishes nothing, so a published 2000 means a local override added one.
- **Verify the sandbox token is set**: `docker compose logs curio | grep CURIO_SANDBOX_TOKEN` must print `CURIO_SANDBOX_TOKEN=<set>` (the value itself is never logged). A deployment with auth on refuses to start without it.
- **Treat node authoring as shell access.** Node code runs with `exec()` inside the sandbox process, as the same OS user, with unrestricted builtins and no resource limits. A user who can author or edit a dataflow node can read `instance/urban_workflow.db` (every password hash and session token) and anything else that process can reach. Only give accounts to people you would give a shell to. See [ARCHITECTURE.md § Sandbox Isolation](ARCHITECTURE.md#sandbox-isolation).
- **Consider isolated node execution.** `--isolation=fork --exec-user curio-exec` runs each node's Python in a confined child process (memory and CPU capped, no network, no read access to `instance/` or `.curio/data`) instead of in-process. It is off by default and Linux only. Without `--exec-user` there is no filesystem boundary, and the sandbox says so at startup. **Read the status note in [ARCHITECTURE.md](ARCHITECTURE.md#isolated-node-execution-opt-in-linux-only) before relying on it:** the confinement code has not yet been exercised outside CI.
- `.env` is gitignored, but verify with `git status` after creating it.
- Back up `instance/urban_workflow.db`, `datasets/`, and `.curio/` regularly.

