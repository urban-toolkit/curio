FROM --platform=linux/amd64 python:3.10-slim-bullseye
COPY . /app/sandbox
WORKDIR /app/sandbox
RUN apt-get -y update && apt-get -y install build-essential libgdal-dev ffmpeg libsm6 libxext6 clang libglib2.0-dev python-dev
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install utk-0.8.9.tar.gz
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=2000
ENV FLASK_APP=server.py
EXPOSE 2000

CMD ["python", "server.py"]