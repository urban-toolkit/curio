FROM --platform=linux/amd64 python:3.10-slim-bullseye

WORKDIR /app/sandbox

# Clean old apt cache, update, install dependencies with --fix-missing to avoid broken builds,
# and clean apt lists to reduce final image size
RUN apt-get clean && apt-get update && apt-get install -y --fix-missing \
    curl build-essential libgdal-dev ffmpeg libsm6 libxext6 clang libglib2.0-dev python-dev \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

# Install UTK package
COPY . .
RUN pip install utk-0.8.9.tar.gz

# Expose sandbox service port
EXPOSE 2000

# Run sandbox server
WORKDIR /app
CMD ["python", "-m", "sandbox.server"]
