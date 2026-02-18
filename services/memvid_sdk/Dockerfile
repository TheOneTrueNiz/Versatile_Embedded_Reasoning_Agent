FROM python:3.11-slim

RUN pip install --no-cache-dir memvid-sdk

WORKDIR /app
COPY memvid_worker.py /app/memvid_worker.py

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/memvid_worker.py"]
