# -----------------------------------------------------------------------------
# Stage 1: Build frontends with Node (avoids NodeSource on slim in CI)
# -----------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app

COPY utk_curio/frontend/utk-workflow/src/utk-ts ./utk-ts
RUN cd utk-ts && npm install && npm run build

COPY utk_curio/frontend/urban-workflows ./urban-workflows
RUN cd urban-workflows && npm install && npm run build

# -----------------------------------------------------------------------------
# Stage 2: Unified Python service (no Node required)
# -----------------------------------------------------------------------------
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    LOG_TO_STDOUT=true
WORKDIR /app

# Apt-get installation (no Node - frontend built in previous stage)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl gdal-bin libsm6 libxext6 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python Dependencies (cached)
COPY curio.py .
COPY requirements.txt .
COPY templates/ templates/
COPY tests/ tests/
COPY utk_curio/sandbox/utk-0.8.9.tar.gz /app/utk_curio/sandbox/utk-0.8.9.tar.gz
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

# Stage 1: Sandbox
WORKDIR /app/utk_curio/sandbox
COPY utk_curio/sandbox/ .

# Stage 2: Backend
WORKDIR /app/utk_curio/backend
COPY utk_curio/backend/ .

# Stage 3: Frontend source + rest of utk_curio
WORKDIR /app/utk_curio
COPY utk_curio/ .

# Overlay built frontend artifacts from Node stage
COPY --from=frontend-builder /app/utk-ts/dist /app/utk_curio/frontend/utk-workflow/src/utk-ts/dist
COPY --from=frontend-builder /app/urban-workflows/dist /app/utk_curio/frontend/urban-workflows/dist

# Final Stage: Unified Service
WORKDIR /app

# Expose necessary ports
EXPOSE 2000 5002 8080

# Dockerfile with Health Check
HEALTHCHECK --start-period=120s --interval=15s --timeout=10s --retries=3 CMD \
  curl -sf http://localhost:2000/health && \
  curl -sf http://localhost:5002/health && \
  curl -sf http://localhost:8080
  
# RUN chmod +x curio.py && ln -s /app/curio.py /usr/local/bin/curio
# CMD ["curio", "start", "all", "--backend-host", "0.0.0.0", "--backend-port", "5002", "--sandbox-host", "0.0.0.0", "--sandbox-port", "2000"]
# CMD ["python", "curio.py", "start", "all", "--backend-host", "0.0.0.0", "--backend-port", "5002", "--sandbox-host", "0.0.0.0", "--sandbox-port", "2000"]
CMD ["python", "curio.py", "start", "all", "--backend-host", "0.0.0.0", "--backend-port", "5002", "--sandbox-host", "0.0.0.0", "--sandbox-port", "2000"]