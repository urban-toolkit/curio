FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    LOG_TO_STDOUT=true
WORKDIR /app

# Apt-get installation
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl gdal-bin libsm6 libxext6 ffmpeg && \
    curl -fsSL https://deb.nodesource.com/setup_23.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Python Dependencies (cached)
COPY curio.py .
COPY requirements.txt .
COPY templates/ templates/
COPY data/ data/
COPY tests/ tests/
COPY utk_curio/sandbox/utk-0.8.9.tar.gz /app/utk_curio/sandbox/utk-0.8.9.tar.gz
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

# Stage 1: Sandbox
WORKDIR /app/utk_curio/sandbox
COPY utk_curio/sandbox/ .

# Stage 2: Backend
WORKDIR /app/utk_curio/backend
COPY utk_curio/backend/ .
# RUN python create_provenance_db.py && \
    # FLASK_APP=server.py flask db upgrade && \
    # FLASK_APP=server.py flask db migrate -m "Migration"

# Stage 3: Frontend
WORKDIR /app/utk_curio/frontend
COPY utk_curio/frontend/ .

# Stage 4: Other files
WORKDIR /app/utk_curio
COPY utk_curio/ .

WORKDIR /app/utk_curio/frontend/utk-workflow/src/utk-ts
RUN npm install && npm run build

WORKDIR /app/utk_curio/frontend/urban-workflows
RUN npm install && npm run build

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