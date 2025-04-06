FROM python:3.10
COPY . /app/backend
WORKDIR /app/backend
RUN pip install --no-cache-dir -r requirements.txt
RUN python create_provenance_db.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5002
ENV FLASK_APP=server.py
RUN FLASK_APP=server.py flask db upgrade
RUN FLASK_APP=server.py flask db migrate -m "Migration"
EXPOSE 5002
CMD ["python", "server.py"]