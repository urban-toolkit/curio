# Deployment

How to deploy Curio on a server you already have, behind HTTPS. For local development see [USAGE.md](USAGE.md) instead.

This guide deploys Curio under a `/curio` path prefix on a hostname you already control (e.g. `https://lab-name.your-uni.edu/curio/`). The path prefix lets you share the hostname with other apps. Replace `lab-name.your-uni.edu` with whatever hostname your server uses, the rest of the steps don't change.

Assumed setup: a Linux server with the hostname already pointing at it, Docker + Compose installed, and [Caddy](https://caddyserver.com) installed as the reverse proxy.

## Contents

- [1. Configure the stack](#1-configure-the-stack)
  - [LLM configurations](#llm-configurations)
  - [Model weights a package fetches](#model-weights-a-package-fetches)
  - [Bucket mounts](#bucket-mounts)
- [2. Configure Caddy](#2-configure-caddy)
- [3. Build and run](#3-build-and-run)
  - [The GPU](#the-gpu)
- [Updating](#updating)
- [Optional: dev stack alongside stable](#optional-dev-stack-alongside-stable)
- [Optional: CI/CD with GitHub Actions + Tailscale](#optional-cicd-with-github-actions--tailscale)
- [Cutting a release](#cutting-a-release)
- [The monitor page](#the-monitor-page)
- [Troubleshooting](#troubleshooting)
- [Security checklist](#security-checklist)

## 1. Configure the stack

This step lays down the source tree and `/srv/curio/docker-compose.site.yml`, the file that holds this site's settings.

Clone and create the data directories:

```bash
git clone https://github.com/urban-toolkit/curio.git /srv/curio
cd /srv/curio
mkdir -p instance .curio datasets
```

Create `/srv/curio/docker-compose.site.yml` with Curio's arguments for this site: the address the browser reaches the backend at, the path the app is served under, and the memory each node may allocate. The address and the path must match the Caddy paths in step 2. `--exec-memory-mb 24576` gives a node room to run PyTorch on the GPU: under the default 4096, `import torch` fails in a node. The `ports` line publishes the backend and the frontend on loopback only, so they are reached through Caddy (`!override` needs Docker Compose 2.24.4 or newer).

```yaml
services:
  curio:
    ports: !override ["127.0.0.1:5002:5002", "127.0.0.1:8080:8080"]
    command: ["--backend-url", "https://lab-name.your-uni.edu/curio/api", "--base-path", "/curio", "--exec-memory-mb", "24576"]
```

The three directories you created, `instance/`, `datasets/` and `.curio/`, are bind-mounted into the container and persist across recreates:

| Directory | Holds | Back up? |
|---|---|---|
| `instance/` | The SQLite DB: users, projects, sessions | **Yes** |
| `datasets/` | The shared Data Catalog: every dataset your users publish | **Yes** |
| `discovery/` | The Discovery Catalog's shipped sources: one manifest per portal or storage source. Ships with the image | No |
| `.curio/` | Per-user stores, logs, sandbox artifacts, each account's agent imports, catalog settings and LLM configurations, and your own sources in `.curio/discovery/` | Yes, if users' imported datasets, computed outputs and settings matter |

`packages/` is **not** mounted: the node catalog, with the Model Catalog's
shipped models as model packages, is baked into the image, so it always
matches the deployed commit. Neither is `discovery/`, whose shipped sources
match the deployed commit too. Pass `--packages-root` or `--discovery-root` to
`curio.py start` if you need them elsewhere. Models your users add live in their stores under `.curio/`. Sources of your own go in `.curio/discovery/`; see
[Storage sources](#storage-sources).

### Outbound requests

The Discovery Catalog is the one feature that makes outbound requests on a
user's behalf, so it is worth knowing what bounds them. Every URL - search,
describe, download, and each redirect hop - passes the same default-deny
address policy the agent tools use: https/http only, private, loopback,
link-local and reserved addresses refused *after* DNS resolution, and the
connected peer re-checked before any response body is read. A download started
from the Dataset Finder's card, or from an agent's approved proposal, is the
same download under the same policy.

What a deployment should know:

- **A source manifest can never exempt a host from that policy.** The one
  exemption in the codebase is for an operator-configured search provider, and
  this catalog does not use it.
- **The residual documented in `app/common/egress_policy.py` applies here
  too**: the request line and headers are on the wire before the peer can be
  confirmed, so a blind request to an internal service is not *prevented*, only
  its response is withheld. Closing that needs connection-factory work.
- **A user's key goes only to its source.** A key sent in a header goes to the
  host of the source's `baseUrl` and to nothing else: not to the image hosts
  Mapillary's photos come from, and not on a redirect to another origin. Google
  Street View's key, a query parameter, is added when each request is sent; the
  URLs a dataset, a job or the audit log records never hold it.
- **Hugging Face models** download up to 2 GB each, from the Hub's file
  storage after a redirect, through the same policy.
- **A download, or a table added from a bucket,** takes one file of up to
  `--discovery-max-download-mb` (1024 by default). **Cache files** copies a
  bucket collection's files one at a time, each of up to
  `--media-cache-max-file-gb` (4 by default) and all of an account's together
  up to `--media-cache-max-gb` (20 by default), both checked against the
  bucket's listing before a byte is fetched, and a file that sends more than
  its listing said is stopped. Raising either lets one user's click fetch that
  much from the bucket and keep it on this machine's disk.

Two sources reach OpenStreetMap:

- **Place search**, for the area of a download, asks Nominatim
  (`https://nominatim.openstreetmap.org`) through the same policy: at most one
  request a second for the whole server, each answer kept for a day, with a
  User-Agent naming Curio.
- **OpenStreetMap downloads** run Node.js from the backend, with autk-db from
  the sandbox's Node.js packages (see [Build and run](#3-build-and-run)), and autk-db sends its requests to
  `https://overpass-api.de` itself. They do not pass the address policy above.
  No value a user types becomes part of a URL: the area and the layers go in the
  request body, and a name with a quote, bracket, backslash or line break is
  refused. One
  download runs for at most 15 minutes and writes at most 512 MiB.

Rate limiting is per user, per source, and **in-process**; requests to buckets
and repositories are not counted, and an OpenStreetMap download counts once. Under several
workers the effective rate is the configured rate times the worker count. It is
a politeness mechanism toward portals you do not own and a brake on accidental
loops, not a guarantee you can make to a third party.

### LLM configurations

Curio ships no LLM endpoint. Users add their own LLM configurations in API
Settings; the deployment can offer endpoints of its own on top, in an
endpoint file that only the backend reads, named by `--llm-endpoint-file`.
It is the one LLM setting.

The file holds one section per endpoint. The section's name is what users
see in API Settings, under **Curio**: a section named `[Lab gateway]` reads
**Provided by Lab gateway**.

```ini
[Lab gateway]
base_url=https://llm.example.org/v1
api_key=<the gateway's key>
models=model-a,model-b

[Local Ollama]
base_url=http://localhost:11434/v1
api_key=ollama
models=llama3.2

[Anthropic]
provider=anthropic
api_key=<an Anthropic key>
models=claude-haiku-4-5
```

| Line | What it sets |
|---|---|
| `api_key` | The endpoint's key. Required; a keyless server such as Ollama takes any placeholder. |
| `models` | The models it offers, comma-separated. Required. |
| `base_url` | Its URL. Leave it out for the provider's own endpoint. |
| `provider` | `openai_compatible` (the default), `anthropic` or `gemini`. |

Lines starting with `#` or `;` are comments. Each section is a read-only
**Curio** row on the **API keys** tab of every user's API Settings, listing
its models, and a signed-in user can pick any of them, as their default or for
one agent, on the **Agent configuration** tab. The first section's first model
is **Curio's default**: it answers for any user who has not chosen a default
of their own, and it is the **guest configuration** every guest answers with.
To change it for everyone, reorder the file and recreate the stack. No
endpoint's key or address reaches a browser.

To set it up on a server:

1. Write the file outside the checkout, or in a folder git and Docker ignore,
   readable by its owner only: `chmod 600 llm-endpoints`.
2. Mount it read-only into the container and pass its path in the `command:`
   of `docker-compose.site.yml`:

   ```yaml
   services:
     curio:
       secrets:
         - llm_endpoints
       command: ["--llm-endpoint-file", "/run/secrets/llm_endpoints"]
   secrets:
     llm_endpoints:
       file: /srv/secrets/llm-endpoints
   ```

3. Recreate the stack. Signed-in users then see one **Curio** row per section
   on the **API keys** tab, the first model marked **Curio default**, and the
   **Agent configuration** tab offers every model under **Curio ·** and the
   section's name.

The start stops with a message naming the section when the file is missing
or cannot be read, when a section lacks `api_key` or `models`, names an
unknown provider or line, or repeats a model, a line or a section, and, under
`--deploy`, when the execution account could read the file. The frontend,
the sandbox and node code never see the file, its path or its values.

Each user's configurations, keys included, are kept in
`.curio/users/<user>/llm-configs.json`, a 0600 file in a 0700 directory. The
keys are not encrypted at rest, and the file is backed up with `.curio/`.

> [!TIP]
> `datasets/` lives inside the git checkout, so publishing a dataset dirties your
> working tree. To avoid that, point the catalog at a path outside the checkout
> with `CURIO_CATALOG_ROOT` (or `--catalog-root`) and mount that path instead.

### Storage sources

A storage source lists a folder, a public S3 bucket or a Hugging Face dataset
repository in the Discovery Catalog. The manifest format is in
[DISCOVERY-CATALOG.md § The manifest](DISCOVERY-CATALOG.md#8-the-manifest).

- **Your own sources** go in
  `.curio/discovery/<sourceId>@<major>/manifest.json`, which the `./.curio`
  mount keeps across image rebuilds. A source whose folder name a shipped one
  uses is not listed, and the log says so. A `folder` source's `root` must be
  absolute. Under `--deploy`, node code cannot write to this directory.
- **Mount a folder read-only.** Curio never writes to one. Add the mount in a
  compose override and give the manifest the path inside the container:

  ```yaml
  services:
    curio:
      volumes:
        - /srv/media/urban-sensing:/data/urban-sensing:ro
  ```

  ```json
  { "provider": { "type": "folder", "root": "/data/urban-sensing" } }
  ```

- **`curio-exec` must be able to read it.** Under `--deploy`, node code runs as
  `curio-exec`, so every directory on the way to the files needs `o+x` and the
  files `o+r` (or a group `curio-exec` is in). At boot the backend logs each
  folder source it cannot read, with the folder or file that stops it.
- **Buckets and repositories** are read through the same outbound policy as the
  portals: public S3 buckets, and Hugging Face dataset repositories, with the
  account's token for one that needs it. `limits.requestsPerMinute` does not
  apply to them.
- **Disk.** A bucket collection's files are cached per account on request,
  under `.curio/exec-scratch/users/<key>/media/objects/` with isolation on and
  `.curio/users/<key>/media/objects/` without. `--media-cache-max-gb`
  (default 20) caps each account, and `--media-cache-max-file-gb` (default 4)
  each file; a collection over either is refused before any file is copied.
  Thumbnails, posters and spectrograms are
  cached under `.curio/users/<key>/media-cache/`, and a storage row's sample
  thumbnails under `.curio/discovery-cache/`. Deleting a collection removes
  its caches, never the source's files. With isolation on, the cached files
  and the frames, videos, clips, tables and mosaics nodes derive are in the
  account's work directory, which other accounts' node code can read: the
  execution account is shared (see the [security checklist](#security-checklist)).
- **Libraries.** Probing and thumbnails use `av` (PyAV) and `rasterio`, which
  are dependencies of `curio.builtin@1`. Curio installs them when it starts,
  and so does `python curio.py setup`.

### Model weights a package fetches

A model package whose manifest has a `model.fetch` block ships without its
weights ([MODEL-CATALOG.md § The manifest](MODEL-CATALOG.md#6-the-manifest)).
Until you fetch them, a node that loads the model stops and names the command
below, and the model's details in the Model Catalog say *Not on this Curio*.
Fetch them once on the server, from the checkout of the release you deploy:

1. Sign in at [huggingface.co](https://huggingface.co), open the repository the
   manifest's `fetch.huggingface` names, and accept its terms if it asks.
2. Create a token with read access at
   [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
3. Fetch the weights into a folder of the host, with the token in that one
   command's environment:

   ```bash
   cd /srv/curio
   read -rs HF_TOKEN
   HF_TOKEN="$HF_TOKEN" python3 scripts/fetch_model_weights.py <package id> --into /srv/curio/model-weights
   unset HF_TOKEN
   ```

   `read -rs` takes the token without showing it or keeping it in the shell's
   history. The script prints each file's name and size as it lands, checks
   each against the digest the manifest names, and skips a file already in
   place, so you run it again after an update that changes the files. A
   refusal from Hugging Face says how to get access.
4. Pass `--model-weights-dir` to `curio.py start`. `docker-compose.deploy.yml`
   mounts the checkout's `model-weights/` read-only at `/model-weights`, so add
   to the `command` in `docker-compose.site.yml`:

   ```yaml
       command: ["--backend-url", "https://lab-name.your-uni.edu/curio/api", "--base-path", "/curio", "--exec-memory-mb", "24576", "--model-weights-dir", "/model-weights"]
   ```

   To keep the weights in another host folder, such as one that two stacks
   share, mount it there in `docker-compose.site.yml` and fetch with `--into`
   that folder:

   ```yaml
       volumes: ["/srv/curio-model-weights:/model-weights:ro"]
   ```
5. Recreate the stack (`docker compose up -d --force-recreate`). The model's
   details no longer say *Not on this Curio*.

- **Every account must be able to read the folder.** Isolated node code reads
  the weights in place, as `curio-exec`. The script makes its folders `755`
  and its files `644`, and says so when `--into` names a folder that is not.
- **Without `--model-weights-dir`**, Curio reads the weights from the
  package's own folder, `packages/<package id>@<major>/models/`, where the
  script puts them without `--into`: for a clone run with `curio.py start`.
- **The token** is read from `HF_TOKEN` alone, sent only to huggingface.co,
  and never printed or saved.
- Git, the image and the pip package hold none of these weights, and
  **Export**, **Publish** and **Save as package node** refuse such a model.

### Bucket mounts

`docker-compose.bucket-mounts.yml` runs a mount service for buckets beside
Curio: rclone in a container of its own, `bucket-mounts`, which mounts buckets
read-only with FUSE. It is the one container with FUSE's privileges:
`/dev/fuse`, `SYS_ADMIN`, and an AppArmor profile of its own, Docker's default
profile for containers with FUSE mounts and unmounts allowed under the
service's `/mounts` alone.

Before a stack starts with it, the host needs three things, set up once:

1. **The FUSE device.** This prints a line that starts with `c`:

   ```bash
   ls -l /dev/fuse
   ```

2. **A shared mount where the mounts live**, as systemd makes `/`. For a
   folder under `/srv`, this prints `shared`:

   ```bash
   findmnt -n -o PROPAGATION -T /srv
   ```

3. **The service's AppArmor profile, loaded.** Docker refuses to start the
   service until the kernel has it. Install and load it as root, then check:

   ```bash
   cd /srv/curio
   sudo install -m 644 scripts/bucket-mounts/curio-bucket-mounts.apparmor /etc/apparmor.d/curio-bucket-mounts
   sudo apparmor_parser -r -W /etc/apparmor.d/curio-bucket-mounts
   sudo aa-status | grep curio-bucket-mounts
   ```

   The last command prints `curio-bucket-mounts`. The profile loads again at
   every boot. When an update changes
   `scripts/bucket-mounts/curio-bucket-mounts.apparmor`, run the `install` and
   `apparmor_parser` lines again. Every stack on the host uses this one
   profile, the [dev stack](#optional-dev-stack-alongside-stable) too.

## 2. Configure Caddy

Caddy terminates HTTPS and forwards traffic into the Docker container. The two `handle_path` blocks below split incoming requests by URL prefix: anything under `/curio/api/` goes to the backend on port 5002, everything else under `/curio/` goes to the frontend on port 8080. The `handle_path` directive strips the prefix before forwarding, so your backend code sees normal paths like `/live` and `/upload`.

The backend's WebSocket connections, which collaboration travels over, are at the backend's address plus `/socket.io` (here `/curio/api/socket.io/`). Caddy's `reverse_proxy` passes their upgrade as it is. Another reverse proxy must forward the `Upgrade` and `Connection` headers on that path.

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

This is where the frontend bundle gets compiled. The first build takes 10-15 minutes because it has to install Python and Node dependencies and run the full webpack build, subsequent builds are faster thanks to layer caching.

The build also installs the sandbox's Node.js packages (autk-db) into `node_modules/` beside the repository's `package.json`; `curio.py start` runs `npm install` there on every start.

> [!WARNING]
> **Always deploy with both compose files.** `docker-compose.yml` alone starts
> Curio the way a local dev instance starts: the image's default command has no
> `--deploy`, so [`cli/environment.py`](../utk_curio/cli/environment.py) sets `CURIO_NO_AUTH=1` and
> **anyone who can reach the URL gets straight in with no login**. The
> [`docker-compose.deploy.yml`](../docker-compose.deploy.yml) overlay is what adds
> `--deploy` (auth + projects on), `--no-allow-publish` (locks the author-only
> catalog mutators), and `restart: unless-stopped`, and `docker-compose.site.yml`
> adds the site's own arguments. Exporting `COMPOSE_FILE` once
> per shell applies it to every later `docker compose` command.

```bash
cd /srv/curio
export COMPOSE_FILE=docker-compose.yml:docker-compose.deploy.yml:docker-compose.site.yml
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

**Run one backend process.** The backend keeps each open dataflow's live copy, the one everyone editing it shares, in its own memory. So one backend process serves a deployment's data directories: never run a second process, worker or replica on them, where each would keep its own copy of a dataflow and the two would drift apart.

### The GPU

On x86_64 the image carries PyTorch and torchvision built for CUDA 12.9, with CUDA 12.9's runtime libraries and NVRTC, which node code uses with nothing to install. A container gets the GPU from the host, which needs:

- an NVIDIA driver, 525 or newer (`nvidia-smi` prints its version);
- the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), set up for Docker. Restarting Docker stops every container on the host until it is back:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

This lists the GPU when a container can get it:

```bash
docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility python:3.12-slim nvidia-smi -L
```

`docker-compose.deploy.yml` asks Docker for the host's GPUs, and Docker refuses to start the stack on a host that cannot hand them over. On a host with no NVIDIA GPU, add this line to the `curio` service in `docker-compose.site.yml`, which takes the request back:

```yaml
    deploy: !reset {}
```

## Updating

Pull the new code, then rebuild and recreate:

```bash
cd /srv/curio
export COMPOSE_FILE=docker-compose.yml:docker-compose.deploy.yml:docker-compose.site.yml
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
| Compose project | `curio` | `curio-dev` |
| Published ports | 5002 / 8080 | 5012 / 8090 |
| Public URL | `lab-name.your-uni.edu/curio/` | `lab-name.your-uni.edu/curio-dev/` |

Clone into `/srv/curio-dev` and write its `docker-compose.site.yml`, which also moves the stack to host ports of its own:

```yaml
services:
  curio:
    ports: !override ["127.0.0.1:5012:5002", "127.0.0.1:8090:8080"]
    command: ["--backend-url", "https://lab-name.your-uni.edu/curio-dev/api", "--base-path", "/curio-dev", "--exec-memory-mb", "24576"]
```

Add two more `handle_path` blocks to the same Caddy site (`/curio-dev/api/*` → 5012, `/curio-dev/*` → 8090). Then:

```bash
cd /srv/curio-dev
export COMPOSE_FILE=docker-compose.yml:docker-compose.deploy.yml:docker-compose.site.yml
docker compose -p curio-dev build
docker compose -p curio-dev up -d --force-recreate
```

The `-p curio-dev` flag isolates this stack's Compose project so it doesn't conflict with stable.

**Every dev deploy starts the dev stack empty.** When [`deploy.yml`](#optional-cicd-with-github-actions--tailscale) deploys to `/srv/curio-dev`, it deletes `instance/`, `.curio/` and the datasets accounts published into `datasets/`. Accounts, projects and every stored file are gone after each deploy. The stable deploy keeps all three.

## Optional: CI/CD with GitHub Actions + Tailscale

The repo includes [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) for push-to-deploy via Tailscale, so the GitHub Actions runner can reach your server without exposing public SSH. This is overkill for a one-person deployment but useful when multiple people merge to `main` and you want each merge automatically reflected on the dev stack.

To adapt it: install Tailscale on the server (`sudo tailscale up --advertise-tags=tag:curio-server --ssh`), create a Tailscale OAuth client with the `auth_keys` scope and tag `tag:ci`, add an ACL allowing `tag:ci -> tag:curio-server:22`, create a `deploy` user on the server with the `docker` group, and set three GitHub secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `DEPLOY_SSH_KEY` (private key whose pubkey is in `~deploy/.ssh/authorized_keys`). Then update the hostname (`utk` → your Tailscale machine name) and the `--backend-url` addresses the workflow writes into each stack's `docker-compose.site.yml`.

To give both stacks an LLM endpoint of their own (the **Curio** rows and Curio's default in [LLM configurations](#llm-configurations)):

1. In the repository's **Settings → Environments**, open `dev` and add the secrets `CURIO_DEPLOY_API_KEY` (the endpoint's key) and `CURIO_DEPLOY_BASE_URL` (its OpenAI-compatible base URL). Do the same for `stable`.
2. In **Settings → Secrets and variables → Actions → Variables**, add the repository variable `CURIO_DEPLOY_MODELS`, a JSON list of the endpoint's model names, such as `["model-a", "model-b"]`. The first is Curio's default.
3. Deploy. Each deploy writes the two secrets and the models as one endpoint, the section `[Electronic Visualization Lab]`, to `.secrets/llm-endpoint` in the stack's checkout, a file only the `deploy` user reads, and starts the stack with `--llm-endpoint-file`. The job's log masks the URL and its host.
4. Sign in to the stack and open **API Settings**: the **API keys** tab shows the **Curio** row, **Provided by Electronic Visualization Lab**, with the first model marked **Curio default**.

Without both secrets, the deploy removes `.secrets/llm-endpoint` and the stack has no endpoint of its own.

Both stacks mount `/srv/curio-model-weights` read-only at `/model-weights` and start with `--model-weights-dir /model-weights`: fetch a model's weights there once ([Model weights a package fetches](#model-weights-a-package-fetches)), with `--into /srv/curio-model-weights`.

Both stacks also start with `--media-cache-max-file-gb 8`, so **Cache files** copies the SideSeeing walks, videos of up to 7 GiB, from data.urbantk.org. Each account still holds at most 20 GB of cached files.

They also start with `--discovery-max-download-mb 2048`, so a download, or a file of a bucket table, may be up to 2 GiB on them: a month of detections in data.urbantk.org's `idot` bucket is a JSON Lines file of up to 1.7 GB.

A merge to `main` deploys the dev stack once: Bump version bumps the patch version and dispatches the dev deploy of that commit. Stable runs manually via Actions → Deploy → Run workflow.

`deploy.yml` takes two inputs: `ref` (branch, tag, or SHA; empty deploys the latest `v*` tag) and `target` (`both` / `dev` / `stable`). Both jobs check out the requested ref and rebuild with `--no-cache --force-recreate`.

## Cutting a release

Version bumps are automated by [`.github/workflows/bump-version.yml`](../.github/workflows/bump-version.yml), which owns `utk_curio/__init__.py`. The bump type is explicit:

| You do | Bump | Tag | Deploys |
|---|---|---|---|
| Push to `main` (touching anything the deployed image holds) | patch | none | dev only |
| Actions → Bump version → Run workflow, `bump: minor` | minor | `vX.Y.0` | dev **and** stable |
| Actions → Bump version → Run workflow, `bump: major` | major | `vX.0.0` | dev **and** stable |

So a routine merge quietly ships to `curio-dev` and nothing else. Cutting a stable release is a manual step: dispatch the workflow with `minor` or `major`, and it bumps the version, tags the bump commit, and dispatches `deploy.yml` with `target: both` to put that exact tag on both stacks.

> [!NOTE]
> Pushes made with `GITHUB_TOKEN` never trigger workflows, which is why the bump job dispatches `deploy.yml` over the API rather than relying on its own commit to set things off. `workflow_dispatch` events are exempt from that recursion guard, so no PAT is needed.

To roll back, dispatch Deploy with `ref` set to the previous tag and `target: stable`.

## The monitor page

Every instance serves `/monitor`, a page that reports what the deployment is
doing and what has recently gone wrong. It exists on a laptop and on a server
alike; there is no flag to turn it on. The top bar's **Monitor** opens it; on
the canvas and the dashboard it opens the same content on the right side, and
the dataflow stays open.

It shows:

- **Deployment** - version, the requested and active isolation mode, and which
  optional features are configured. Settings that have a value somebody chose
  (the execution account, and whether Curio offers LLM models of its own) are
  reported only as "configured" or "none", never as their value.
- **Hardware** - CPU model and core count, memory, swap, load average (raw and
  per core), and the resident memory of the backend and sandbox processes. The
  hostname is not reported. Under it, **Open files** charts the files,
  sockets and pipes the backend and the sandbox hold open, sampled every hour
  from the backend's start, against their limit as a dashed line (one per
  server when the two differ), on a log scale. A sample above 80% of a
  server's limit adds an entry to Recent errors, and the next one comes only
  after that server's count has fallen below 70%. Past its limit, each file or
  connection a server opens fails with `[Errno 24] Too many open files`.
- **Execution** - node runs since launch, failures, a duration histogram, how
  many isolated slots are busy, and a tally of how child processes died
  (timeout, OOM, CPU limit, refused confinement).
- **LLM tokens** - each model's input and output tokens per hour over the last
  7 days, as two charts, and a table of each model's tokens over the last 24
  hours, the last 7 days and everything kept, with its requests. Each model is
  marked as running on Curio's own endpoint or on a key a user set for their
  own.
- **Accounts and content** - account, session, sign-in, project and dataset
  counts.
- **Storage** - disk usage across the `.curio` tree, as a distribution over
  user stores plus a per-area breakdown. A file with several names counts
  once, in the first area that holds it (users, then data).
- **Recent errors** - the last failures from node executions, the sandbox, the
  backend, and the browser.

"Copy diagnostics" puts the whole picture on the clipboard as markdown, ready
to paste into an issue; "Download" saves the same thing as JSON.

Every figure is since the process started, which is why uptime is on the page,
and a restart resets them. The LLM tokens are also written to
`.curio/monitor/llm-tokens.json` as they are counted, and the open-files
samples to `.curio/monitor/open-files.json`. Each file holds at most the last
90 days, and a restart starts it over.

### What the page exposes, and who can read it

**`/monitor` and its six routes are public and unauthenticated**, like
`/version`. On a deployment, anyone who can reach the URL can read them.

The statistics are aggregates: no route reports a username, an email address,
an IP address, or a per-user row. The LLM tokens section names the models that
answered: Curio's own, and the ones users set for their own keys. A model name
that looks like a URL, a host, an email address, an IP address or a key, or
that has spaces, shows as `other`.

**The error log is the exception.** `GET /api/monitor/errors` returns raw,
unredacted failures. Those
entries will contain absolute server paths including the home directory of the
account Curio runs as, fragments of other users' node code, and any values
their tracebacks interpolated.

There is no redaction setting. If that exposure is not acceptable for your
deployment, block the page and its API at the reverse proxy. In the Caddy site
of step 2, add:

```caddyfile
handle /curio/monitor* { respond 404 }
handle /curio/api/api/monitor* { respond 404 }
```

Browser error reports arrive on `POST /api/monitor/errors/client`, which is
also public. It is rate limited per address and globally, caps what it stores,
and keeps browser reports in a separate window from server-side failures, so
flooding it cannot push real errors out of the log.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Caddy: `permission denied` on key | `caddy` user can't read the private key. Fix perms (see Path B above). |
| `Loading failed for the <script> .../bundle.js` | `--base-path` in `docker-compose.site.yml` does not match the Caddy path. Fix it and run `docker compose up -d --force-recreate`. |
| `SSL_ERROR_INTERNAL_ERROR_ALERT` | Caddy has no cert for that hostname. Check the Caddyfile block exists, DNS resolves, and (Path A) port 80 is reachable from the public internet. |
| `systemctl reload caddy` hangs | Caddy stuck in cert-fetch retry. Use `restart` instead, then check `journalctl -u caddy`. |
| Mixed-content errors in browser console | `--backend-url` in `docker-compose.site.yml` is an `http://` address. Use the `https://` one and run `docker compose up -d --force-recreate`. |
| `could not select device driver "nvidia"` when the stack starts | The host has no NVIDIA Container Toolkit, or no NVIDIA GPU. Set up the toolkit ([The GPU](#the-gpu)), or add `deploy: !reset {}` to the `curio` service in `docker-compose.site.yml`. |
| A node that imports torch fails with `failed to map segment from shared object` | Its memory budget is too small for PyTorch's CUDA libraries. Pass `--exec-memory-mb 24576` in `docker-compose.site.yml`. |
| A node says *The weights of model '...' are not on this Curio* | Its model's weights are fetched, and this stack has none: run the script the message names on the host, with `--into` the folder the stack mounts at `/model-weights` ([Model weights a package fetches](#model-weights-a-package-fetches)). |
| `docker compose up` cannot start `bucket-mounts` | The host lacks one of the three things [Bucket mounts](#bucket-mounts) checks: `/dev/fuse`, a shared mount where the mounts live, or the loaded AppArmor profile. |
| `/monitor` shows **Bucket mounts** *unavailable* | Curio's test of the mount service failed, for the reason the line gives. Recent errors holds the details, and `docker compose logs bucket-mounts` the service's side. |
| Nodes fail and you cannot see why | Open `/monitor`. The error log there holds the last failures with their tracebacks, and survives longer than `.curio/messages.log`, which is truncated on every launch. |
| `/monitor` says the sandbox is unreachable | The sandbox process is down or not answering within 3s. The rest of the page stays current; check `docker compose logs curio`. |

## Security checklist

- **Decide who may read `/monitor`.** It is public and unauthenticated on every instance, and its error log carries raw tracebacks including server paths and fragments of user node code. Block it at the reverse proxy if that is not acceptable; see [The monitor page](#the-monitor-page).
- **Anyone with a dashboard link can start runs**, whatever the guest setting. A tile with no saved output runs the nodes before it when the page opens, and a viewer who changes a pinned control runs the dataflow again, on the server, with its owner's data, models and packages and never the owner's keys; a viewer never changes the dataflow. The limits are fixed: 10 runs a minute per visitor address of the values visitors try and 120 overall (opening the page costs nothing), two runs at once per dashboard, and half the isolated pool (`--exec-parallelism`) for every viewer's nodes together. What a run makes is kept 7 days, at most 2 GiB of viewers' runs per dashboard, and made again by the next visit that needs it. To refuse such runs, block the backend's `/api/projects/<id>/dashboard/runs` at the reverse proxy.
- **Guests' work is kept until the backend starts again.** Every guest signs in to one shared account. What a guest changes in an example, and each dataflow it makes with File > New, is a folder of its own under `.curio/users/guest/projects/` that only that guest's sign-in opens, and the files it uploads and the datasets it downloads go to that account's store, listed for that guest alone. Each start of the backend deletes them all, and there is no quota between two starts. A guest's agents run its own dataflows on the server, under the limits of isolated node execution below.
- **Say how many proxies add `X-Forwarded-For`.** The limits per visitor address (sign-in attempts, the monitor's error reports, a dashboard's runs) read the address there when `--proxy-hops N` names the proxies in front of the backend that add it; the overlay passes 1, for the site's Caddy. Pass one more for each other proxy that adds it, such as a CDN in front of Caddy, and keep the backend reachable only through them. Without the flag the header is not read, and each request counts as the address it came from.
- **Verify auth is on**: `docker compose logs curio | grep CURIO_NO_AUTH` must print `CURIO_NO_AUTH=0`. If it prints `1`, you started without the `docker-compose.deploy.yml` overlay and the instance is open to anyone.
- Keep `--no-allow-publish` (the overlay supplies it). Without it, any signed-in user can publish into the shared node catalog, including over a package already there. See [NODE-CATALOG.md § Operator notes](NODE-CATALOG.md#operator-notes).
- `--no-allow-publish` covers the shared Data Catalog too. Without it, any signed-in user other than a guest can publish a dataset there; only the original publisher can unpublish or delete it. See [DATA-CATALOG.md](DATA-CATALOG.md#operator-notes).
- `--no-allow-publish` covers the shared Agent Catalog as well. Without it, any signed-in user can publish an agent they imported there. See [AGENT-CATALOG.md](AGENT-CATALOG.md#operator-notes).
- `--no-allow-publish` covers the skills the Skill Catalog shares too. Without it, any signed-in user other than a guest can publish a skill they imported there; only its publisher can publish over it or unpublish it. See [SKILL-CATALOG.md](SKILL-CATALOG.md#operator-notes).
- **Library installs are on, and scoped per user.** With isolation on (below), an install goes to `.curio/exec-overlays/users/<key>/` rather than the interpreter every user's nodes share. Three limits: a user's tree is readable by other users' node code (the execution account is shared), there is no size quota, so disk is the operator's to watch, and the shared guest cannot install at all.
- **Keys saved without `--deploy` are not used with it.** Without `--deploy`, Curio signs everyone in as the shared guest, which saves data source keys and node code keys like any account. Started with `--deploy` on the same `.curio/` and database, Curio sends none of them, and guests cannot save new ones. The keys stay where they are, and a later run without `--deploy` uses them again.
- **A deployment that cannot isolate does not start.** `--deploy` needs Linux, fork, setrlimit, pyseccomp and the `curio-exec` account; without them it exits with what is missing instead of serving accounts that share one interpreter. Run the Docker image, which has all of it, or drop `--deploy` and run Curio as the single-user tool it then is.
- **Verify the sandbox is not exposed**: `docker compose ps` must not list a published port for 2000. The sandbox executes arbitrary node code; only the backend inside the container should reach it. The image binds it to `127.0.0.1` and publishes nothing, so a published 2000 means a local override added one.
- **Verify the sandbox token is set**: `docker compose logs curio | grep CURIO_SANDBOX_TOKEN` must print `CURIO_SANDBOX_TOKEN=<set>` (the value itself is never logged). A deployment with auth on refuses to start without it.
- **Isolated node execution is on.** `--deploy` turns it on: Linux, plus the unprivileged `curio-exec` account the image creates. Each node's Python then runs in a confined child process: memory and CPU capped, network, `ptrace` and new sessions or process groups denied by seccomp, and no read access to `instance/` or `.curio/data`. Every process a node starts ends when the node does: when it returns, fails or reaches its time limit. `docker-compose.deploy.yml` also passes `CURIO_ISOLATION=fork`, which makes the sandbox **fail-closed** too: if it cannot confine, it refuses to start. The deploy workflow checks the result over `/version` and fails the deployment if it is not `fork`. To check a running instance yourself:

  ```bash
  docker compose -p curio exec -T curio curl -sf http://127.0.0.1:2000/version
  ```

  The `isolation` field must read `fork`. The version badge in the UI shows the same answer.
- **Every process a JavaScript node starts ends when the node does**: when it returns, fails or reaches its time limit, a `detached` one too. On Linux, seccomp denies Node and every process it starts a new session or process group: `setsid` and `setpgid` fail with `EPERM`, and a `detached` child starts in Node's process group. With `CURIO_ISOLATION=fork`, a JavaScript node fails instead of running where that filter cannot be installed. On Windows, only Node itself is stopped.
- **Isolation chmods several paths on the host, permanently.** At every boot the sandbox tightens the bind-mounted `./instance` to `0700` with its files at `0600`, the three stores `./.curio/data`, `./.curio/users` and `./datasets` to `0700`. It changes **modes only, never ownership**, so each path keeps whatever user created it. The three stores keep their *file* modes because a staged input reaches the child as a hardlink, which shares its source's inode. The one file the sandbox gives an owner is a node's output: once it moves into `./.curio/data`, it belongs to the account the sandbox runs as, at `0644`, so no later node can write it. Any other host process that reads these paths, such as a backup job or an operator shell as a third user, loses access and needs to run as root or as the owning account.
- **The boundary is node code against the host, not user against user.** One OS account (`curio-exec`) is what every Curio user's nodes run as. What keeps two users' data apart is session scoping in the parent process, which no child can reach. Because all children share a uid, two nodes running concurrently can reach each other's scratch directories and find each other through `/proc`. Treat "another user's node ran at the same time" as within reach, and "another user's stored artifacts" as not, with one exception: the outputs a project SAVED are readable by anyone who can load that project, because that is what a shared dataflow or dashboard link shows.
- **Relative writes from node code land in a per-user work directory**, `.curio/exec-scratch/users/<key>/`, which is `0700` and owned by `curio-exec`. It persists between runs and is the only place a node may write; a relative write anywhere else fails, because the launch tree is root-owned. Node output still reaches the user's store, but through the parent's validated persist step rather than the child's filesystem access. Nothing cleans this directory automatically, so include it when you size the disk.
- **`.curio/data` holds a week of results.** Every node's output is kept there 7 days after it was made, saved or not, and a sweep every 6 hours removes what is older. A saved output stays in its account's Data Catalog under `.curio/users`, which keeps it. Size the disk for a week of runs, plus the saved outputs.
- **Node authoring is still close to shell access.** A node author cannot read `instance/urban_workflow.db` or another session's artifacts, cannot open a socket, and cannot start a process in a new session or process group (`subprocess.Popen(start_new_session=True)` raises `PermissionError`), but can run arbitrary Python within the child's limits, and writes are bounded by ownership and `RLIMIT_FSIZE` rather than confined to a directory. Give accounts accordingly. See [ARCHITECTURE.md § Sandbox Isolation](ARCHITECTURE.md#sandbox-isolation).
- **To turn it off** (an incident, or a host where it cannot work), set `CURIO_ISOLATION=off` in `docker-compose.deploy.yml`'s environment and redeploy. Remove the `CURIO_ISOLATION=fork` line at the same time, or the fail-closed setting will keep winning. The permission changes above are not reverted by that; `chmod` them back by hand if something else needs them.
- `docker-compose.site.yml` is gitignored, but verify with `git status` after creating it.
- Back up `instance/urban_workflow.db`, `datasets/`, and `.curio/` regularly.
  `discovery/` ships with the image and holds no user data, so it needs none;
  your own sources are in `.curio/discovery/`, and a folder source's files are
  wherever you mounted them from.
- **A folder source is readable by every signed-in user**, through its source
  rows and the collections they add. Mount only what all of them may see.
- **Fetched model weights are readable by every node.** Isolated node code
  reads the folder `--model-weights-dir` names in place, so any node code can
  open the weights there by their path, not only the nodes of an account that
  added the model.

