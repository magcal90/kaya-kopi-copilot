FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       default-mysql-client libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY ingestion/requirements-db.txt /tmp/requirements-db.txt
COPY ingestion/requirements-ocr.txt /tmp/requirements-ocr.txt
RUN python -m pip install --no-cache-dir \
    -r /tmp/requirements-db.txt \
    -r /tmp/requirements-ocr.txt

WORKDIR /workspace
