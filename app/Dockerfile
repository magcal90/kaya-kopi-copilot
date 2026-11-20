FROM python:3.12-slim

COPY app/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace
COPY app /workspace/app

EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
