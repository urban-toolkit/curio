FROM python:3.10-slim

WORKDIR /app/backend

# Install Python dependencies
COPY requirements.txt .
RUN apt update && apt install -y curl gdal-bin libgdal-dev
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

COPY . .
RUN python create_provenance_db.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5002
ENV FLASK_APP=server.py
RUN FLASK_APP=server.py flask db upgrade
RUN FLASK_APP=server.py flask db migrate -m "Migration"
EXPOSE 5002
CMD ["python", "server.py"]
