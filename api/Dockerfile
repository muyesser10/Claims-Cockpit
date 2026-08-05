# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
# requirements-worker.txt is deliberately not installed here: it pulls
# sentence-transformers and torch, and nothing under api/ imports either.
# Measured 2026-08-05 (Linux/cp311 wheels): 34 MB of dependencies without them,
# 625 MB with. This image was paying the larger number for code it never ran.
# The cache mount replaces --no-cache-dir - it keeps pip's downloads outside
# the image, so a changed requirements line rebuilds the layer without
# re-fetching every wheel.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt

COPY api /app/api
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY scripts /app/scripts

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
