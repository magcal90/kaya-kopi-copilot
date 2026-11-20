FROM python:3.12-slim

COPY app/requirements.txt /tmp/app-requirements.txt
COPY ingestion/requirements-db.txt /tmp/ingestion-requirements.txt
RUN python -m pip install --no-cache-dir \
    -r /tmp/app-requirements.txt \
    -r /tmp/ingestion-requirements.txt

WORKDIR /workspace
CMD ["python", "-m", "unittest", "discover", "-v"]
