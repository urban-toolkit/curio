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
- [Troubleshooting](#troubleshooting)
- [Security checklist](#security-checklist)

## 1. Configure the stack

This step lays down the source tree and the configuration file that tells Docker which ports to use, where the public site will live, and how to reach Google OAuth. Everything Curio runs in production is driven from `/srv/curio/.env`, so getting this right up front saves a rebuild later.

Clone and create the data directories:

```bash
git clone https://github.com/urban-toolkit/curio.git /srv/curio
cd /srv/curio
mkdir -p instance .curio data templates
```

Create `/srv/curio/.env`:

```bash
CURIO_CONTAINER_NAME=curio
CURIO_PORT_2000=2000
CURIO_PORT_5002=5002
CURIO_PORT_8080=8080

# URL prefix the bundle expects. Must match the Caddy path in step 2.
PUBLIC_PATH=/curio/

# Public URL the bundle uses to reach the backend.
# No trailing slash, frontend code does `${BACKEND_URL}/live` etc.
BACKEND_URL=https://lab-name.your-uni.edu/curio/api

# Google OAuth (only if you want users to log in).
REDIRECT_URI=postmessage
CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
CLIENT_SECRET=your-google-oauth-client-secret
```

The four directories you created are bind-mounted into the container and persist across recreates: `instance/` holds the SQLite DB (users, projects, sessions, **back this up**), `data/` holds workflow artifacts (**back this up**), `.curio/` holds logs and sandbox files, `templates/` holds workflow templates exposed in the UI.

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

```bash
cd /srv/curio
docker compose build
docker compose up -d
```

Verify from outside the server:

```bash
curl https://lab-name.your-uni.edu/curio/api/live
```

Then load `https://lab-name.your-uni.edu/curio/` in a browser. If something looks off, `docker compose logs -f` shows the running container's output.

## Updating

Pulling new code is straightforward, but the `--no-cache` flag is important: Docker's layer cache occasionally fails to invalidate the npm-build step when build args change, which silently produces a frontend bundle still pointing at the old URL. Forcing a clean build is slower but guarantees correctness.

```bash
git pull
docker compose build --no-cache
docker compose up -d
```

After the deploy completes, hard-refresh the browser (Ctrl+Shift+R) to drop any cached JavaScript.

## Optional: dev stack alongside stable

A second checkout running on different ports under a different path lets you test changes without disrupting users. The two stacks share the hostname but live at separate URLs (`/curio/` for stable, `/curio-dev/` for dev) and run as separate Docker containers.

| | Stable | Dev |
|---|---|---|
| Path on server | `/srv/curio` | `/srv/curio-dev` |
| Container | `curio` | `curio-dev` |
| Ports | 2000 / 5002 / 8080 | 2010 / 5012 / 8090 |
| Public URL | `lab-name.your-uni.edu/curio/` | `lab-name.your-uni.edu/curio-dev/` |

Clone into `/srv/curio-dev`, write a parallel `.env` with `CURIO_PORT_*=2010/5012/8090`, `PUBLIC_PATH=/curio-dev/`, and `BACKEND_URL=https://lab-name.your-uni.edu/curio-dev/api`. Add two more `handle_path` blocks to the same Caddy site (`/curio-dev/api/*` → 5012, `/curio-dev/*` → 8090). Then:

```bash
cd /srv/curio-dev
docker compose -p curio-dev build
docker compose -p curio-dev up -d
```

The `-p curio-dev` flag isolates this stack's Compose project so it doesn't conflict with stable.

## Optional: CI/CD with GitHub Actions + Tailscale

The repo includes [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) for push-to-deploy via Tailscale, so the GitHub Actions runner can reach your server without exposing public SSH. This is overkill for a one-person deployment but useful when multiple people merge to `main` and you want each merge automatically reflected on the dev stack.

To adapt it: install Tailscale on the server (`sudo tailscale up --advertise-tags=tag:curio-server --ssh`), create a Tailscale OAuth client with the `auth_keys` scope and tag `tag:ci`, add an ACL allowing `tag:ci -> tag:curio-server:22`, create a `deploy` user on the server with the `docker` group, and set three GitHub secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `DEPLOY_SSH_KEY` (private key whose pubkey is in `~deploy/.ssh/authorized_keys`). Then update the hostname (`utk` → your Tailscale machine name) and the `BACKEND_URL` exports in the workflow file.

Pushing to `main` triggers the dev deploy. Stable runs manually via Actions → Deploy → Run workflow.

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

- Set a real `SECRET_KEY` if running with auth.
- `.env` is gitignored, but verify with `git status` after creating it.
- Back up `instance/urban_workflow.db` and `data/` regularly.
- Google OAuth client's authorized redirect URIs match your hostname.

