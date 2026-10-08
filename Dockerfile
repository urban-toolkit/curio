# -----------------------------------------------------------------------------
# Stage 1: Unified Python service (no Node required)
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime_base

ENV PYTHONUNBUFFERED=1 LOG_TO_STDOUT=true
WORKDIR /app

# Node 26, not 24: from 24.17 on, Node 24's bundled undici crashes the sandbox's
# PBF downloads with assert(!this.paused) (nodejs/undici#5360, fixed in undici
# 8.6; see utk_curio/sandbox/app/worker.py). Node 26 bundles undici 8.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gdal-bin libsm6 libxext6 ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_26.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Repo-root node_modules for the sandbox's Node.js subprocess
# (@urban-toolkit/autk-db — see utk_curio/sandbox/app/worker.py).
# Early layer: only rebuilds when the root lockfile changes; the
# npm install in utk_curio/cli/dependencies.py::_ensure_root_node_modules at container
# start then becomes a fast idempotent no-op.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Before the source, so a code change reuses this layer: pip needs nothing but
# the requirements file, and reinstalling everything on every commit was most
# of a build.
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install --prefer-binary --no-cache-dir -r requirements.txt

COPY curio.py ./
# pyproject.toml / MANIFEST.in are what carry utk_curio/llm-prompts (not an
# importable package -- the hyphen makes packages.find blind to it) into an
# sdist and a wheel, and setup.py copies the package.json and package-lock.json
# above into the wheel. tests/test_agents/test_prompt_assets.py and
# tests/test_scripts/test_launcher_sandbox_nodejs.py assert against these
# files, and CI runs the backend suite INSIDE this image, so without them here
# the packaging assertions cannot run where they matter.
COPY pyproject.toml MANIFEST.in setup.py ./
COPY scripts/ scripts/
COPY packages/ packages/
COPY datasets/ datasets/
# The Discovery Catalog's source manifests. Needed for the same reason
# datasets/ is: the catalog root is read from the image, and without this the
# roster is empty and every source is a 404.
COPY discovery/ discovery/
# The Model Catalog's shipped models, read from the image as datasets/ is.
COPY models/ models/
COPY docs/examples/ docs/examples/
COPY docs/schemas/ docs/schemas/
COPY utk_curio/ utk_curio/
# DuckDB's spatial and json extensions, which the backend seeds into
# ~/.duckdb for node runs and serves to the browser worker (#318). Without
# them here every fresh database reaches extensions.duckdb.org.
COPY vendor/ vendor/

# -----------------------------------------------------------------------------
# Stage 2: Build frontends with Node (avoids NodeSource on slim in CI)
# -----------------------------------------------------------------------------
FROM node:26-bookworm-slim AS frontend_builder
# The dependencies first, from the manifests, so a source change reuses the npm
# layer and only rebuilds.
WORKDIR /src/utk_curio/frontend/urban-workflows
COPY utk_curio/frontend/urban-workflows/package.json utk_curio/frontend/urban-workflows/package-lock.json ./
RUN npm install

COPY utk_curio/frontend/ /src/utk_curio/frontend/
COPY packages/ /src/packages/
RUN npm run build

# Record the webpack mode the bundle was built in, in the file curio.py's
# launcher reads (utk_curio/cli/frontend_build.py::_build_stamp_reason). The launcher writes
# this stamp itself, but only when IT runs the build; this stage runs webpack
# directly, and a dist/ with no stamp reads as "built in an unrecorded mode",
# which rebuilds the 9 MB bundle on every container start. The mode is parsed
# from package.json the same way _frontend_build_mode does, so the two cannot
# drift.
RUN node -e "const s=require('./package.json').scripts.build||'';const m=/--mode\s+(\S+)/.exec(s);require('fs').writeFileSync('dist/.curio-build',(m?m[1]:'unknown')+'\n')"

# -----------------------------------------------------------------------------
# Stage 3: Final image: Python runtime + built frontend assets
# -----------------------------------------------------------------------------
FROM runtime_base AS runtime

# Production mode: serve built frontend with Python http.server on 8080
ENV CURIO_DEV=0

# Unprivileged account for isolated node execution
# (utk_curio/sandbox/isolation/). Creating it changes nothing on its own: the
# container still runs as root and no process uses this account unless a launch
# turns isolation on, which --deploy does by discovering this very account. It exists here because the
# account has to be in the image for isolation to have anything to drop to.
#
# Deliberately NOT adding a `USER` directive or chowning anything. CI depends on
# the container running as root and works around bind-mount ownership with
# `umask 000` (see docker-compose.ci.yml), and the live deployments bind-mount
# ./instance, ./.curio and ./datasets from the host. Tightening those globally
# would break both for the sake of a feature that is off by default. The
# permissions that isolation needs are applied at runtime, only when isolation
# is actually enabled, by utk_curio/sandbox/isolation/hardening.py.
RUN groupadd --system curio-exec \
    && useradd --system --gid curio-exec --no-create-home \
        --shell /usr/sbin/nologin curio-exec

# Adjust these COPY paths if your build outputs to "build/" instead of "dist/"
COPY --from=frontend_builder /src/utk_curio/frontend/urban-workflows/dist \
    /app/utk_curio/frontend/urban-workflows/dist

# Expose necessary ports. The sandbox (2000) is deliberately NOT exposed: it
# runs arbitrary user code and is reached only by the backend over loopback
# inside this container.
EXPOSE 5002 8080

# Dockerfile with Health Check
HEALTHCHECK --start-period=180s --interval=30s --timeout=60s --retries=20 CMD \
  curl -sf http://localhost:2000/health && \
  curl -sf http://localhost:5002/health && \
  curl -sf http://localhost:8080

# RUN chmod +x curio.py && ln -s /app/curio.py /usr/local/bin/curio
# The sandbox binds 127.0.0.1 (the default) rather than 0.0.0.0. Backend and
# sandbox share this container, so loopback is all the backend needs, and
# binding the wider interface published an unauthenticated code-execution API
# to anything that could reach the container.
CMD ["python", "curio.py", "start", "all", "--backend-host", "0.0.0.0", "--backend-port", "5002", "--sandbox-port", "2000", "--with-examples"]